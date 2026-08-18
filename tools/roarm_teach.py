#!/usr/bin/env python3
"""Zapisanie ujęć ramienia RoArm-M2-S — jedno ustawienie na ujęcie.

Ujęcie to cztery kąty przegubów, nie punkt w przestrzeni. Skrypt puszcza serwa,
Ty ustawiasz ramię ręką dokładnie tak, jak ma robić zdjęcie, wciskasz ENTER —
i tyle. Aplikacja odtworzy potem te same kąty co do stopnia, bez kinematyki
odwrotnej, bez tolerancji w milimetrach i bez „odchyłki".

Poprzednia wersja (roarm_calibrate.py) prosiła o ten sam kadr dwa razy, żeby
wyliczyć oś patrzenia i kompensację kąta. Nie działało: bez podglądu nie da się
trafić w ten sam kadr z dwóch różnych odległości, a każda pomyłka rozjeżdżała
cały model. Tutaj nie ma czego pomylić.

Kadr ustawiaj PATRZĄC NA PODGLĄD z aparatu. Najprościej:
  1. w .env: ROBOT_ENABLED=false
  2. `python3 gui.py` — aparat i live view działają, ramienia nie dotyka
  3. w drugim terminalu ten skrypt
  4. po zapisie wróć ROBOT_ENABLED=true

    source .venv/bin/activate
    python3 tools/roarm_teach.py

UWAGA: przy puszczonych serwach ramię opada pod ciężarem aparatu —
przytrzymaj je, zanim wciśniesz ENTER.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ROBOT_JOINTS_ENV, persist_env  # noqa: E402
from src.robot import RoArmSession  # noqa: E402

SHOTS = [
    ("top90", "Z GÓRY", "kamera pionowo nad produktem"),
    ("a45", "Z BOKU", "kamera skośnie na produkt, jak na zdjęciach 3/4"),
]


def main() -> int:
    arm = RoArmSession()
    arm.log = lambda text: print("  " + text)
    try:
        arm.open()
    except Exception as e:
        print(f"✗ {e}")
        return 1
    print(f"✓ {arm.describe()}")
    if not arm.wrist_mode:
        print("⚠ oś 4 została w trybie chwytaka — kamera może nie dać się obrócić")
    print()

    try:
        # Moment jest puszczany DOPIERO po potwierdzeniu: na końcu ramienia
        # wisi korpus z obiektywem i zwolnione serwa oznaczają, że całość
        # opada na stół. To jedyne miejsce w projekcie, gdzie w ogóle
        # zwalniamy moment (aplikacja nie robi tego nawet przy zamykaniu).
        print("⚠ Za chwilę serwa zostaną puszczone i ramię opadnie pod ciężarem aparatu.")
        input("  PRZYTRZYMAJ ramię i wciśnij ENTER… ")
        arm.arm.torque_set(0)
        print("Serwa puszczone — ramię można ustawiać ręcznie.\n")

        saved = []
        for pose, title, desc in SHOTS:
            print(f"— {title} ({desc})")
            ans = input("  Ustaw ramię tak, jak ma robić zdjęcie, i wciśnij ENTER "
                        "(albo `p` żeby pominąć)… ").strip().lower()
            if ans == "p":
                print("     pominięte — ujęcie zostaje takie, jak w .env\n")
                continue
            joints = arm.read_joints()
            if joints is None:
                print("  ✗ ramię nie oddaje odczytu kątów — przerywam")
                return 1
            line = ",".join(f"{v:.1f}" for v in joints)
            key = ROBOT_JOINTS_ENV[pose]
            persist_env(key, line)
            saved.append(f"{key}={line}")
            print(f"     zapisano: {RoArmSession.fmt_joints(joints)}")
            pos = arm.read_pose()
            if pos:
                print(f"     (kamera stoi w {RoArmSession._fmt(pos)})")
            print()

        if saved:
            print("Zapisane w .env:")
            for line in saved:
                print("   " + line)
            print("\nUruchom aplikację i sprawdź ⌘1 / ⌘2 — ramię wróci dokładnie tutaj.")
        else:
            print("Nic nie zapisano.")
    except KeyboardInterrupt:
        print("\nPrzerwane — nic więcej nie zapisano.")
    finally:
        # Moment WRACA zawsze, także po Ctrl+C: bez tego ramię zostaje
        # zwolnione i opada z aparatem po wyjściu ze skryptu.
        try:
            arm.arm.torque_set(1)
        except Exception:
            pass
        arm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
