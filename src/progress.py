"""Postęp zdjęcia od migawki do gotowego pliku — kafelek w pasku zdjęć.

Każde zdjęcie przechodzi stałą listę etapów (STAGES, w tej kolejności). Front
dostaje listę etapów z SZACOWANYM czasem każdego, numer bieżącego i ile już
trwa, i sam liczy procent co klatkę — pasek rośnie płynnie między pollami
stanu, zamiast skakać co 500 ms.

Szacunki uczą się na TYM komputerze (średnia krocząca, plik obok .exe jak
.env, więc przeżywa aktualizacje): na laptopie bez GPU wycinanie produktu
trwa kilka razy dłużej niż na stacji operatora, a stałe wagi dawałyby pasek,
który stoi na 90% albo przeskakuje od 30% do końca.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable

# etap -> domyślny czas (s), zanim komputer zmierzy własny; 0 = nie wlicza się
# do procentu (kolejka bywa pusta albo trwa minutę rozgrzewki — nie da się jej
# przewidzieć, więc pasek wtedy stoi, a napis mówi, na co czeka)
STAGES: dict[str, float] = {
    "camera": 2.0,     # migawka + JPEG po USB
    "queue": 0.0,      # czeka na wątek obróbki (poprzednie zdjęcie, rozgrzewka)
    "announce": 0.4,   # zapowiedź zdjęcia na serwerze
    "rembg": 1.5,      # wycinanie produktu (model)
    "mask": 0.6,       # maska i cienie
    "crop": 0.2,       # kadrowanie
    "compose": 0.5,    # białe tło
    "logo": 0.2,
    "save": 0.5,       # zapis JPEG
}
EMA = 0.3   # waga nowego pomiaru w średniej kroczącej


def stages_for(clean_bg: bool, add_logo: bool, upload: bool) -> list[str]:
    """Etapy jednego zdjęcia przy danych ustawieniach (kolejność jak w obróbce)."""
    out = ["camera", "queue"]
    if upload:
        out.append("announce")
    out += ["rembg", "mask", "crop", "compose"] if clean_bg else ["crop"]
    if add_logo:
        out.append("logo")
    out.append("save")
    return out


class PhotoProgress:
    def __init__(self, store: Callable[[], Path]) -> None:
        # ścieżka jako funkcja: testy podmieniają katalog po utworzeniu WebUI
        self._store = store
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._est: dict[str, float] | None = None

    # ---- szacunki

    def _estimates(self) -> dict[str, float]:
        if self._est is None:
            est = dict(STAGES)
            try:
                saved = json.loads(self._store().read_text(encoding="utf-8"))
                est.update({k: float(v) for k, v in saved.items()
                            if k in STAGES and STAGES[k] > 0 and float(v) > 0})
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            self._est = est
        return self._est

    def _learn(self, key: str, seconds: float) -> None:
        if STAGES.get(key, 0) <= 0 or seconds <= 0:
            return
        est = self._estimates()
        est[key] = round(est[key] * (1 - EMA) + seconds * EMA, 3)

    def _save(self) -> None:
        est = {k: v for k, v in self._estimates().items() if STAGES[k] > 0}
        path = self._store()
        tmp = path.with_name(path.name + ".part")
        try:
            tmp.write_text(json.dumps(est), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass  # katalog tylko do odczytu — szacunki zostają domyślne

    # ---- zdjęcie

    def start(self, file: str, stages: list[str]) -> None:
        with self._lock:
            self._jobs[file] = {"stages": list(stages), "index": 0,
                                "since": time.monotonic()}

    def stage(self, file: str, key: str) -> None:
        """Początek etapu `key` (koniec poprzedniego). Etapy pominięte po
        drodze liczą się jako zrobione; nieznany albo wsteczny — bez zmian."""
        with self._lock:
            job = self._jobs.get(file)
            if job is None or key not in job["stages"]:
                return
            new = job["stages"].index(key)
            if new <= job["index"]:
                return
            now = time.monotonic()
            self._learn(job["stages"][job["index"]], now - job["since"])
            job["index"], job["since"] = new, now

    def finish(self, file: str, ok: bool = True) -> None:
        with self._lock:
            job = self._jobs.pop(file, None)
            if job is None:
                return
            if ok:
                self._learn(job["stages"][job["index"]], time.monotonic() - job["since"])
                self._save()

    def snapshot(self) -> list[dict]:
        """Dla /api/state: zdjęcia w kolejności zrobienia."""
        now = time.monotonic()
        with self._lock:
            est = self._estimates()
            return [{
                "file": file,
                "stages": [[k, est.get(k, 0.0)] for k in job["stages"]],
                "index": job["index"],
                "agoMs": int((now - job["since"]) * 1000),
            } for file, job in self._jobs.items()]
