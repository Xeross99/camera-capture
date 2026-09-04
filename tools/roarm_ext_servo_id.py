#!/usr/bin/env python3
"""Nadanie ID serwu osi 5 (pochylenie kamery) i sprawdzenie, czy odpowiada.

Nowe ST3215 ma fabrycznie ID 1. Na magistrali ramienia RoArm-M2-S fabryczne
serwa zajmują 11–15, aplikacja spodziewa się osi 5 pod `ROBOT_EXT_SERVO_ID`
(domyślnie 16). Zmianę robi komenda 134 z firmware
`firmware/roarm_m2_ext_servo/` — fabryczna 501 dla ID 1 pisze poza tablicę
feedbacku i nie wolno jej tu używać.

    source .venv/bin/activate
    python3 tools/roarm_ext_servo_id.py            # 1 → ROBOT_EXT_SERVO_ID
    python3 tools/roarm_ext_servo_id.py --from 1 --to 16
    python3 tools/roarm_ext_servo_id.py --probe    # tylko odczyt osi 5

Podłącz TYLKO JEDNO serwo o starym ID (fabryczne 11–15 mogą zostać —
nie kolidują). Ramię ma być zasilane z 12 V, inaczej serwo nie odpowie.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ROBOT_EXT_SERVO_ID  # noqa: E402
from src.robot import RoArmSession  # noqa: E402


def describe(ext: dict) -> str:
    return (f"kąt {ext['angle']:+.1f}° (pos {ext['pos']}), obciążenie {ext.get('load')}, "
            f"{ext.get('volt')} V, {ext.get('temp')} °C")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="raw", type=int, default=1, help="obecne ID serwa (fabryczne: 1)")
    ap.add_argument("--to", dest="new", type=int, default=ROBOT_EXT_SERVO_ID or 16,
                    help="nowe ID (domyślnie ROBOT_EXT_SERVO_ID)")
    ap.add_argument("--probe", action="store_true", help="bez zmiany ID — tylko odczyt serwa --to")
    args = ap.parse_args()

    arm = RoArmSession()
    # Ostrzezenie „os 5 nie odpowiada" z open() jest tu SPODZIEWANE (serwo ma
    # jeszcze stare ID) — wlaczamy log dopiero po polaczeniu.
    arm.log = lambda text: None
    try:
        arm.open()
    except Exception as e:
        print(f"✗ {e}")
        return 1
    arm.log = lambda text: print("  " + text)
    print(f"✓ {arm.describe()}")
    try:
        ext = arm.read_ext(args.new)
        if ext is not None:
            print(f"✓ serwo ID {args.new} już odpowiada: {describe(ext)}")
            return 0
        if args.probe:
            print(f"✗ serwo ID {args.new} nie odpowiada — firmware bez komend 130–134 "
                  "(OLED powinien pokazywać „version: 0.84 +ext”), złe ID albo brak zasilania")
            return 1
        if arm.read_ext(args.raw) is None:
            print(f"✗ serwo ID {args.raw} nie odpowiada — sprawdź kabel magistrali i zasilanie 12 V; "
                  "jeśli ramię ma fabryczny firmware, wgraj firmware/roarm_m2_ext_servo/")
            return 1
        print(f"  serwo ID {args.raw} odpowiada — zmieniam na {args.new}…")
        if not arm.ext_set_id(args.raw, args.new):
            print("✗ zmiana ID nie powiodła się (serwo nie potwierdziło pod nowym ID)")
            return 1
        ext = arm.read_ext(args.new)
        if ext is None:
            print(f"✗ po zmianie serwo ID {args.new} milczy — wyłącz i włącz zasilanie ramienia i uruchom --probe")
            return 1
        print(f"✓ serwo ma teraz ID {args.new}: {describe(ext)}")
        print("  Zapis jest w EEPROM serwa — przeżyje wyłączenie zasilania. "
              "Teraz ustaw ujęcia (tools/roarm_teach.py albo Ustawienia → Robot — ujęcia).")
        return 0
    finally:
        arm.close()


if __name__ == "__main__":
    raise SystemExit(main())
