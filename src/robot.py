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

Os 5 (`ROBOT_EXT_SERVO_ID`, domyslnie serwo ID 16): dodatkowe ST3215 dopiete
do magistrali ZA osia 4, na koncu wysiegnika, pochyla kamere. Sama os 4
obraca glowice tylko w jednej plaszczyznie, wiec z czterema osiami ujecie
z gory i skos 45 wymagaly przestawiania produktu; z piata osia produkt stoi
raz, a ramie przejezdza miedzy ujeciami. Fabryczny firmware zna tylko serwa
11–15 — os 5 gada komendami 130–134 z `firmware/roarm_m2_ext_servo/`
(kat w stopniach, 0 = srodek zakresu serwa; spd/acc w SUROWYCH krokach, czyli
dokladnie ROBOT_JOINT_SPEED/ACC z konfiguracji, bez podwojnego przeliczania).
Odpowiedzi (`T:1131`, `T:1134`) czytamy sami z portu pod `arm.lock`, bo SDK
rozumie tylko feedback 1051.
"""

from .config import (
    ROBOT_AXES,
    ROBOT_BAUD,
    ROBOT_EXT_SERVO_ID,
    ROBOT_JOINT_ACC,
    ROBOT_JOINT_SPEED,
    ROBOT_JOINT_TOL,
    ROBOT_JOINTS,
    ROBOT_LIFT_FIRST,
    ROBOT_MOVE_ACC,
    ROBOT_MOVE_SPEED,
    ROBOT_MOVE_TIMEOUT,
    ROBOT_PORT,
    ROBOT_SETTLE_ROUNDS,
    ROBOT_SETTLE_TOL,
    ROBOT_TYPE,
    ROBOT_WRIST_MODE,
)

import json
import logging
import math
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
# (radiany [0, 0, 1.5708, 0]), tylko z uzywalnym przyspieszeniem. Os 5 (gdy
# jest) idzie na 0 = srodek zakresu serwa.
HOME_ANGLES = [0.0, 0.0, 90.0, 0.0]

# Dlugosci ogniw RoArm-M2-S (mm) z RoArm-M2_config.h firmware — do
# wysokosci nadgarstka (`wrist_height`), nie do sterowania.
_L2_A, _L2_B = 236.82, 30.00        # ramie: bark → lokiec (z odsadzeniem)
_L3_A = 215.99                       # przedramie w trybie nadgarstka (EEMode 1)
_L2 = math.hypot(_L2_A, _L2_B)
_T2 = math.atan2(_L2_B, _L2_A)

# Podzial osi na fazy przejazdu: „podnoszenie" to bark i lokiec, „obrot" to
# podstawa, glowica i pochylenie kamery (indeksy 0-based).
_LIFT_AXES = (1, 2)
_TURN_AXES = (0, 3, 4)
_LIFT_MIN_DZ = 20.0                  # mm — mniejsza roznica wysokosci = jedna faza
_TURN_MIN_DEG = 3.0                  # obrot mniejszy niz to nie wymaga faz


def wrist_height(j2: float, j3: float) -> float:
    """Wysokosc nadgarstka nad osia barku (mm) — wzor z
    `RoArmM2_computePosbyJointRad` w firmware (bez czlonu koncowki, ktory
    zalezy od osi 4 i jest maly wobec ogniw). Sluzy tylko do decyzji
    „cel jest wyzej czy nizej"."""
    s = math.radians(j2)
    e = math.radians(j3)
    return _L2 * math.cos(s + _T2) + _L3_A * math.cos(s + e)

# Komendy osi 5 z firmware/roarm_m2_ext_servo/ext_servo.h.
_EXT_CMD_ANGLE, _EXT_CMD_FEEDBACK, _EXT_CMD_TORQUE, _EXT_CMD_SET_ID = 130, 131, 132, 134
# Ile czekamy na odpowiedz serwa przez plytke: jeden obrot petli firmware to
# odczyt feedbacku wszystkich serw (~10 ms), a InfoPrint=1 wypisuje wczesniej
# echo naszej komendy.
_EXT_REPLY_TIMEOUT_S = 0.5

