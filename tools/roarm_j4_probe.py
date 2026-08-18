#!/usr/bin/env python3
"""Pomiar skali osi 4 (nadgarstek z kamerą) — diagnostyka, nie konfiguracja.

Po co: odczyt kątów (`joints_angle_get`) NIE przechodzi w SDK przez żadną
konwersję, ale przy zadawaniu SDK odwraca wartość osi 4 (`180 − angle`,
`handle_joint_angle_ctrl`). Jeśli obie strony są w tej samej skali, zapisany
odczyt trzeba wysyłać wprost; jeśli nie — z odwróceniem. Pomyłka daje objaw
„oś 4 jest pod −51°, a ma być −13°": komenda wychodzi, ramię jej nie wykonuje.

Skrypt wysyła oś 4 na kilka kątów w OBU konwencjach i po każdym czyta, gdzie
faktycznie stanęła. Ta konwencja, w której odczyt zgadza się z celem, jest
prawdziwa. Moment NIE jest zwalniany — ramię trzyma się samo.

    source .venv/bin/activate
    python3 tools/roarm_j4_probe.py

Zamknij najpierw gui.py — port szeregowy ma jednego właściciela.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ROBOT_JOINT_ACC, ROBOT_JOINT_SPEED  # noqa: E402
from src.robot import RoArmSession  # noqa: E402

SETTLE_S = 2.0     # tyle czekamy na dojazd osi przed odczytem
STEPS = (10.0, -10.0, 20.0)   # o ile stopni probujemy ruszyc od punktu wyjscia


def send(arm: RoArmSession, angle: float, invert: bool) -> None:
    """Komenda 121 dla osi 4 — z odwróceniem albo bez."""
    payload = json.dumps({"T": 121, "joint": 4,
                          "angle": round(180.0 - angle if invert else angle, 2),
                          "spd": round(ROBOT_JOINT_SPEED * 180 / 2048, 3),
                          "acc": round(ROBOT_JOINT_ACC * 180 / (254 * 100), 4)})
    with arm.arm.lock:
        arm.arm._write((payload + "\n").encode())


def probe(arm: RoArmSession, invert: bool) -> list[tuple[float, float]]:
    label = "180 − kąt (jak SDK)" if invert else "kąt wprost"
    print(f"\n— konwencja: {label}")
    start = arm.read_joints()[3]
    out = []
    for step in STEPS:
        want = start + step
        send(arm, want, invert)
        time.sleep(SETTLE_S)
        got = arm.read_joints()[3]
        miss = abs(got - want)
        mark = "✓" if miss <= 3 else "✗"
        print(f"  {mark} cel {want:7.1f}°  →  odczyt {got:7.1f}°  (różnica {miss:5.1f}°)")
        out.append((want, got))
    send(arm, start, invert)     # wracamy tam, gdzie było
    time.sleep(SETTLE_S)
    return out


def main() -> int:
    arm = RoArmSession()
    arm.log = lambda text: print("  " + text)
    try:
        arm.open()
    except Exception as e:
        print(f"✗ {e}")
        return 1
    print(f"✓ {arm.describe()}")
    print(f"  tryb osi 4: {'nadgarstek' if arm.wrist_mode else 'chwytak'}")
    try:
        joints = arm.read_joints()
        if joints is None:
            print("✗ ramię nie oddaje odczytu kątów — nie ma czego mierzyć")
            return 1
        print(f"  start: {RoArmSession.fmt_joints(joints)}")
        results = {inv: probe(arm, inv) for inv in (False, True)}
        print("\n— wynik")
        for inv, rows in results.items():
            hits = sum(1 for want, got in rows if abs(got - want) <= 3)
            label = "180 − kąt (jak SDK)" if inv else "kąt wprost"
            print(f"  {label}: {hits}/{len(rows)} trafień")
        print("\nTa konwencja z większą liczbą trafień jest prawdziwa — wklej ten wynik,")
        print("poprawię pod nią _send_joints/_send_joint4 w src/robot.py.")
    finally:
        arm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
