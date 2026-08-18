"""Ramie RoArm-M2-S (Waveshare) — ustawianie ujecia kamery.

Ujecie to ZAPISANE KATY PRZEGUBOW (`ROBOT_JOINTS_*` w .env, wypisuje je
`tools/roarm_teach.py`), a nie punkt w przestrzeni. Sterowanie wspolrzednymi
(`pose_ctrl`) bylo tu wczesniej i nie nadaje sie do tego zadania: liczy
kinematyke odwrotna, wiec dojezdza „gdzies blisko" celu, a ten sam punkt umie
osiagnac roznym ukladem barku i lokcia, zaleznie od tego, skad ramie jechalo.
Efekt widoczny w logu jako „dojechal z odchylka N mm" i kadr inny po kazdym
uruchomieniu. Przy sterowaniu katami cel jest ta sama liczba za kazdym razem,
wiec pozycja jest powtarzalna — a ugiecie serw pod ciezarem aparatu jest wtedy
stalym przesunieciem, nie losowym bledem.

Cena tej decyzji: odleglosc i kat kamery nie sa regulowane osobno. Ujecie jest
jedna pozycja, ustawiona raz recznie przy podgladzie i odtwarzana bez zmian.

Transport: USB-C -> USB-serial (CH34x) 115200, JSON. Wiekszosc komend idzie
przez oficjalne SDK (`roarm-sdk`), ale ruch skladamy sami i wysylamy
`arm._write()` pod `arm.lock`, bo `calibration_parameters()` w SDK przycina
KAZDA os do -10..100 stopni (jedna tabela dla calego ramienia, niezaleznie od
trybu osi) — a nadgarstek z kamera ma ~270 i realnie tam dojezdza. Przeliczenia
sa dokladnie te, ktore robi SDK, inaczej ta sama liczba oznaczalaby inny kat.

SDK jest zaleznoscia OPCJONALNA: brak paczki albo brak ramienia w porcie to
czytelny komunikat i panel w stanie „rozlaczony", nigdy wywrocony start
aplikacji — na macOS deweloperskim ramienia zwyczajnie nie ma.
"""

from .config import (
    ROBOT_BAUD,
    ROBOT_JOINT_ACC,
    ROBOT_JOINT_SPEED,
    ROBOT_JOINT_TOL,
    ROBOT_JOINTS,
    ROBOT_MOVE_ACC,
    ROBOT_MOVE_SPEED,
    ROBOT_MOVE_TIMEOUT,
    ROBOT_PORT,
    ROBOT_TYPE,
    ROBOT_WRIST_MODE,
)

import json
import logging
import sys
import time


def _muzzle_sdk() -> None:
    """Ucisza SDK: `roarm_sdk` wypisuje KAZDA odebrana ramke feedbacku przez
    goly `print` (`common.py: _process_received`), a przy konstrukcji dokłada
    wlasny handler do ROOT loggera i zbija jego poziom do 0.

    Ramie odpytujemy co ~150 ms, wiec bez tego kazdy przejazd zasypuje terminal
    (i log w .exe) kilkudziesiecioma slownikami, a warningi z cudzych bibliotek
    zaczynaja lecac na stderr.

    Podmieniamy `print` w GLOBALS tych modulow, a nie `sys.stdout` — przekierowanie
    stdout jest globalne dla procesu, wiec watek robota kradlby wyjscie watkowi
    workera (`_LogPipe` przy obrobce zdjecia) i wpisy z pipeline'u znikalyby z logu."""
    for name in ("roarm_sdk.common", "roarm_sdk.utils", "roarm_sdk.generate"):
        mod = sys.modules.get(name)
        if mod is not None:
            mod.print = lambda *a, **k: None