# Plytka sterujaca RoArm-M2-S wystawia sie przez CH343 (QinHeng, VID 0x1A86)
# albo — zmierzone na naszym egzemplarzu — przez CP2102N (Silicon Labs,
# VID 0x10C4). Po tym VID rozpoznajemy port, gdy ROBOT_PORT nie jest
# ustawiony w .env; dalej jest fallback po nazwie urzadzenia.
_ROBOT_VIDS = {0x1A86, 0x10C4}
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
        # jedno ostrzezenie o niemej osi 5 na polaczenie — odczyt katow idzie
        # co sekunde i bez tego log zalalby sie tym samym wpisem
        self._ext_warned = False
        # nauczona poprawka ugiecia per ujecie (stopnie, per os) — patrz
        # `_settle`; zyje tylko w pamieci, bo zalezy od tego, co wisi na koncu
        self._trim: dict[str, list[float]] = {}

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
        self._ext_warned = False
        if ROBOT_AXES == 5 and self.read_ext() is None:
            # Polaczenie ZOSTAJE (plytka odpowiada, cztery osie dzialaja) —
            # ale bez osi 5 zadne ujecie nie jest kompletne, wiec mowimy
            # od razu, czego szukac. Najczestsze przyczyny w tej kolejnosci.
            self._warn_ext()

    def _warn_ext(self) -> None:
        if self._ext_warned:
            return
        self._ext_warned = True
        self.log(f"Robot: oś 5 (serwo ID {ROBOT_EXT_SERVO_ID}) nie odpowiada — sprawdź: "
                 "(1) czy w ramieniu jest firmware z firmware/roarm_m2_ext_servo "
                 "(OLED: „version: 0.84 +ext”), (2) czy serwo ma nadane ID "
                 f"{ROBOT_EXT_SERVO_ID} (tools/roarm_ext_servo_id.py), (3) kabel magistrali")

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
        """[j1, j2, j3, j4(, j5)] w STOPNIACH (tak jak przyjmuja komendy ruchu;
        `feedback_get` oddaje radiany, wiec swiadomie nie tamtedy).

        Przy piecu osiach brak odczytu osi 5 = brak odczytu W OGOLE (None):
        cztery katy bez pochylenia kamery nie opisuja ujecia, a zapisanie ich
        jako ujecia dawaloby kadr „prawie dobry" bez sladu, czemu."""
        if self.arm is None:
            return None
        try:
            joints = self.arm.joints_angle_get()
        except Exception:
            return None
        if not joints or len(joints) < 4:
            return None
        try:
            out = [float(v) for v in joints[:4]]
        except (TypeError, ValueError):
            return None
        if ROBOT_AXES == 5:
            ext = self.read_ext()
            if ext is None:
                self._warn_ext()
                return None
            out.append(ext["angle"])
        return out

    # ---------- os 5: serwo poza SDK ----------

    def read_ext(self, servo_id: int | None = None) -> dict | None:
        """Odczyt dodatkowego serwa: {"angle", "pos", "load", "volt", "temp"}
        albo None (serwo/firmware nie odpowiada)."""
        sid = servo_id or ROBOT_EXT_SERVO_ID
        reply = self._ext_query({"T": _EXT_CMD_FEEDBACK, "id": sid}, _EXT_CMD_FEEDBACK + 1000)
        if not reply or not reply.get("ok"):
            return None
        try:
            return {"angle": float(reply["angle"]), "pos": int(reply["pos"]),
                    "load": reply.get("load"), "volt": reply.get("volt"),
                    "temp": reply.get("temp")}
        except (KeyError, TypeError, ValueError):
            return None

    def ext_torque(self, on: bool, servo_id: int | None = None) -> None:
        """Moment jednego serwa przez komende 132 (ID 254 = wszystkie)."""
        payload = json.dumps({"T": _EXT_CMD_TORQUE, "id": servo_id or ROBOT_EXT_SERVO_ID,
                              "cmd": 1 if on else 0})
        self._write(payload, "moment serw")

    def set_torque(self, on: bool) -> None:
        """Puszcza (False) albo lapie (True) WSZYSTKIE serwa — do recznego
        ustawiania ujecia.

        Z naszym firmware idzie to komenda 132 na broadcast 254, a NIE przez
        `torque_set` z SDK (komenda 210): firmware Waveshare z 2026 przy
        `210 cmd:0` najpierw wola `Move_to_location()` — jedzie ramieniem do
        pozycji parkingowej i czeka w petli na dojazd kazdej osi — i dopiero
        potem zwalnia serwa. Operator, ktory wlasnie trzyma ramie z aparatem,
        blokuje ten dojazd, wiec firmware wisi, a serwa nigdy nie puszczaja
        (objaw: „Puść serwa" nic nie robi). 132 to golo `EnableTorque`, bez
        parkowania. Na fabrycznym firmware (ROBOT_AXES == 4) zostaje SDK."""
        if self.arm is None:
            raise RobotLinkError("ramię nie jest połączone")
        if ROBOT_AXES == 5:
            self.ext_torque(on, servo_id=254)
            return
        try:
            self.arm.torque_set(1 if on else 0)
        except Exception as e:
            raise RobotLinkError(f"moment serw: {e}") from e

    def ext_set_id(self, raw_id: int, new_id: int) -> bool:
        """Nadanie ID nowemu serwu (fabrycznie 1) — komenda 134 z naszego
        firmware, bezpieczna dla kazdego `raw` (fabryczna 501 indeksuje tablice
        feedbacku `raw - 11`, wiec dla ID 1 pisze poza nia)."""
        reply = self._ext_query({"T": _EXT_CMD_SET_ID, "raw": raw_id, "new": new_id},
                                _EXT_CMD_SET_ID + 1000, timeout=2.0)
        return bool(reply and reply.get("ok"))

    def _ext_query(self, cmd: dict, reply_t: int, timeout: float = _EXT_REPLY_TIMEOUT_S) -> dict | None:
        """Komenda z odpowiedzia. Pod `arm.lock`, bo czytamy z portu obok SDK;
        `_write` SDK czysci bufor wejsciowy PRZED wyslaniem, wiec to, co
        przychodzi potem, jest odpowiedzia na nas — pomijamy tylko echo komendy
        (InfoPrint=1) i ewentualny feedback 1051 z trybu flow."""
        if self.arm is None:
            raise RobotLinkError("ramię nie jest połączone")
        payload = (json.dumps(cmd) + "\n").encode()
        try:
            with self.arm.lock:
                self.arm._write(payload)
                port = self.arm._serial_port
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    line = port.readline()
                    if not line:
                        continue
                    line = line.strip()
                    if not line.startswith(b"{"):
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(data, dict) and data.get("T") == reply_t:
                        return data
        except Exception as e:
            raise RobotLinkError(f"oś 5: komenda nie doszła ({e})") from e
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
        trim = self._trim.get(pose)
        if trim is None or len(trim) != len(angles):
            trim = self._trim[pose] = [0.0] * len(angles)
        self.move_joints(angles, trim)

    def move_joints(self, angles: list[float], trim: list[float] | None = None) -> None:
        """Przejazd na zadane katy przegubow (4 albo 5, wg ROBOT_AXES).

        `trim` (opcjonalnie, modyfikowany W MIEJSCU) to nauczona poprawka
        ugiecia per os: komenda idzie na `angles + trim`, a po dojezdzie
        `_settle` dociaga osie do `angles` i aktualizuje `trim`.

        Ramie i glowica dostaja OSOBNE komendy, mimo ze pierwsza zawiera juz
        docelowy kat osi 4: druga nadpisuje go z wlasna, wyzsza predkoscia.
        Wysieg z aparatem musi jechac wolno, bo szarpniecie przenosi sie na
        stol, ale sama glowica nie ma czego rozhustac — a `_wait_joints` czeka
        na wszystkie osie, wiec jej spowolnienie wydluzaloby kazdy przejazd.
        Os 5 (pochylenie kamery) jedzie z ta sama predkoscia co os 4 — to tez
        sama glowica."""
        if len(angles) != ROBOT_AXES:
            raise RobotRangeError(
                f"ujęcie ma {len(angles)} kątów, a ramię {ROBOT_AXES} osi — ustaw je ponownie")
        cmd = [a + t for a, t in zip(angles, trim)] if trim else list(angles)
        phases = self._plan_phases(cmd)
        if phases is None:
            self._send_joints(cmd[:4])
            self._send_joint4(cmd[3])
            if ROBOT_AXES == 5:
                self._send_joint(5, cmd[4])
            now = self._wait_joints(cmd)
        else:
            now = None
            for axes, start in phases:
                target = list(start)
                for i in axes:
                    target[i] = cmd[i]
                    self._send_joint(i + 1, cmd[i])
                now = self._wait_joints(target)
                if now is None:
                    break
        if trim is not None:
            now = self._settle(angles, trim)
        self._check_arrived(angles, now)

    def _plan_phases(self, cmd: list[float]) -> list[tuple[tuple[int, ...], list[float]]] | None:
        """Kolejnosc faz przejazdu albo None (= wszystko naraz).

        Obrot glowicy z aparatem o ~210° w trakcie podnoszenia z ujecia
        „z boku" konczyl sie uderzeniem aparatu o blat: wszystkie osie ruszaly
        naraz, wiec glowica krecila sie, gdy ramie bylo jeszcze nisko. Gdy cel
        jest wyzej — najpierw bark i lokiec (podniesienie), potem obrot
        podstawy/glowicy/pochylenia; gdy nizej — obrot na gorze, potem
        opuszczanie. Kazda faza to lista osi do ruszenia i katy, na ktorych
        stoja pozostale (do czekania na dojazd)."""
        if not ROBOT_LIFT_FIRST:
            return None
        now = self.read_joints()
        if now is None or len(now) != len(cmd):
            return None
        turn = [i for i in _TURN_AXES if i < len(cmd) and abs(cmd[i] - now[i]) > _TURN_MIN_DEG]
        dz = wrist_height(cmd[1], cmd[2]) - wrist_height(now[1], now[2])
        if not turn or abs(dz) < _LIFT_MIN_DZ:
            return None
        lift = tuple(i for i in _LIFT_AXES if abs(cmd[i] - now[i]) > 0.5)
        turn_t = tuple(turn)
        if dz > 0:
            after_lift = list(now)
            for i in lift:
                after_lift[i] = cmd[i]
            return [(lift, now), (turn_t, after_lift)]
        after_turn = list(now)
        for i in turn_t:
            after_turn[i] = cmd[i]
        return [(turn_t, now), (lift, after_turn)]

    def _settle(self, target: list[float], trim: list[float]) -> list[float] | None:
        """Dociaga osie do `target` po dojezdzie. Zwraca ostatni odczyt katow.

        Serwo pod stalym obciazeniem zatrzymuje sie z bledem ustalonym —
        z aparatem na wysiegu kadr wychodzil zawsze „lekko nizej" niz ustawiony
        z reki. Blad jest powtarzalny, wiec leczymy go jak przesuniecie:
        os, ktora stanela o d za daleko od celu, dostaje cel + (−d) i tak w
        kolku, maksymalnie ROBOT_SETTLE_ROUNDS razy. Nauczone przesuniecie
        zostaje w `trim`, wiec nastepny przejazd na to ujecie od razu jedzie
        skorygowany i zwykle konczy sie bez rund."""
        now = self.read_joints()
        if ROBOT_SETTLE_ROUNDS <= 0 or now is None:
            return now
        limit = 20.0        # bezpiecznik: poprawka wieksza niz to nie jest ugieciem
        rounds = 0
        stuck: set[int] = set()     # osie, ktore nie reaguja — koniec zakresu / blokada
        for _ in range(ROBOT_SETTLE_ROUNDS):
            if self.should_stop():
                return now
            err = [t - n for t, n in zip(target, now)]
            fix = [i for i, e in enumerate(err)
                   if abs(e) > ROBOT_SETTLE_TOL and i not in stuck]
            if not fix:
                break
            rounds += 1
            before = now
            added: dict[int, float] = {}
            for i in fix:
                new_trim = max(-limit, min(limit, trim[i] + err[i]))
                added[i] = new_trim - trim[i]
                trim[i] = new_trim
                self._send_joint(i + 1, target[i] + trim[i])
            now = self._wait_still()
            if now is None:
                return None
            # Os, ktora mimo DUZEJ poprawki (>= 5°) nie drgnela, stoi na koncu
            # zakresu albo jest zablokowana — dalsze pchanie tylko zjada rundy
            # i nabija trim, wiec oddajemy dokladnie to, co dodalismy. Mala
            # poprawka bez ruchu to co innego: bark ma martwa strefe ~2–3° i
            # rusza dopiero, gdy kolejna runda dolozy drugie tyle.
            for i in fix:
                if abs(now[i] - before[i]) < 0.3 and abs(added[i]) >= 5.0:
                    stuck.add(i)
                    trim[i] -= added[i]
        resid = max(abs(t - n) for t, n in zip(target, now))
        applied = " ".join(f"j{i + 1} {v:+.1f}°" for i, v in enumerate(trim) if abs(v) >= 0.1)
        if rounds:
            self.log(f"Robot: dociągnięcie w {rounds} rund. ({applied or 'bez zmian'}), "
                     f"pozostały błąd {resid:.1f}°")
        return now

    def _check_arrived(self, target: list[float], now: list[float] | None) -> None:
        """Po dojezdzie i dociaganiu: odchylka wieksza niz ROBOT_JOINT_TOL to
        juz nie ugiecie, tylko blokada albo brak zasilania — mowimy, ktora os."""
        if now is None:
            return          # brak odczytu — lepiej to niz udawanie
        miss = max(range(len(target)), key=lambda i: abs(now[i] - target[i]))
        if abs(now[miss] - target[miss]) > ROBOT_JOINT_TOL:
            raise RobotRangeError(
                f"ramię nie dojechało: oś {miss + 1} stoi na {now[miss]:.0f}°, "
                f"a ma być {target[miss]:.0f}° — albo to koniec zakresu tej osi "
                "(ręką da się ją przekręcić dalej niż dojedzie silnik: ustaw ujęcie "
                "od nowa bliżej środka zakresu), albo brak zasilania 12 V / blokada")

    def _wait_still(self, timeout: float = 2.5) -> list[float] | None:
        """Czeka, az osie przestana sie ruszac (dwa kolejne odczyty zgodne
        do 0,2°) i zwraca ostatni odczyt. `_wait_joints` ma tolerancje
        ROBOT_JOINT_TOL, czyli wieksza niz sama poprawka — wrocilby przed
        ruchem. Pierwszy odczyt po krotkiej pauzie, zeby serwo zdazylo ruszyc."""
        deadline = time.monotonic() + timeout
        time.sleep(0.25)
        prev = self.read_joints()
        now = prev
        while time.monotonic() < deadline and not self.should_stop():
            time.sleep(0.15)
            now = self.read_joints()
            if now is None:
                return None
            if prev is not None and all(abs(a - b) <= 0.2 for a, b in zip(now, prev)):
                return now
            prev = now
        return now

    def verify_pose(self, angles: list[float]) -> list[float] | None:
        """Sprawdza, czy SILNIKI utrzymaja zadane katy: dosyla je jako cel
        (ramie juz tam stoi, wiec ruch jest znikomy), dociaga i oddaje
        odczyt. Uzywane zaraz po zapisie ujecia: ujecie ustawione reka przy
        puszczonych serwach potrafi lezec poza zakresem, w ktory serwo w ogole
        dojezdza (zmierzone na osi 4: reka −115°, silnik konczy na ~−107°) —
        lepiej uslyszec to przy zapisie niz przy pierwszym ⌘1."""
        trim = [0.0] * len(angles)
        cmd = list(angles)
        self._send_joints(cmd[:4])
        self._send_joint4(cmd[3])
        if ROBOT_AXES == 5:
            self._send_joint(5, cmd[4])
        self._wait_joints(cmd)
        return self._settle(angles, trim)

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
        self.move_joints(list(HOME_ANGLES) + ([0.0] if ROBOT_AXES == 5 else []))

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
        """Komenda 121 (jedna os) sklejona samodzielnie; os 5 idzie komenda
        130 z naszego firmware.

        Odwrocenie `180 - angle` dotyczy TYLKO osi 4 — dokladnie tak samo, jak
        w `handle_joint_angle_ctrl` w SDK. Pozostale osie ida wprost.
        Predkosc tez zalezy od osi: glowica moze chodzic szybciej niz wysieg,
        ktory przenosi szarpniecie na stol."""
        if joint == 5:
            # spd/acc SUROWE — firmware nie przelicza ich przez stopnie, wiec
            # nie ma tu skalowania 180/2048 jak przy 121/122
            payload = json.dumps({"T": _EXT_CMD_ANGLE, "id": ROBOT_EXT_SERVO_ID,
                                  "angle": round(angle, 2),
                                  "spd": int(ROBOT_JOINT_SPEED), "acc": int(ROBOT_JOINT_ACC)})
            self._write(payload, "ruch osi 5")
            return
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
        if not 1 <= joint <= ROBOT_AXES:
            raise RobotRangeError(f"ramię nie ma osi {joint}")
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

    def _wait_joints(self, target: list[float]) -> list[float] | None:
        """Czeka na koniec przejazdu i zwraca ostatni odczyt katow.

        Koniec = wszystkie osie w ROBOT_JOINT_TOL od celu ALBO ramie przestalo
        sie ruszac (odczyty zgodne do 0,2° przez ~1 s). To drugie jest
        potrzebne, bo serwo pod ciezarem aparatu potrafi stanac dalej niz
        tolerancja (zmierzone: lokiec 4,4°) — wczesniej konczylo sie to pelnym
        ROBOT_MOVE_TIMEOUT i bledem „nie dojechalo", zamiast dociaganiem.
        O tym, czy ramie faktycznie dojechalo, decyduje `_check_arrived` po
        dociaganiu. Po przekroczeniu czasu (ramie caly czas w ruchu — np. os
        oscyluje) rzucamy z nazwa osi."""
        deadline = time.monotonic() + ROBOT_MOVE_TIMEOUT
        joints: list[float] | None = None
        prev: list[float] | None = None
        still_since: float | None = None
        while time.monotonic() < deadline:
            time.sleep(0.15)
            if self.should_stop():
                return None
            joints = self.read_joints()
            if joints is None:
                return None     # SDK nie oddaje odczytu — lepiej to niz udawanie
            if all(abs(j - t) <= ROBOT_JOINT_TOL for j, t in zip(joints, target)):
                return joints
            moving = prev is None or any(abs(j - p) > 0.2 for j, p in zip(joints, prev))
            if moving:
                still_since = None
            elif still_since is None:
                still_since = time.monotonic()
            elif time.monotonic() - still_since >= 1.0:
                return joints   # stanelo poza tolerancja — dociaganie / _check_arrived
            prev = joints
        now = joints or target
        miss = max(range(len(target)), key=lambda i: abs(now[i] - target[i]))
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
