"""Klient HTTP do Automatu (Rails) — upload przetworzonego JPEG do photo_studio API.

Lokalny pipeline (rembg + biale tlo + watermark) jest robiony przed uploadem,
wiec Automat nie odpala swojego pipeline'u — od razu zapisuje plik jako
processed.

Sesja jest deduplikowana po stronie Rails per produkt + dzień.
"""

from pathlib import Path

import requests

from .config import AUTOMAT_API_TOKEN, AUTOMAT_BASE_URL


class AutomatNotFound(RuntimeError):
    """404 z Automatu — sesja/zdjęcie zniknęło po drugiej stronie (skasowane
    w UI Automatu, wyczyszczona baza). Podklasa RuntimeError, żeby istniejące
    `except Exception` w wołających działały bez zmian."""


def describe_opened_session(uploader: "AutomatUploader", name: str) -> tuple[str, str]:
    """Komunikat do logu po open_session() -> (tekst, poziom 'ok'|'warn')."""
    suffix = (
        f" — podłączono do istniejącej ({uploader.photos_count} zdjęć)"
        if uploader.reattached
        else ""
    )
    base = f"↑ Automat: sesja {uploader.session_id} ({name})"
    if uploader.product_found:
        return f"{base}{suffix}", "ok"
    return f"{base} — produkt nie znaleziony, sesja luźna{suffix}", "warn"


def find_existing_session(uploader: "AutomatUploader", name: str) -> dict | None:
    """Najnowsza sesja photo_studio o tej nazwie (case-insensitive) albo None.
    Blad listy (brak sieci itd.) -> None, flow po prostu otworzy sesje po nazwie."""
    try:
        sessions = uploader.list_sessions()
    except Exception:
        return None
    matches = [s for s in sessions
               if (s.get("name") or "").strip().lower() == name.strip().lower()]
    if not matches:
        return None
    return max(matches, key=lambda s: s.get("created_at") or "")