def _restore_logging(handlers: list, level: int) -> None:
    """Zdejmuje handler, ktory SDK dokłada do root loggera przy konstrukcji."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if h not in handlers:
            root.removeHandler(h)
    root.setLevel(level)


# Pozycja domowa w STOPNIACH — te same katy, ktore SDK wysyla w `move_init`
# (radiany [0, 0, 1.5708, 0]), tylko z uzywalnym przyspieszeniem.
HOME_ANGLES = [0.0, 0.0, 90.0, 0.0]

# Plytka sterujaca RoArm-M2-S wystawia sie przez CH343 (QinHeng, VID 0x1A86).
# Po tym VID rozpoznajemy port, gdy ROBOT_PORT nie jest ustawiony w .env.
_ROBOT_VIDS = {0x1A86}
_PORT_HINTS = ("wchusbserial", "usbserial", "ttyUSB", "ttyACM")


class RobotLinkError(RuntimeError):
    """Zerwany/nieotwarty link do ramienia — watek robota reconnectuje."""


class RobotRangeError(RuntimeError):
    """Ramie nie moze wykonac polecenia, ale polaczenie jest zdrowe."""


def _is_data_error(e: Exception) -> bool:
    """Czy to odrzucenie WARTOSCI przez SDK (`RoarmDataException`), a nie awaria
    lacza. SDK sprawdza zakresy jeszcze przed wyslaniem czegokolwiek po
    kablu — potraktowanie tego jak zerwanego linku wywolywaloby bezsensowny
    reconnect ramienia. Rozpoznajemy po NAZWIE klasy, zeby nie robic twardego
    importu z modulu wewnetrznego SDK (`roarm_sdk.utils`), ktory potrafi sie
    przenosic."""
    return type(e).__name__ == "RoarmDataException"


def find_robot_port() -> str | None:
    """Port ramienia: najpierw po VID plytki, potem po nazwie urzadzenia.

    Bez pyserial (SDK nie zainstalowane) zwraca None — wtedy i tak nie ma
    czym gadac, a import ma nie wywalac aplikacji."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    ports = list(list_ports.comports())
    for p in ports:
        if getattr(p, "vid", None) in _ROBOT_VIDS:
            return p.device
    for p in ports:
        if any(h in p.device for h in _PORT_HINTS):
            return p.device
    return None


