"""Fullscreen TUI: sticky header z nazwa sesji i statusami, przewijany log
zdjec pod spodem, menu opcji rozwijane strzalka w dol."""

import contextlib
import io
import os
import select
import sys
import tempfile
import termios
import threading
import time
import tty
from collections import deque
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from .automat_uploader import (AutomatUploader, describe_opened_session,
                               find_existing_session)
from .camera import capture_from_camera
from .config import AUTOMAT_API_TOKEN
from .image_processing import LOGO_POSITIONS, process
from .naming import sanitize_name
from .version import APP_VERSION

__all__ = ["CaptureTUI", "sanitize_name"]


class _KeyReader:
    """Cbreak stdin + dekodowanie sekwencji strzalek."""

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def drain(self) -> None:
        try:
            termios.tcflush(self.fd, termios.TCIFLUSH)
        except (termios.error, ValueError, OSError):
            pass

    def read(self, timeout: float | None = None) -> str | None:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        ch = os.read(self.fd, 1).decode(errors="ignore")
        if ch == "\x1b":
            r, _, _ = select.select([self.fd], [], [], 0.03)
            if not r:
                return "ESC"
            seq = os.read(self.fd, 2).decode(errors="ignore")
            return {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT"}.get(seq, "ESC")
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("\x7f", "\x08"):
            return "BACKSPACE"
        return ch


class _LogWriter(io.TextIOBase):
    """Przechwytuje print()y z camera/process do logu TUI."""

    def __init__(self, tui: "CaptureTUI"):
        self.tui = tui
        self.buf = ""

    def write(self, s: str) -> int:
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.tui.log(Text(line.strip(), style="dim"))
        return len(s)


class CaptureTUI:
    def __init__(
        self,
        logo: Path,
        base_output: Path,
        upload: bool,
        add_logo: bool,
        logo_position: str,
        auto_center: bool,
        auto_zoom: bool,
    ):
        # file= wiaze realny stdout na sztywno — redirect_stdout podczas
        # strzalu (przechwycenie print()ow z camera.py) nie moze porwac
        # renderingu Live.
        self.console = Console(file=sys.stdout)
        self.logo = logo
        self.base_output = base_output
        self.upload_enabled = upload
        self.add_logo = add_logo
        self.logo_position = logo_position
        self.auto_center = auto_center
        self.auto_zoom = auto_zoom
        self.name: str | None = None
        self.count = 0
        self.uploader: AutomatUploader | None = None
        self.log_lines: deque[Text] = deque(maxlen=300)
        self.menu_open = False
        self.menu_idx = 0
        self.pending_attach: dict | None = None   # sesja z Automatu czekajaca na decyzje podlacz/nowa
        self.attach_to: dict | None = None        # {"name", "session"|None} — zapamietana decyzja dla nazwy
        self.status: Spinner | None = None
        self.input_buffer: str | None = ""  # start w trybie wpisywania nazwy
        self.live = None
        self.quit = False

    # ---------- log / uploader ----------

    def log(self, line: Text | str) -> None:
        if isinstance(line, str):
            line = Text(line)
        # Wpis moze byc wielolinijkowy (np. blad aparatu z lista krokow) —
        # deque trzyma pojedyncze linie, zeby docinanie ogona do wysokosci
        # panelu bylo dokladne (inaczej panel przycina najnowsze wpisy).
        parts = line.split("\n") if "\n" in line.plain else [line]
        for part in parts:
            part.no_wrap = True
            part.overflow = "ellipsis"
            self.log_lines.append(part)
        if self.live is not None:
            self.live.update(self._render())

    def _open_uploader(self) -> None:
        self.uploader = None
        self.pending_attach = None
        if not self.upload_enabled or not AUTOMAT_API_TOKEN or not self.name:
            return
        if self.attach_to is not None and self.attach_to["name"] == self.name:
            self._connect_uploader(self.attach_to["session"])
            return
        match = find_existing_session(AutomatUploader(), self.name)
        if match is not None:
            self.pending_attach = match  # decyzja w _handle_attach_key
            return
        self.attach_to = {"name": self.name, "session": None}
        self._connect_uploader(None)

    def _connect_uploader(self, attach: dict | None) -> None:
        try:
            u = AutomatUploader()
            if attach is not None:
                u.attach_session(attach["id"], self.name,
                                 product_found=bool(attach.get("product")),
                                 photos_count=int(attach.get("photos_count", 0)))
            else:
                u.open_session(self.name)
        except Exception as e:
            self.log(Text(f"Nie udalo sie otworzyc sesji w Automacie: {e}", style="red"))
            return
        text, level = describe_opened_session(u, self.name)
        self.log(Text(text, style="bold cyan" if level == "ok" else "yellow"))
        self.uploader = u

    def _announce(self, filename: str) -> int | None:
        if self.uploader is None:
            return None
        try:
            return self.uploader.announce_photo(filename)
        except Exception as e:
            self.log(Text(f"Announce do Automatu nie wyszedl: {e}", style="red"))
            return None

    def _upload(self, out: Path, photo_id: int | None) -> None:
        if self.uploader is None:
            return
        t0 = time.perf_counter()
        try:
            self.uploader.upload_processed(out, photo_id=photo_id)
        except Exception as e:
            self.log(Text(f"Upload do Automatu nie wyszedl: {e}", style="red"))
            return
        self.log(Text(f"↑ Wgrano przetworzone do Automatu ({time.perf_counter() - t0:.1f} s)",
                      style="bold cyan"))

    # ---------- render ----------

    def _state_chips(self) -> Text:
        chips = Text()

        def chip(label: str, on: bool, extra: str = "") -> None:
            if chips:
                chips.append("  ·  ", style="dim")
            chips.append(f"{label}: ", style="dim")
            chips.append("ON" if on else "OFF", style="bold green" if on else "bold red")
            if extra:
                chips.append(f" {extra}", style="dim")

        chip("Upload", self.uploader is not None)
        chip("Logo", self.add_logo, f"({self.logo_position})" if self.add_logo else "")
        chip("Zoom", self.auto_zoom)
        chip("Centrowanie", self.auto_center)
        return chips

    def _header(self) -> Panel:
        body = Text()
        body.append("Sesja: ", style="dim")
        body.append(self.name or "—", style="bold cyan")
        body.append("   Zdjec: ", style="dim")
        body.append(str(self.count), style="bold magenta")
        body.append("   Folder: ", style="dim")
        body.append(str(self.base_output / (self.name or "")), style="yellow")
        body.no_wrap = True
        body.overflow = "ellipsis"
        chips = self._state_chips()
        chips.no_wrap = True
        chips.overflow = "ellipsis"
        hint = Text.assemble(
            ("[ENTER]", "bold green"), (" zdjecie   ", "dim"),
            ("[↓]", "bold green"), (" menu   ", "dim"),
            ("[q]", "bold green"), (" wyjscie", "dim"),
        )
        return Panel(
            Group(body, chips, hint),
            title="[bold]Camera Capture [dim]· Canon EOS M50 II",
            border_style="bright_magenta",
            height=5,
        )

    def _menu_items(self) -> list[tuple[str, Text]]:
        def onoff(v: bool) -> tuple[str, str]:
            return ("ON", "bold green") if v else ("OFF", "bold red")

        return [
            ("name", Text.assemble(("n  ", "bold green"), "Zmien nazwe sesji…")),
            ("upload", Text.assemble(("u  ", "bold green"), "Upload do Automatu: ", onoff(self.uploader is not None))),
            ("logo", Text.assemble(("l  ", "bold green"), "Nakladanie logo: ", onoff(self.add_logo))),
            ("logo_pos", Text.assemble(("p  ", "bold green"), "Pozycja logo: ", (self.logo_position, "bold cyan"))),
            ("zoom", Text.assemble(("z  ", "bold green"), "Przyblizanie (zoom): ", onoff(self.auto_zoom))),
            ("center", Text.assemble(("c  ", "bold green"), "Centrowanie: ", onoff(self.auto_center))),
            ("close", Text.assemble(("ESC  ", "bold green"), "Zamknij menu")),
            ("quit", Text.assemble(("q  ", "bold green"), "Wyjscie")),
        ]

    def _menu_panel(self) -> Panel:
        rows = []
        for i, (_, label) in enumerate(self._menu_items()):
            row = label.copy()
            row.no_wrap = True
            if i == self.menu_idx:
                row = Text.assemble(("❯ ", "bold cyan"), row)
                row.stylize("reverse")
            else:
                row = Text.assemble("  ", row)
            rows.append(row)
        return Panel(
            Group(*rows),
            title="[bold cyan]Menu [dim]↑/↓ wybierz · ENTER zatwierdz · ESC zamknij",
            border_style="cyan",
        )

    def _input_panel(self) -> Panel:
        body = Text.assemble(
            ("Nazwa sesji zdjeciowej: ", "bold cyan"),
            (self.input_buffer or "", "bold white"),
            ("▏", "blink cyan"),
        )
        return Panel(body, border_style="cyan", height=3,
                     title="[dim]ENTER zatwierdz" + (" · ESC anuluj" if self.name else ""))

    def _attach_panel(self) -> Panel:
        m = self.pending_attach
        date = (m.get("created_at") or "")[:10]
        body = Text.assemble(
            ("Sesja ", ""), (str(m.get("name", "")), "bold cyan"),
            (" juz istnieje w Automacie", ""),
            (f" ({date}, zdjec: {m.get('photos_count', 0)}).", "dim"),
        )
        body.no_wrap = True
        body.overflow = "ellipsis"
        hint = Text.assemble(
            ("[ENTER/p]", "bold green"), (" podlacz do istniejacej   ", "dim"),
            ("[n]", "bold green"), (" utworz nowa   ", "dim"),
            ("[ESC]", "bold green"), (" upload OFF", "dim"),
        )
        return Panel(Group(body, hint), border_style="yellow", height=4,
                     title="[bold yellow]Istniejaca sesja w Automacie")

    def _render(self) -> Group:
        total_h = self.console.size.height
        parts: list = [self._header()]
        used = 5
        if self.input_buffer is not None:
            parts.append(self._input_panel())
            used += 3
        elif self.pending_attach is not None:
            parts.append(self._attach_panel())
            used += 4
        elif self.menu_open:
            menu = self._menu_panel()
            parts.append(menu)
            used += len(self._menu_items()) + 2
        status_line = self.status if self.status is not None else Text("")
        parts.append(status_line)
        used += 1
        log_h = max(3, total_h - used)
        visible = list(self.log_lines)[-(log_h - 2):]
        parts.append(Panel(
            Group(*visible) if visible else Text("(brak zdjec w tej sesji)", style="dim"),
            title="[bold]Zdjecia / log",
            border_style="green",
            height=log_h,
        ))
        return Group(*parts)

    # ---------- akcje ----------

    def _shoot(self, keys: _KeyReader) -> None:
        if not self.name:
            return
        self.status = Spinner("dots", text=Text("Lacze z aparatem i wyzwalam migawke…", style="cyan"))
        self.live.update(self._render())
        announced_id = None
        try:
            with contextlib.redirect_stdout(_LogWriter(self)):
                with tempfile.TemporaryDirectory() as td:
                    t0 = time.perf_counter()
                    captured = capture_from_camera(Path(td))
                    cap_s = time.perf_counter() - t0
                    filename = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    announced_id = self._announce(filename)
                    self.status = Spinner("dots", text=Text("Czyszcze tlo / centruje…", style="cyan"))
                    self.live.update(self._render())
                    t0 = time.perf_counter()
                    out = process(
                        captured, self.logo, self.base_output / self.name, clean_bg=True,
                        add_logo=self.add_logo, logo_position=self.logo_position,
                        auto_center=self.auto_center, auto_zoom=self.auto_zoom,
                    )
                    proc_s = time.perf_counter() - t0
        except SystemExit as e:
            self.log(Text(f"Blad aparatu: {e}", style="bold red"))
            return
        finally:
            self.status = None
            keys.drain()  # ENTERy wciskane podczas obrobki nie strzelaja drugi raz
        self.count += 1
        self.log(Text.assemble(
            ("✓ Zapisano ", "bold green"), (str(out), "yellow"), (f"  (#{self.count})", "dim"),
            (f"  aparat {cap_s:.1f} s · obrobka {proc_s:.1f} s", "dim"),
        ))
        self._upload(out, announced_id)

    def _commit_name(self) -> None:
        raw = (self.input_buffer or "").strip()
        if not raw:
            return
        self.name = sanitize_name(raw)
        self.input_buffer = None
        self.count = 0
        self._open_uploader()

    def _toggle_upload(self) -> None:
        self.upload_enabled = not self.upload_enabled
        if self.upload_enabled:
            self._open_uploader()
            if self.uploader is None and not AUTOMAT_API_TOKEN:
                self.log(Text("Upload: brak AUTOMAT_TOKEN w .env — zostaje OFF", style="yellow"))
                self.upload_enabled = False
        else:
            self.uploader = None

    def _cycle_logo_position(self) -> None:
        idx = LOGO_POSITIONS.index(self.logo_position) if self.logo_position in LOGO_POSITIONS else 0
        self.logo_position = LOGO_POSITIONS[(idx + 1) % len(LOGO_POSITIONS)]

    def _run_action(self, action: str) -> None:
        if action == "name":
            self.menu_open = False
            self.input_buffer = self.name or ""
        elif action == "upload":
            self._toggle_upload()
        elif action == "logo":
            self.add_logo = not self.add_logo
        elif action == "logo_pos":
            self._cycle_logo_position()
        elif action == "zoom":
            self.auto_zoom = not self.auto_zoom
        elif action == "center":
            self.auto_center = not self.auto_center
        elif action == "close":
            self.menu_open = False
        elif action == "quit":
            self.quit = True

    # ---------- obsluga klawiszy ----------

    def _handle_input_key(self, k: str) -> None:
        if k == "ENTER":
            self._commit_name()
        elif k == "ESC" and self.name:
            self.input_buffer = None
        elif k == "BACKSPACE":
            self.input_buffer = (self.input_buffer or "")[:-1]
        elif len(k) == 1 and k.isprintable():
            self.input_buffer = (self.input_buffer or "") + k

    def _handle_attach_key(self, k: str) -> None:
        m = self.pending_attach
        if k in ("ENTER", "p"):
            self.pending_attach = None
            self.attach_to = {"name": self.name, "session": m}
            self._connect_uploader(m)
        elif k == "n":
            self.pending_attach = None
            self.attach_to = {"name": self.name, "session": None}
            self._connect_uploader(None)
        elif k == "ESC":
            self.pending_attach = None
            self.upload_enabled = False
            self.log(Text("Upload: OFF (anulowano wybor sesji)", style="yellow"))

    _SHORTCUTS = {"n": "name", "u": "upload", "l": "logo",
                  "p": "logo_pos", "z": "zoom", "c": "center"}

    def _handle_menu_key(self, k: str) -> None:
        items = self._menu_items()
        if k in ("ESC", "h"):
            self.menu_open = False
        elif k == "UP":
            self.menu_idx = (self.menu_idx - 1) % len(items)
        elif k == "DOWN":
            self.menu_idx = (self.menu_idx + 1) % len(items)
        elif k == "ENTER":
            self._run_action(items[self.menu_idx][0])
        elif k == "q":
            self.quit = True
        elif k in self._SHORTCUTS:
            self._run_action(self._SHORTCUTS[k])

    def _handle_main_key(self, k: str, keys: _KeyReader) -> None:
        if k == "ENTER":
            self._shoot(keys)
        elif k in ("DOWN", "h"):
            self.menu_open = True
            self.menu_idx = 0
        elif k == "q":
            self.quit = True
        elif k in self._SHORTCUTS:
            self._run_action(self._SHORTCUTS[k])

    # ---------- petla ----------

    def _check_update_bg(self) -> None:
        """Sprawdzenie nowszego wydania w tle (sekundy sieci — nie blokujemy
        startu). TUI chodzi ze zrodel, wiec tylko informujemy o `git pull`;
        samo-aktualizacja jest w aplikacji okienkowej na Windowsie."""
        try:
            from .updater import check_for_update

            info = check_for_update()
        except Exception:
            return
        if info:
            self.log(Text(
                f"Dostepna nowa wersja {info['version']} (masz {APP_VERSION}) — git pull",
                style="yellow"))

    def _warmup_bg(self) -> None:
        """Rozgrzewka rembg w tle — pierwsza inferencja placi jednorazowe
        koszty (model; na GPU kompilacje pod karte), ktore inaczej obrywaloby
        pierwsze zdjecie."""
        try:
            from .background import gpu_active, warmup_clean_bg

            if gpu_active():  # na CPU nie ma czego kompilowac
                warmup_clean_bg()
        except Exception:
            pass

    def run(self) -> None:
        from rich.live import Live

        threading.Thread(target=self._check_update_bg, daemon=True).start()
        threading.Thread(target=self._warmup_bg, daemon=True).start()
        with _KeyReader() as keys, Live(
            console=self.console, screen=True, auto_refresh=True,
            refresh_per_second=12, transient=True,
        ) as live:
            self.live = live
            live.update(self._render())
            while not self.quit:
                k = keys.read(timeout=0.25)
                if k is None:
                    live.update(self._render())
                    continue
                if self.input_buffer is not None:
                    self._handle_input_key(k)
                elif self.pending_attach is not None:
                    self._handle_attach_key(k)
                elif self.menu_open:
                    self._handle_menu_key(k)
                else:
                    self._handle_main_key(k, keys)
                live.update(self._render())
        self.live = None
        if self.name:
            self.console.print(
                f"[dim]Do zobaczenia. Sesja [/][bold cyan]{self.name}[/]"
                f"[dim]: {self.count} zdjec w [/][yellow]{self.base_output / self.name}[/]"
            )
        else:
            self.console.print("[dim]Do zobaczenia.[/]")