class AutomatUploader:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout_open: float = 10.0,
        timeout_upload: float = 60.0,
    ):
        token = token or AUTOMAT_API_TOKEN
        if not token:
            raise RuntimeError(
                "AUTOMAT_TOKEN nie ustawiony — uzupelnij .env (patrz .env.example)."
            )
        self.base = (base_url or AUTOMAT_BASE_URL).rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        # keep-alive: przy strzelaniu seriami i sync-u kilkudziesieciu zdjec
        # kazdy announce/upload/download placil wczesniej pelny handshake TCP.
        # Uzywane z jednego watku naraz (worker; okladki maja wlasny uploader).
        self.http = requests.Session()
        self.http.headers.update(self.headers)
        self.timeout_open = timeout_open
        self.timeout_upload = timeout_upload
        self.session_id: int | None = None
        self.product_name: str | None = None
        self.product_found: bool = True
        self.reattached: bool = False
        self.photos_count: int = 0

    @staticmethod
    def _strip_body(r) -> str:
        text = (r.text or "").lstrip()
        low = text[:20].lower()
        if low.startswith("<!doctype") or low.startswith("<html"):
            return "<HTML z Rails dev mode — sprawdz log/development.log>"
        return text.strip().replace("\n", " ")[:400] or "<empty>"

    def _err(self, kind: str, r) -> RuntimeError:
        # 404 dostaje wlasna klase (nadal RuntimeError, wiec stare `except`
        # lapia jak dotad) — wolajacy musi umiec odroznic "znikneło po drugiej
        # stronie" od zwyklego bledu HTTP, np. zeby sprzatnac lokalna sesje.
        cls = AutomatNotFound if r.status_code == 404 else RuntimeError
        return cls(f"Automat {kind} {r.status_code} {r.reason} — {self._strip_body(r)}")

    def list_sessions(self) -> list[dict]:
        """GET wszystkich sesji photo_studio: [{id, name, product, created_at,
        photos_count}, ...] — dla ekranu startowego aplikacji."""
        r = self.http.get(
            f"{self.base}/api/photo_studio/sessions",
            timeout=self.timeout_open,
        )
        if not r.ok:
            raise self._err("lista sesji", r)
        return r.json()

    def session_photos(self, session_id: int | None = None) -> list[dict]:
        """Zdjecia sesji z Automatu: [{id, status, filename, processed}, ...] —
        zrodlo prawdy przy otwarciu sesji na maszynie bez jej lokalnych plikow."""
        sid = session_id if session_id is not None else self.session_id
        if sid is None:
            raise RuntimeError("open_session()/attach_session() musi byc zawolane wczesniej.")
        r = self.http.get(
            f"{self.base}/api/photo_studio/sessions/{sid}",
            timeout=self.timeout_open,
        )
        if not r.ok:
            raise self._err("zdjecia sesji", r)
        return r.json().get("photos") or []

    def download_photo(self, photo_id: int, dest: Path, session_id: int | None = None) -> Path:
        """Pobiera przetworzony JPEG do `dest`. Zapis idzie do `.part` i dopiero
        rename — przerwane pobieranie nie zostawi obcietego pliku, ktory
        filmstrip pokazalby jako zdjecie sesji."""
        sid = session_id if session_id is not None else self.session_id
        if sid is None:
            raise RuntimeError("open_session()/attach_session() musi byc zawolane wczesniej.")
        r = self.http.get(
            f"{self.base}/api/photo_studio/sessions/{sid}/photos/{photo_id}/file",
            timeout=self.timeout_upload,
            stream=True,
        )
        if not r.ok:
            raise self._err("pobranie zdjecia", r)
        tmp = dest.with_name(dest.name + ".part")
        try:
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(64 * 1024):
                    fh.write(chunk)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        return dest

    def open_session(self, product_name: str) -> int:
        r = self.http.post(
            f"{self.base}/api/photo_studio/sessions",
            data={"product_name": product_name},
            timeout=self.timeout_open,
        )
        if not r.ok:
            raise self._err("sesja", r)
        payload = r.json()
        self.session_id = int(payload["id"])
        self.product_name = product_name
        self.product_found = bool(payload.get("product_found", True))
        self.reattached = bool(payload.get("reattached", False))
        self.photos_count = int(payload.get("photos_count", 0))
        return self.session_id

    def attach_session(
        self,
        session_id: int,
        product_name: str,
        product_found: bool = True,
        photos_count: int = 0,
    ) -> int:
        """Podłącza się do istniejącej sesji po id, bez POST-a (announce/upload
        idą na /sessions/:id/photos). Jeśli sesja zniknęła po stronie Rails,
        pierwszy 404 przejdzie przez _reopen() i otworzy nową po nazwie."""
        self.session_id = int(session_id)
        self.product_name = product_name
        self.product_found = product_found
        self.reattached = True
        self.photos_count = photos_count
        return self.session_id

    def _reopen(self) -> None:
        if not self.product_name:
            raise RuntimeError("Sesja zniknela, ale brak product_name do odtworzenia.")
        self.open_session(self.product_name)

    def _post_announce(self, filename: str):
        return self.http.post(
            f"{self.base}/api/photo_studio/sessions/{self.session_id}/photos",
            data={"filename": filename},
            timeout=self.timeout_open,
        )

    def announce_photo(self, filename: str) -> int:
        """Rejestruje placeholder (nazwa, status=uploading) zanim plik
        bedzie gotowy. Browser pokazuje od razu kafelek ze spinnerem.
        Przy 404 odtwarza sesje i ponawia raz."""
        if self.session_id is None:
            raise RuntimeError("open_session() musi byc zawolane wczesniej.")
        r = self._post_announce(filename)
        if r.status_code == 404:
            self._reopen()
            r = self._post_announce(filename)
        if not r.ok:
            raise self._err("announce", r)
        return int(r.json()["id"])

    def _do_upload(self, processed_path: Path, photo_id: int | None):
        with open(processed_path, "rb") as fh:
            files = {"file": (processed_path.name, fh, "image/jpeg")}
            if photo_id is not None:
                return self.http.put(
                    f"{self.base}/api/photo_studio/sessions/{self.session_id}/photos/{photo_id}",
                    files=files,
                    timeout=self.timeout_upload,
                )
            return self.http.post(
                f"{self.base}/api/photo_studio/sessions/{self.session_id}/photos",
                files=files,
                timeout=self.timeout_upload,
            )

    def delete_photo(self, photo_id: int) -> None:
        """DELETE zdjecia z sesji — operator skasowal je w aplikacji.
        404 (zdjecie/sesja juz nie istnieje) traktowane jako sukces."""
        if self.session_id is None:
            raise RuntimeError("open_session() musi byc zawolane wczesniej.")
        r = self.http.delete(
            f"{self.base}/api/photo_studio/sessions/{self.session_id}/photos/{photo_id}",
            timeout=self.timeout_open,
        )
        if r.status_code == 404:
            return
        if not r.ok:
            raise self._err("delete", r)

    def upload_processed(self, processed_path: Path, photo_id: int | None = None) -> dict:
        """Upload przetworzonego JPEG. Jesli `photo_id` podany — atachuje do
        istniejacego placeholdera (PUT). W innym razie tworzy nowy rekord (POST).
        Przy 404 odtwarza sesje i ponawia jako POST bez photo_id (stary id jest martwy)."""
        if self.session_id is None:
            raise RuntimeError("open_session() musi byc zawolane wczesniej.")
        r = self._do_upload(processed_path, photo_id)
        if r.status_code == 404:
            self._reopen()
            r = self._do_upload(processed_path, photo_id=None)
        if not r.ok:
            raise self._err("upload", r)
        return r.json()