class RoArmSession:
    """Trwala sesja ramienia. Uzywana z JEDNEGO watku (robot w webui) —
    port szeregowy nie jest wspoldzielony, tak samo jak aparat."""

    def __init__(self) -> None:
        self.arm = None
        self.port: str | None = None
        self.wrist_mode = False
        # wstrzykiwane przez webui (`WebUI._stop.is_set`): czekanie na koniec
        # ruchu ma przerwac zamykanie aplikacji, a nie trzymac ja 20 s
        self.should_stop = lambda: False
        # kanal do logu UI (wstrzykiwany przez webui, jak `on_log` w EDSDK) —
        # inaczej ostrzezenia z ustawiania osi zniknelyby w spakowanym .exe
        self.log = lambda text: None

    # ---------- polaczenie ----------

    def open(self) -> None:
        if self.arm is not None:
            return
        try:
            from roarm_sdk.roarm import roarm
        except ImportError as e:
            raise RobotLinkError(
                "brak pakietu roarm-sdk (pip install -r requirements.txt) — "
                f"sterowanie ramieniem wyłączone ({e})") from e
        port = ROBOT_PORT or find_robot_port()
        if not port:
            raise RobotLinkError(
                "nie znaleziono portu ramienia — sprawdź kabel USB-C i zasilanie "
                "(port można wskazać ręcznie: ROBOT_PORT w .env)")
        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        try:
            self.arm = roarm(roarm_type=ROBOT_TYPE, port=port, baudrate=ROBOT_BAUD)
        except Exception as e:   # pyserial/SDK — typ wyjatku niepewny
            self.arm = None
            raise RobotLinkError(f"nie mogę otworzyć {port}: {e}") from e
        finally:
            _muzzle_sdk()
            _restore_logging(handlers, level)
        self.port = port
        try:
            self.arm.torque_set(1)
        except Exception as e:
            self.close()
            raise RobotLinkError(f"ramię nie odpowiada na {port}: {e}") from e
        self.wrist_mode = False
        if ROBOT_WRIST_MODE:
            # Joint 4 jako NADGARSTEK, nie chwytak: w trybie chwytaka ta sama os
            # zaciska szczeki zamiast obracac glowica z kamera.
            try:
                self.arm.gripper_mode_set(1)
                self.wrist_mode = True
            except Exception as e:
                self.log(f"Robot: nie udało się przełączyć osi 4 w tryb nadgarstka ({e}) "
                         "— kamera może nie dać się obrócić")

    def close(self) -> None:
        arm, self.arm = self.arm, None
        if arm is None:
            return
        # NIE puszczamy tu momentu (`torque_set(0)`), choc przy zamykaniu
        # wygladaloby to naturalnie: na koncu ramienia wisi korpus z
        # obiektywem, wiec zwolnione serwa = ramie opada z aparatem na stol.
        # Serwa trzymaja pozycje same, dopoki plytka ma zasilanie.
        #
        # Nazwa metody zamykajacej roznila sie miedzy wersjami SDK, a port MUSI
        # zostac zwolniony (inaczej kolejny start dostaje „resource busy") —
        # probujemy po kolei, lacznie z golym pyserial pod spodem.
        for call in (lambda: arm.disconnect(),
                     lambda: arm.ser.close()):
            try:
                call()
            except Exception:
                pass

    def describe(self) -> str:
        return f"{ROBOT_TYPE} na {self.port} @ {ROBOT_BAUD}"

    # ---------- odczyt ----------

    def read_pose(self) -> list[float] | None:
        """[x, y, z, t] z ramienia albo None, gdy SDK nie oddaje odczytu.

        Do sterowania NIEuzywane (jedziemy katami) — sluzy do logu i do
        podpowiedzi, gdzie ramie stoi."""
        if self.arm is None:
            return None
        try:
            pose = self.arm.pose_get()
        except Exception:
            return None
        if not pose or len(pose) < 4:
            return None
        try:
            return [float(v) for v in pose[:4]]
        except (TypeError, ValueError):
            return None

    def read_joints(self) -> list[float] | None:
        """[j1, j2, j3, j4] w STOPNIACH (tak jak przyjmuja komendy ruchu;
        `feedback_get` oddaje radiany, wiec swiadomie nie tamtedy)."""
        if self.arm is None:
            return None
        try:
            joints = self.arm.joints_angle_get()
        except Exception:
            return None
        if not joints or len(joints) < 4:
            return None
        try:
            return [float(v) for v in joints[:4]]
        except (TypeError, ValueError):
            return None

    # ---------- ruch ----------

    def move(self, pose: str) -> None:
        """Ustawia ramie w zapisanym ujeciu i CZEKA, az dojedzie.

        Komendy w tym SDK sa asynchroniczne — wracaja od razu, a ramie jedzie
        dalej. Bez czekania `robot_busy` gaslby natychmiast i migawka
        odblokowywalaby sie w polowie ruchu."""
        if self.arm is None:
            raise RobotLinkError("ramię nie jest połączone")
        angles = ROBOT_JOINTS.get(pose)
        if not angles:
            raise RobotRangeError(
                f"ujęcie „{pose}” nie jest ustawione — uruchom tools/roarm_teach.py, "
                "ustaw ramię ręcznie i zapisz")
        self.move_joints(angles)

    def move_joints(self, angles: list[float]) -> None:
        """Przejazd na cztery zadane katy przegubow.

        Ramie i glowica dostaja OSOBNE komendy, mimo ze pierwsza zawiera juz
        docelowy kat osi 4: druga nadpisuje go z wlasna, wyzsza predkoscia.
        Wysieg z aparatem musi jechac wolno, bo szarpniecie przenosi sie na
        stol, ale sama glowica nie ma czego rozhustac — a `_wait_joints` czeka
        na wszystkie osie, wiec jej spowolnienie wydluzaloby kazdy przejazd."""
        self._send_joints(angles)
        self._send_joint4(angles[3])
        self._wait_joints(angles)

    def home(self) -> None:
        """Przejazd do pozycji domowej (`j1 0, j2 0, j3 90, j4 0`).

        SWIADOMIE nie uzywamy `move_init()` z SDK: ta funkcja wysyla
        `joints_radian_ctrl(..., speed=100, acc=0)`, czyli z ZEROWYM
        przyspieszeniem — mimo ze jej wlasna dokumentacja podaje zakres
        acc [1,254]. Walidacja zero przepuszcza, komenda wychodzi po kablu i nic
        sie nie dzieje: ramie stoi tam, gdzie stalo, a log twierdzi, ze pozycja
        domowa zostala ustawiona."""
        if self.arm is None:
            raise RobotLinkError("ramię nie jest połączone")
        self.move_joints(list(HOME_ANGLES))

    def _send_joints(self, angles: list[float]) -> None:
        """Komenda 122 (wszystkie przeguby) sklejona samodzielnie.

        SDK wysyla ja przez `joints_angle_ctrl`, ale przepuszcza katy przez
        `calibration_parameters()`, ktore przycina KAZDA os do -10..100 stopni.
        Nadgarstek z kamera ma ~270 stopni i realnie tam dojezdza, wiec ta
        walidacja odrzucalaby poprawne ujecia.

        Przeliczenia sa DOKLADNIE te, ktore robi `handle_m2_joints_angle`: kat
        osi 4 wchodzi jako `180 - h`, `spd` skalowane przez 180/2048, `acc`
        przez 180/(254*100)."""
        j1, j2, j3, j4 = angles
        payload = json.dumps({"T": 122,
                              "b": round(j1, 2), "s": round(j2, 2),
                              "e": round(j3, 2), "h": round(180.0 - j4, 2),
                              "spd": round(ROBOT_MOVE_SPEED * 180 / 2048, 3),
                              "acc": round(ROBOT_MOVE_ACC * 180 / (254 * 100), 4)})
        self._write(payload, "przejazd")

    def _send_joint4(self, angle: float) -> None:
        """Komenda 121 dla osi 4 — glowica z kamera, z jej wlasna predkoscia."""
        self._send_joint(4, angle)

    def _send_joint(self, joint: int, angle: float) -> None:
        """Komenda 121 (jedna os) sklejona samodzielnie.

        Odwrocenie `180 - angle` dotyczy TYLKO osi 4 — dokladnie tak samo, jak
        w `handle_joint_angle_ctrl` w SDK. Pozostale osie ida wprost.
        Predkosc tez zalezy od osi: glowica moze chodzic szybciej niz wysieg,
        ktory przenosi szarpniecie na stol."""
        fast = joint == 4
        spd = ROBOT_JOINT_SPEED if fast else ROBOT_MOVE_SPEED
        acc = ROBOT_JOINT_ACC if fast else ROBOT_MOVE_ACC
        payload = json.dumps({"T": 121, "joint": joint,
                              "angle": round(180.0 - angle if fast else angle, 2),
                              "spd": round(spd * 180 / 2048, 3),
                              "acc": round(acc * 180 / (254 * 100), 4)})
        self._write(payload, f"ruch osi {joint}")

    def nudge(self, joint: int, delta: float) -> list[float] | None:
        """Korekta JEDNEJ osi o `delta` stopni od jej biezacego kata.

        Wzgledna, nie bezwzgledna: operator patrzy na kadr, nie na liczby, wiec
        interesuje go „o stopien wyzej", a nie „na 47 stopni". Zwraca odczyt po
        ruchu albo None, gdy ramie nie oddaje katow."""
        if self.arm is None:
            raise RobotLinkError("ramię nie jest połączone")
        joints = self.read_joints()
        if joints is None:
            return None
        want = joints[joint - 1] + delta
        self._send_joint(joint, want)
        # NIE przez `_wait_joints`: tam tolerancja (ROBOT_JOINT_TOL) jest wieksza
        # niz maly krok korekty, wiec cel bylby „osiagniety" jeszcze przed
        # ruchem i odczyt wrocilby sprzed komendy — z UI wygladalo to jak
        # „klikam i nic sie nie dzieje".
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            time.sleep(0.12)
            if self.should_stop():
                break
            now = self.read_joints()
            if now is None:
                return None
            if abs(now[joint - 1] - want) <= 0.6:
                return now
        return self.read_joints()

    def _write(self, payload: str, what: str) -> None:
        """Wysyla goly JSON tym samym kanalem, ktorego uzywa SDK.

        `arm.lock` to ten sam zamek, pod ktorym SDK wysyla swoje komendy —
        watek robota jest jedynym pisarzem, ale feedback czyta ta sama warstwa."""
        try:
            with self.arm.lock:
                self.arm._write((payload + "\n").encode())
        except Exception as e:
            raise RobotLinkError(f"{what}: komenda nie doszła ({e})") from e

    def _wait_joints(self, target: list[float]) -> None:
        """Czeka, az wszystkie przeguby trafia w zadane katy.

        Po przekroczeniu czasu mowimy wprost, ktora os nie dojechala i o ile —
        najczestsza przyczyna to brak zasilania serw albo mechaniczna blokada,
        a nie zla wartosc."""
        deadline = time.monotonic() + ROBOT_MOVE_TIMEOUT
        joints: list[float] | None = None
        while time.monotonic() < deadline:
            time.sleep(0.15)
            if self.should_stop():
                return
            joints = self.read_joints()
            if joints is None:
                return      # SDK nie oddaje odczytu — lepiej to niz udawanie
            if all(abs(j - t) <= ROBOT_JOINT_TOL for j, t in zip(joints, target)):
                return
        now = joints or target
        miss = max(range(4), key=lambda i: abs(now[i] - target[i]))
        raise RobotRangeError(
            f"ramię nie dojechało: oś {miss + 1} jest pod {now[miss]:.0f}°, "
            f"a ma być {target[miss]:.0f}° — sprawdź zasilanie 12 V "
            "i czy nic go nie blokuje")

    @staticmethod
    def _fmt(pose: list[float]) -> str:
        return "x{:.0f} y{:.0f} z{:.0f} t{:.0f}".format(*pose[:4])

    @staticmethod
    def fmt_joints(joints: list[float]) -> str:
        return " ".join(f"j{i + 1} {v:.1f}°" for i, v in enumerate(joints))
