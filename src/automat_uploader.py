"""Klient HTTP do Automatu (Rails) — upload przetworzonego JPEG do photo_studio API.

Lokalny pipeline (rembg + biale tlo + watermark) jest robiony przed uploadem,
wiec Automat nie odpala swojego pipeline'u — od razu zapisuje plik jako
processed.

Sesja jest deduplikowana po stronie Rails per produkt + dzień.
"""

from pathlib import Path

import requests

from .config import AUTOMAT_API_TOKEN, AUTOMAT_BASE_URL


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
        return RuntimeError(f"Automat {kind} {r.status_code} {r.reason} — {self._strip_body(r)}")

    def open_session(self, product_name: str) -> int:
        r = requests.post(
            f"{self.base}/api/photo_studio/sessions",
            headers=self.headers,
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

    def _reopen(self) -> None:
        if not self.product_name:
            raise RuntimeError("Sesja zniknela, ale brak product_name do odtworzenia.")
        self.open_session(self.product_name)

    def _post_announce(self, filename: str):
        return requests.post(
            f"{self.base}/api/photo_studio/sessions/{self.session_id}/photos",
            headers=self.headers,
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
                return requests.put(
                    f"{self.base}/api/photo_studio/sessions/{self.session_id}/photos/{photo_id}",
                    headers=self.headers,
                    files=files,
                    timeout=self.timeout_upload,
                )
            return requests.post(
                f"{self.base}/api/photo_studio/sessions/{self.session_id}/photos",
                headers=self.headers,
                files=files,
                timeout=self.timeout_upload,
            )

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
