"""Aplikacja okienkowa (Tkinter): live preview z aparatu po lewej, panel
sterowania po prawej, log na dole. Pipeline strzalu identyczny jak w TUI:
capture -> announce -> clean bg/centrowanie -> zapis raw+final -> upload.

Watki:
- UI (glowny): Tkinter mainloop + tick 30 ms (rendering klatek, kolejka zdarzen).
- camera: JEDYNY wlasciciel gphoto2 (preview loop + wyzwalanie migawki).
- worker: obrobka (rembg), uploader Automatu — strzaly kolejkuja sie,
  preview nie zamiera podczas obrobki.
"""

import io
import queue
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

import gphoto2 as gp
from PIL import Image, ImageOps, ImageTk

from .automat_uploader import AutomatUploader
from .camera import CameraSession
from .config import AUTOMAT_API_TOKEN
from .image_processing import LOGO_POSITIONS, process
from .tui import sanitize_name

_TICK_MS = 30
_THUMB_SIZE = 240


class _StdoutToUi(io.TextIOBase):
    """print()y z camera.py/process() -> log w oknie (linia po linii)."""

    def __init__(self, put):
        self.put = put
        self.buf = ""

    def write(self, s: str) -> int:
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.put(line.strip())
        return len(s)


class CaptureGUI:
    def __init__(
        self,
        logo: Path,
        base_output: Path,
        upload: bool,
        add_logo: bool,
        logo_position: str,
        auto_center: bool,
        auto_zoom: bool,
        name: str | None = None,
    ):
        self.logo = logo
        self.base_output = base_output
        self.name: str | None = sanitize_name(name) if name else None
        self.count = 0
        self.uploader: AutomatUploader | None = None  # tylko watek worker

        self.session = CameraSession()
        self._cam_ok = False
        self._preview_enabled = True
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._frame: bytes | None = None
        self._frames_shown = 0
        self._fps_t0 = time.monotonic()
        self._cam_q: queue.Queue[tuple] = queue.Queue()  # komendy do watku aparatu
        self._jobs: queue.Queue = queue.Queue()
        self._ui_q: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Camera Capture — Canon EOS M50 II")
        self.root.geometry("1180x800")
        self.root.minsize(900, 620)

        self.upload_var = tk.BooleanVar(value=upload)
        self.logo_var = tk.BooleanVar(value=add_logo)
        self.logo_pos_var = tk.StringVar(value=logo_position)
        self.zoom_var = tk.BooleanVar(value=auto_zoom)
        self.center_var = tk.BooleanVar(value=auto_center)
        self.name_var = tk.StringVar(value=self.name or "")

        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- layout ----------

    def _build_widgets(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.preview_label = tk.Label(self.root, bg="black", anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        side = ttk.Frame(self.root, padding=12)
        side.grid(row=0, column=1, sticky="ns")

        ttk.Label(side, text="Nazwa sesji zdjęciowej").pack(anchor="w")
        row = ttk.Frame(side)
        row.pack(fill="x", pady=(2, 8))
        self.name_entry = ttk.Entry(row, textvariable=self.name_var, width=20)
        self.name_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Ustaw", command=self._commit_name).pack(side="left", padx=(6, 0))

        self.session_label = ttk.Label(side, text="", foreground="gray")
        self.session_label.pack(anchor="w", pady=(0, 10))

        ttk.Checkbutton(
            side, text="Upload do Automatu", variable=self.upload_var,
            command=self._on_upload_toggle,
        ).pack(anchor="w")
        ttk.Checkbutton(side, text="Nakładanie logo", variable=self.logo_var).pack(anchor="w")
        row = ttk.Frame(side)
        row.pack(fill="x", pady=(2, 0))
        ttk.Label(row, text="Pozycja logo:").pack(side="left")
        ttk.Combobox(
            row, textvariable=self.logo_pos_var, values=list(LOGO_POSITIONS),
            state="readonly", width=13,
        ).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(side, text="Przybliżanie (zoom)", variable=self.zoom_var).pack(anchor="w", pady=(2, 0))
        ttk.Checkbutton(side, text="Centrowanie", variable=self.center_var).pack(anchor="w")

        ttk.Label(side, text="Kontrast (w aparacie):").pack(anchor="w", pady=(8, 0))
        self.contrast_row = ttk.Frame(side)
        self.contrast_row.pack(fill="x")
        ttk.Label(self.contrast_row, text="— sprawdzam…", foreground="gray").pack(anchor="w")

        self.shoot_btn = ttk.Button(
            side, text="📷  Zdjęcie  (Spacja)", command=self._request_shoot,
        )
        self.shoot_btn.pack(fill="x", ipady=10, pady=(16, 4))
        self.preview_btn = ttk.Button(
            side, text="Podgląd: ON", command=self._toggle_preview,
        )
        self.preview_btn.pack(fill="x")

        ttk.Label(side, text="Ostatnie zdjęcie (klik = pełny ekran):").pack(anchor="w", pady=(14, 2))
        self.thumb_label = tk.Label(side, bg="#222", cursor="pointinghand")
        self.thumb_label.pack()
        self.thumb_label.configure(width=32, height=12)
        self.thumb_label.bind("<Button-1>", self._open_fullscreen)

        self.status_label = ttk.Label(self.root, text="Łączę z aparatem…", padding=(8, 4))
        self.status_label.grid(row=1, column=0, columnspan=2, sticky="ew")

        self.log_text = tk.Text(
            self.root, height=8, state="disabled", bg="#161616", fg="#ddd",
            font=("Menlo", 11), relief="flat",
        )
        self.log_text.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.root.bind("<space>", self._on_space)
        self.root.bind("<Return>", self._on_return)
        self.root.bind("<Key-q>", self._on_q)

    # ---------- kolejka UI (wolana z dowolnego watku) ----------

    def _ui(self, msg: tuple) -> None:
        self._ui_q.put(msg)

    def _log(self, line: str) -> None:
        self._ui(("log", line))

    # ---------- watek aparatu ----------

    def _camera_loop(self) -> None:
        try:
            self.session.open()
        except Exception as e:
            self._ui(("cam", False))
            self._log(f"✗ {e}")
            return
        self._ui(("cam", True))
        self._log("Aparat połączony — live view aktywny.")
        try:
            self._ui(("contrast_info", self.session.describe_contrast()))
        except gp.GPhoto2Error as e:
            self._ui(("contrast_info", None))
            self._log(f"Nie udało się odczytać kontrastu: {e}")
        try:
            while not self._stop.is_set():
                try:
                    cmd, payload = self._cam_q.get_nowait()
                except queue.Empty:
                    cmd = None
                if cmd == "shoot":
                    self._do_capture(payload)
                    continue
                if cmd == "contrast":
                    try:
                        self.session.set_contrast(payload)
                        self._log(f"Kontrast aparatu: {payload}")
                    except Exception as e:
                        self._log(f"✗ Nie udało się ustawić kontrastu: {e}")
                    continue
                if self._preview_enabled:
                    try:
                        data = self.session.preview_frame()
                    except gp.GPhoto2Error as e:
                        self._log(f"✗ Podgląd przerwany: {e}")
                        self._ui(("cam", False))
                        return
                    with self._frame_lock:
                        self._frame = data
                else:
                    time.sleep(0.1)
        finally:
            self.session.close()

    def _do_capture(self, opts: dict) -> None:
        self._ui(("status", "Wyzwalam migawkę…"))
        tmpdir = Path(tempfile.mkdtemp(prefix="capture_"))
        try:
            captured = self.session.capture_to(tmpdir)
        except (SystemExit, gp.GPhoto2Error) as e:
            self._log(f"✗ Błąd aparatu: {e}")
            self._ui(("status", ""))
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._ui(("status", ""))
        self._jobs.put(("photo", {**opts, "tmpdir": tmpdir, "captured": captured}))

    # ---------- watek worker (obrobka + Automat) ----------

    def _worker_loop(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            kind, payload = item
            if kind == "session":
                self._open_uploader(payload)
            elif kind == "upload_off":
                self.uploader = None
            elif kind == "photo":
                self._process_job(payload)

    def _open_uploader(self, name: str) -> None:
        self.uploader = None
        try:
            u = AutomatUploader()
            u.open_session(name)
        except Exception as e:
            self._log(f"✗ Nie udało się otworzyć sesji w Automacie: {e}")
            return
        suffix = f" — podłączono do istniejącej ({u.photos_count} zdjęć)" if u.reattached else ""
        if u.product_found:
            self._log(f"↑ Automat: sesja {u.session_id} ({name}){suffix}")
        else:
            self._log(f"↑ Automat: sesja {u.session_id} ({name}) — produkt nie znaleziony, sesja luźna{suffix}")
        self.uploader = u

    def _process_job(self, job: dict) -> None:
        filename = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        announced_id = None
        if self.uploader is not None:
            try:
                announced_id = self.uploader.announce_photo(filename)
            except Exception as e:
                self._log(f"✗ Announce do Automatu nie wyszedł: {e}")
        self._ui(("status", "Czyszczę tło / centruję…"))
        try:
            out = process(
                job["captured"], self.logo, job["outdir"], clean_bg=True,
                add_logo=job["add_logo"], logo_position=job["logo_position"],
                auto_center=job["auto_center"], auto_zoom=job["auto_zoom"],
            )
        except Exception as e:
            self._log(f"✗ Obróbka nie wyszła: {e}")
            return
        finally:
            self._ui(("status", ""))
            shutil.rmtree(job["tmpdir"], ignore_errors=True)
        self._ui(("shot", str(out)))
        if self.uploader is not None:
            try:
                self.uploader.upload_processed(out, photo_id=announced_id)
                self._log("↑ Wgrano przetworzone do Automatu")
            except Exception as e:
                self._log(f"✗ Upload do Automatu nie wyszedł: {e}")

    # ---------- akcje UI ----------

    def _commit_name(self) -> None:
        raw = self.name_var.get().strip()
        if not raw:
            return
        self.name = sanitize_name(raw)
        self.name_var.set(self.name)
        self.count = 0
        self._refresh_session_label()
        self._log(f"Sesja: {self.name} → {self.base_output / self.name}")
        if self.upload_var.get() and AUTOMAT_API_TOKEN:
            self._jobs.put(("session", self.name))
        self.preview_label.focus_set()

    def _on_upload_toggle(self) -> None:
        if self.upload_var.get():
            if not AUTOMAT_API_TOKEN:
                self._log("Brak AUTOMAT_TOKEN w .env — upload zostaje OFF")
                self.upload_var.set(False)
                return
            if self.name:
                self._jobs.put(("session", self.name))
        else:
            self._jobs.put(("upload_off", None))

    def _request_shoot(self) -> None:
        if not self._cam_ok:
            self._log("Aparat nie jest połączony.")
            return
        if not self.name:
            self._log("Najpierw ustaw nazwę sesji.")
            self.name_entry.focus_set()
            return
        self._cam_q.put(("shoot", {
            "outdir": self.base_output / self.name,
            "add_logo": self.logo_var.get(),
            "logo_position": self.logo_pos_var.get(),
            "auto_center": self.center_var.get(),
            "auto_zoom": self.zoom_var.get(),
        }))

    def _build_contrast_control(self, info: dict | None) -> None:
        for w in self.contrast_row.winfo_children():
            w.destroy()
        if not info:
            ttk.Label(
                self.contrast_row,
                text="niedostępny przez USB (ustaw w Picture Style aparatu)",
                foreground="gray",
            ).pack(anchor="w")
            return
        if info["kind"] == "range":
            self.contrast_var = tk.DoubleVar(value=float(info["current"]))
            value_label = ttk.Label(self.contrast_row, text=f"{float(info['current']):.0f}", width=4)
            scale = ttk.Scale(
                self.contrast_row, from_=info["min"], to=info["max"],
                variable=self.contrast_var,
                command=lambda _v: value_label.configure(text=f"{self.contrast_var.get():.0f}"),
            )
            scale.pack(side="left", fill="x", expand=True)
            scale.bind("<ButtonRelease-1>", lambda _e: self._send_contrast(round(self.contrast_var.get())))
            value_label.pack(side="left", padx=(6, 0))
        else:
            self.contrast_var = tk.StringVar(value=str(info["current"]))
            box = ttk.Combobox(
                self.contrast_row, textvariable=self.contrast_var,
                values=[str(c) for c in info["choices"]], state="readonly", width=10,
            )
            box.pack(anchor="w")
            box.bind("<<ComboboxSelected>>", lambda _e: self._send_contrast(self.contrast_var.get()))

    def _send_contrast(self, value) -> None:
        self._cam_q.put(("contrast", value))

    def _toggle_preview(self) -> None:
        self._preview_enabled = not self._preview_enabled
        self.preview_btn.configure(
            text="Podgląd: ON" if self._preview_enabled else "Podgląd: OFF"
        )
        if not self._preview_enabled:
            self.preview_label.configure(image="")
            self.preview_label.image = None

    def _entry_focused(self) -> bool:
        return self.root.focus_get() is self.name_entry

    def _on_space(self, _e) -> str | None:
        if self._entry_focused():
            return None
        self._request_shoot()
        return "break"

    def _on_return(self, _e) -> str | None:
        if self._entry_focused():
            self._commit_name()
        else:
            self._request_shoot()
        return "break"

    def _on_q(self, _e) -> str | None:
        if self._entry_focused():
            return None
        self._on_close()
        return "break"

    # ---------- tick UI ----------

    def _refresh_session_label(self) -> None:
        if self.name:
            self.session_label.configure(
                text=f"{self.base_output / self.name}  ·  zdjęć: {self.count}"
            )
        else:
            self.session_label.configure(text="(bez nazwy nie da się strzelić)")

    def _render_frame(self) -> None:
        with self._frame_lock:
            data, self._frame = self._frame, None
        if data is None:
            return
        w = self.preview_label.winfo_width()
        h = self.preview_label.winfo_height()
        if w < 20 or h < 20:
            return
        img = Image.open(io.BytesIO(data))
        img = ImageOps.contain(img, (w, h))
        photo = ImageTk.PhotoImage(img)
        self.preview_label.configure(image=photo)
        self.preview_label.image = photo
        self._frames_shown += 1

    def _set_thumbnail(self, path: str) -> None:
        try:
            img = Image.open(path)
            img.thumbnail((_THUMB_SIZE, _THUMB_SIZE))
            photo = ImageTk.PhotoImage(img)
            self.thumb_label.configure(image=photo, width=img.width, height=img.height)
            self.thumb_label.image = photo
            self._last_photo = path
        except Exception:
            pass

    def _open_fullscreen(self, _e=None) -> None:
        path = getattr(self, "_last_photo", None)
        if not path:
            return
        top = tk.Toplevel(self.root)
        top.attributes("-fullscreen", True)
        top.configure(bg="black")
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        try:
            img = ImageOps.contain(Image.open(path), (sw, sh))
        except Exception as e:
            top.destroy()
            self._log(f"✗ Nie mogę otworzyć {path}: {e}")
            return
        photo = ImageTk.PhotoImage(img)
        lbl = tk.Label(top, image=photo, bg="black", cursor="pointinghand")
        lbl.image = photo
        lbl.pack(expand=True, fill="both")
        for seq in ("<Escape>", "<Key-q>", "<space>", "<Button-1>"):
            top.bind(seq, lambda _e: top.destroy())
        top.focus_set()

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                kind, *rest = self._ui_q.get_nowait()
            except queue.Empty:
                return
            if kind == "log":
                self.log_text.configure(state="normal")
                self.log_text.insert("end", rest[0] + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            elif kind == "cam":
                self._cam_ok = rest[0]
                if not self._cam_ok:
                    self.status_label.configure(text="Aparat rozłączony.")
            elif kind == "status":
                self._busy_status = rest[0]
            elif kind == "contrast_info":
                self._build_contrast_control(rest[0])
            elif kind == "shot":
                self.count += 1
                self._refresh_session_label()
                self._log(f"✓ Zapisano {rest[0]}  (#{self.count})")
                self._set_thumbnail(rest[0])

    def _tick(self) -> None:
        self._drain_ui_queue()
        self._render_frame()
        now = time.monotonic()
        if now - self._fps_t0 >= 1.0:
            fps = self._frames_shown / (now - self._fps_t0)
            self._frames_shown = 0
            self._fps_t0 = now
            if self._cam_ok:
                busy = getattr(self, "_busy_status", "")
                base = busy or (
                    f"Aparat: połączony · podgląd {fps:.0f} fps"
                    if self._preview_enabled else "Aparat: połączony · podgląd wyłączony"
                )
                self.status_label.configure(text=base)
        self.root.after(_TICK_MS, self._tick)

    # ---------- lifecycle ----------

    def _on_close(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        if self._camera_thread.is_alive():
            self._camera_thread.join(timeout=3.0)
        self.root.destroy()

    def run(self) -> None:
        sys.stdout = _StdoutToUi(self._log)
        try:
            self._camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._camera_thread.start()
            self._worker_thread.start()
            self._refresh_session_label()
            if not self.name:
                self.name_entry.focus_set()
            self.root.after(_TICK_MS, self._tick)
            self.root.mainloop()
        finally:
            sys.stdout = sys.__stdout__
