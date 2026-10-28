"""Aktualizacja z GitHub Releases: src/updater.py i przepływ w aplikacji.

Bez sieci i bez prawdziwego .exe: GitHub to atrapa `requests.get`, paczka to
zip zbudowany w teście, a instalacja to katalog tmp z udawanym .exe,
`_internal/`, `.env`, `photos/` i `EDSDK.dll`. Windows: pobranie, rozpakowanie,
start aktualizatora z paczki, podmiana plików i powrót do starej wersji przy
błędzie. macOS: spakowana `.app` nie podmienia się sama, tylko prowadzi do
paczki macOS z wydania. Testy z `win32` w nazwie ruszają tylko na Windowsie
(CI), bo sprawdzają rzeczy, których nie da się podrobić gdzie indziej.
"""

import io
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, expect

from conftest import ROOT, log_texts, wait_for

EXE = "Trixbrix - Camera Capture.exe"
VERSION = "9.9.9"


def release_json(repo: str, kind: str = "windows", version: str = VERSION,
                 asset_id: int = 1, **extra) -> dict:
    """Jedno wydanie z listy GitHuba (/releases): osobne na system, tag
    `vX.Y.Z-<system>`, w środku jedna paczka tego systemu."""
    tag = f"v{version}-{kind}"
    return {
        "tag_name": tag,
        "published_at": "2026-10-28T07:00:00Z",
        "body": f"Co nowego ({kind})\n",
        "html_url": f"https://github.com/{repo}/releases/tag/{tag}",
        "draft": False,
        "prerelease": False,
        "assets": [{
            "name": f"CameraCapture-{kind}-v{version}.zip",
            "url": f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}",
            "browser_download_url":
                f"https://github.com/{repo}/releases/download/{tag}/CameraCapture-{kind}-v{version}.zip",
            "size": 1000 + asset_id,
        }],
        **extra,
    }


def releases(repo: str) -> list[dict]:
    """Repo po wydaniu 9.9.9: Windows i macOS osobno, starsze niżej, a na
    końcu dawne wspólne wydanie z obiema paczkami."""
    combined = release_json(repo, "windows", "2.4.11", 9)
    combined["tag_name"] = "v2.4.11"
    combined["assets"] += release_json(repo, "macos", "2.4.11", 10)["assets"]
    return [
        release_json(repo, "macos", VERSION, 2),
        release_json(repo, "windows", VERSION, 1),
        release_json(repo, "windows", "9.9.8", 3),
        release_json(repo, "macos", "9.9.8", 4),
        combined,
    ]


def package_zip(files: dict[str, str]) -> bytes:
    """Zip paczki: ścieżka w archiwum -> treść."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


NEW_PACKAGE = {
    EXE: "nowy exe",
    "_internal/python311.dll": "nowa biblioteka",
    "_internal/src/webui_static/index.html": "<html>nowa</html>",
}


class FakeResponse:
    def __init__(self, status=200, json_data=None, body=b"", chunk=4096):
        self.status_code = status
        self._json = json_data
        self._body = body
        self._chunk = chunk
        self.headers = {"Content-Length": str(len(body))} if body else {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} z GitHuba")

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), self._chunk):
            yield self._body[i:i + self._chunk]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def upd(tmp_path, monkeypatch):
    """updater z instalacją w tmp/install i katalogiem tymczasowym w tmp/temp
    (sprzątanie globuje %TEMP%/cc_update_* — nie może ruszać prawdziwego)."""
    from src import updater

    install = tmp_path / "install"
    install.mkdir()
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updater, "PROJECT_DIR", install)
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    monkeypatch.setattr(updater, "UPDATE_TOKEN", "")
    updater.install_dir = install
    updater.temp_dir = temp
    return updater


def fake_get(monkeypatch, responses: list, calls: list | None = None):
    """`requests.get` oddaje kolejne odpowiedzi z listy i zapisuje wywołania."""
    def get(url, **kw):
        if calls is not None:
            calls.append((url, kw))
        return responses.pop(0)
    monkeypatch.setattr(requests, "get", get)


# ---------- sprawdzenie wydania ----------

def test_each_system_takes_its_own_release(upd, monkeypatch):
    calls = []
    fake_get(monkeypatch, [FakeResponse(json_data=releases(upd.GITHUB_REPO))] * 2, calls)
    win = upd.latest_release("windows")
    assert calls[0][0] == upd.RELEASES_API and calls[0][1]["params"] == {"per_page": 30}
    assert win["version"] == VERSION and win["tag"] == f"v{VERSION}-windows"
    # Windows pobiera przez API (działa też z tokenem dla prywatnego repo)
    assert win["url"] == f"https://api.github.com/repos/{upd.GITHUB_REPO}/releases/assets/1"
    assert win["size"] == 1001
    assert win["notes"] == "Co nowego (windows)"
    assert win["page"].endswith(f"/releases/tag/v{VERSION}-windows")
    mac = upd.latest_release("macos")
    assert mac["tag"] == f"v{VERSION}-macos"
    # macOS: zwykły link do paczki dla przeglądarki
    assert mac["download"] == (f"https://github.com/{upd.GITHUB_REPO}/releases/download/"
                               f"v{VERSION}-macos/CameraCapture-macos-v{VERSION}.zip")


def test_newest_version_wins_whatever_the_list_order(upd, monkeypatch):
    repo = upd.GITHUB_REPO
    listed = [release_json(repo, "windows", "9.9.8", 1), release_json(repo, "windows", "9.10.0", 2),
              release_json(repo, "macos", "9.11.0", 3)]
    fake_get(monkeypatch, [FakeResponse(json_data=listed)])
    assert upd.latest_release("windows")["version"] == "9.10.0"


def test_without_the_new_split_old_combined_release_still_works(upd, monkeypatch):
    """Zanim wyjdzie pierwsze osobne wydanie, w repo jest tylko wspólne."""
    fake_get(monkeypatch, [FakeResponse(json_data=releases(upd.GITHUB_REPO)[-1:])] * 2)
    assert upd.latest_release("windows")["url"].endswith("/assets/9")
    assert upd.latest_release("macos")["download"].endswith("CameraCapture-macos-v2.4.11.zip")


def test_system_decides_which_package_to_look_for(upd, monkeypatch):
    fake_get(monkeypatch, [FakeResponse(json_data=releases(upd.GITHUB_REPO))] * 2)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert upd.latest_release()["tag"].endswith("-macos")
    monkeypatch.setattr(sys, "platform", "win32")
    assert upd.latest_release()["tag"].endswith("-windows")


def test_no_usable_release(upd, monkeypatch):
    repo = upd.GITHUB_REPO
    fake_get(monkeypatch, [FakeResponse(status=404)])
    assert upd.latest_release("windows") is None
    fake_get(monkeypatch, [FakeResponse(json_data=[])])
    assert upd.latest_release("windows") is None
    # tylko paczka macOS — Windows nie ma czego pobrać
    fake_get(monkeypatch, [FakeResponse(json_data=[release_json(repo, "macos")])])
    assert upd.latest_release("windows") is None
    # szkic, wersja testowa i tag bez numeru wersji się nie liczą
    skipped = [release_json(repo, "windows", "9.9.9", 1, draft=True),
               release_json(repo, "windows", "9.9.8", 2, prerelease=True),
               {**release_json(repo, "windows", "9.9.7", 3), "tag_name": "nightly"}]
    fake_get(monkeypatch, [FakeResponse(json_data=skipped)])
    assert upd.latest_release("windows") is None
    fake_get(monkeypatch, [FakeResponse(status=500)])
    with pytest.raises(requests.HTTPError):
        upd.latest_release("windows")


def test_token_goes_only_into_the_header(upd, monkeypatch):
    calls = []
    fake_get(monkeypatch, [FakeResponse(json_data=releases(upd.GITHUB_REPO))] * 2, calls)
    upd.latest_release("windows")
    assert "Authorization" not in calls[0][1]["headers"]
    monkeypatch.setattr(upd, "UPDATE_TOKEN", "ghp_test")
    upd.latest_release("windows")
    assert calls[1][1]["headers"]["Authorization"] == "Bearer ghp_test"
    assert "ghp_test" not in calls[1][0]


def test_newer_version_is_compared_as_numbers(upd, monkeypatch):
    monkeypatch.setattr(upd, "APP_VERSION", "2.4.9")
    assert upd.is_newer("2.4.10")
    assert upd.is_newer("3.0.0")
    assert not upd.is_newer("2.4.9")
    assert not upd.is_newer("2.4.8")
    assert not upd.is_newer("nightly")


@pytest.mark.parametrize("frozen, platform, windows, mac", [
    (True, "win32", True, False),     # spakowany .exe — podmienia się sam
    (True, "darwin", False, True),    # Camera Capture.app — paczka ręcznie
    (False, "win32", False, False),   # z kodu — git pull
    (False, "darwin", False, False),
])
def test_who_can_update_itself(upd, monkeypatch, frozen, platform, windows, mac):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    assert upd.can_self_update() is windows
    assert upd.packaged_mac() is mac


# ---------- pobranie i rozpakowanie ----------

def test_download_unpacks_package_next_to_app(upd, monkeypatch):
    body = package_zip(NEW_PACKAGE)
    calls = []
    fake_get(monkeypatch, [FakeResponse(body=body, chunk=max(1, len(body) // 7))], calls)
    progress = []
    staging = upd.download_and_stage("https://api.github.com/x/assets/1", progress.append)
    assert calls[0][1]["headers"]["Accept"] == "application/octet-stream"
    assert calls[0][1]["stream"] is True
    assert staging == upd.install_dir / ".update" / "staging"
    assert (staging / EXE).read_text(encoding="utf-8") == "nowy exe"
    assert (staging / "_internal" / "python311.dll").is_file()
    assert not (upd.install_dir / ".update" / "update.zip").exists()
    assert progress[-1] == 100 and progress == sorted(progress) and len(progress) > 2


def test_download_accepts_zip_with_a_top_folder(upd, monkeypatch):
    body = package_zip({f"CameraCapture/{k}": v for k, v in NEW_PACKAGE.items()})
    fake_get(monkeypatch, [FakeResponse(body=body)])
    staging = upd.download_and_stage("u")
    assert staging.name == "CameraCapture" and (staging / EXE).is_file()


def test_download_rejects_paths_outside_the_package(upd, monkeypatch):
    body = package_zip({**NEW_PACKAGE, "../../zlo.txt": "nadpisany plik"})
    fake_get(monkeypatch, [FakeResponse(body=body)])
    with pytest.raises(ValueError, match="podejrzana"):
        upd.download_and_stage("u")
    assert not (upd.install_dir / ".update").exists()
    assert not (upd.install_dir.parent / "zlo.txt").exists()


def test_failed_download_leaves_nothing_behind(upd, monkeypatch):
    fake_get(monkeypatch, [FakeResponse(status=403, body=b"x")])
    with pytest.raises(requests.HTTPError):
        upd.download_and_stage("u")
    assert not (upd.install_dir / ".update").exists()


def test_package_must_have_exe_and_internal(upd, tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    with pytest.raises(ValueError, match=r"\.exe"):
        upd._validate_staging(pkg)
    (pkg / EXE).write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="_internal"):
        upd._validate_staging(pkg)
    (pkg / "_internal").mkdir()
    assert upd._validate_staging(pkg) == pkg / EXE


# ---------- start aktualizatora (stara wersja) ----------

def staged_package(upd, files=NEW_PACKAGE) -> Path:
    staging = upd.install_dir / ".update" / "staging"
    for name, text in files.items():
        p = staging / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return staging


class FakePopen:
    """Proces aktualizatora: `alive` = czy po 2 s jeszcze działa."""
    started: list = []

    def __init__(self, args, **kw):
        FakePopen.started.append((args, kw))

    def poll(self):
        return None if FakePopen.alive else 1


def test_updater_starts_from_the_new_package(upd, monkeypatch):
    monkeypatch.setattr(upd, "can_self_update", lambda: True)
    monkeypatch.setattr(upd.time, "sleep", lambda s: None)
    monkeypatch.setattr(upd.subprocess, "Popen", FakePopen)
    FakePopen.started, FakePopen.alive = [], True
    (upd.install_dir / "update_error.txt").write_text("stary błąd", encoding="utf-8")
    staging = staged_package(upd)
    log = upd.apply_update_and_restart(staging)
    args, kw = FakePopen.started[0]
    assert args == [str(staging / EXE), "--apply-update", str(upd.install_dir), str(__import__("os").getpid())]
    assert kw["cwd"] == str(staging)
    assert log == upd.install_dir / "update.log" and "aktualizator dziala" in log.read_text(encoding="utf-8")
    assert not (upd.install_dir / "update_error.txt").exists()


def test_app_is_not_closed_when_updater_dies_at_once(upd, monkeypatch):
    monkeypatch.setattr(upd, "can_self_update", lambda: True)
    monkeypatch.setattr(upd.time, "sleep", lambda s: None)
    monkeypatch.setattr(upd.subprocess, "Popen", FakePopen)
    FakePopen.started, FakePopen.alive = [], False
    with pytest.raises(RuntimeError, match="nie wystartowal"):
        upd.apply_update_and_restart(staged_package(upd))
    assert len(FakePopen.started) == 2   # jedna powtórka (antywirus na świeżym .exe)


def test_updater_refuses_outside_windows_exe(upd, monkeypatch):
    monkeypatch.setattr(upd, "can_self_update", lambda: False)
    with pytest.raises(RuntimeError, match="Windowsie"):
        upd.apply_update_and_restart(staged_package(upd))


# ---------- podmiana plików (nowa wersja w trybie --apply-update) ----------

def old_install(root: Path) -> None:
    files = {
        EXE: "stary exe",
        "_internal/python311.dll": "stara biblioteka",
        "_internal/tylko_stara.pyd": "zbędna po aktualizacji",
        "_internal/stary_katalog/x.dat": "też zbędny",
        ".env": "AUTOMAT_TOKEN=sekret\n",
        "photos/sesja/photo_1.jpg": "zdjęcie",
        "EDSDK.dll": "sterownik Canona",
        "EdsImage.dll": "sterownik Canona",
    }
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_install_replaces_program_and_keeps_user_files(upd, monkeypatch):
    old_install(upd.install_dir)
    staging = staged_package(upd, {**NEW_PACKAGE, ".env": "AUTOMAT_TOKEN=z paczki\n"})
    monkeypatch.setattr(sys, "executable", str(staging / EXE))
    spawned = []
    monkeypatch.setattr(upd, "_spawn", lambda exe, say: spawned.append(exe))
    rc = upd.run_apply_update([str(upd.install_dir), "0"])
    d = upd.install_dir
    assert rc == 0
    assert (d / EXE).read_text(encoding="utf-8") == "nowy exe"
    assert (d / "_internal" / "python311.dll").read_text(encoding="utf-8") == "nowa biblioteka"
    assert (d / "_internal" / "src" / "webui_static" / "index.html").is_file()
    assert not (d / "_internal" / "tylko_stara.pyd").exists()
    assert not (d / "_internal" / "stary_katalog").exists()
    # to, co operator dołożył, przeżywa aktualizację
    assert (d / ".env").read_text(encoding="utf-8") == "AUTOMAT_TOKEN=sekret\n"
    assert (d / "photos" / "sesja" / "photo_1.jpg").read_text(encoding="utf-8") == "zdjęcie"
    assert (d / "EDSDK.dll").is_file() and (d / "EdsImage.dll").is_file()
    assert spawned == [d.resolve() / EXE]
    assert "gotowe" in (d / "update.log").read_text(encoding="utf-8")
    assert not (d / "update_error.txt").exists()


def test_broken_package_brings_back_the_old_version(upd, monkeypatch):
    old_install(upd.install_dir)
    staging = staged_package(upd, {EXE: "nowy exe"})   # bez _internal
    monkeypatch.setattr(sys, "executable", str(staging / EXE))
    spawned, boxes = [], []
    monkeypatch.setattr(upd, "_spawn", lambda exe, say: spawned.append(exe))
    monkeypatch.setattr(upd, "_message_box", boxes.append)
    rc = upd.run_apply_update([str(upd.install_dir), "0"])
    d = upd.install_dir
    assert rc == 1
    assert (d / EXE).read_text(encoding="utf-8") == "stary exe"          # nic nie nadpisane
    assert (d / "_internal" / "tylko_stara.pyd").is_file()
    assert spawned == [d.resolve() / EXE]                # stara wersja wstaje
    assert "_internal" in boxes[0]
    marker = (d / "update_error.txt").read_text(encoding="utf-8")
    assert "_internal" in marker and "update.log" in marker


def test_copy_retries_while_windows_holds_the_file(upd, monkeypatch, tmp_path):
    src = tmp_path / "a.dll"
    src.write_text("x", encoding="utf-8")
    real_copy = upd.shutil.copy2
    fails = [PermissionError("zajęty"), PermissionError("zajęty")]
    def copy2(a, b):
        if fails:
            raise fails.pop(0)
        return real_copy(a, b)
    monkeypatch.setattr(upd.shutil, "copy2", copy2)
    monkeypatch.setattr(upd.time, "sleep", lambda s: None)
    upd._copy(src, tmp_path / "out" / "a.dll")
    assert (tmp_path / "out" / "a.dll").read_text(encoding="utf-8") == "x"
    fails[:] = [PermissionError("zajęty")] * 3
    with pytest.raises(PermissionError):
        upd._copy(src, tmp_path / "out" / "b.dll", attempts=3)


# ---------- sprzątanie przy następnym starcie ----------

def test_next_start_reports_failure_and_cleans_up(upd):
    (upd.install_dir / "update_error.txt").write_text("brak _internal\nLog: update.log\n", encoding="utf-8")
    for d in (upd.install_dir / ".update" / "staging", upd.temp_dir / "cc_update",
              upd.temp_dir / "cc_update_stary"):
        d.mkdir(parents=True)
        (d / "plik").write_text("x", encoding="utf-8")
    assert upd.cleanup_after_update() == "brak _internal\nLog: update.log"
    assert not (upd.install_dir / "update_error.txt").exists()
    assert not (upd.install_dir / ".update").exists()
    assert not (upd.temp_dir / "cc_update").exists()
    assert not (upd.temp_dir / "cc_update_stary").exists()
    assert upd.cleanup_after_update() is None


def test_cleanup_leaves_package_the_updater_still_runs_from(upd, monkeypatch):
    staging = staged_package(upd)
    monkeypatch.setattr(upd, "_in_use", lambda root: root == upd.install_dir / ".update")
    upd.cleanup_after_update()
    assert (staging / EXE).is_file()


# ---------- gdzie leżą .env i photos/ w spakowanej aplikacji ----------

@pytest.mark.parametrize("platform, executable, expected", [
    ("win32", "/Program/CameraCapture/Trixbrix - Camera Capture.exe", "/Program/CameraCapture"),
    ("darwin", "/Apps/Camera Capture/Camera Capture.app/Contents/MacOS/CameraCapture", "/Apps/Camera Capture"),
])
def test_user_files_live_next_to_the_app_not_inside_it(platform, executable, expected):
    """Aktualizacja podmienia .exe + _internal (Windows) albo całą .app (macOS),
    więc .env i photos/ muszą leżeć OBOK — inaczej znikną razem ze starą wersją."""
    code = (
        # zależności config ładujemy przed podmianą platformy — stdlib pod
        # udawanym win32 na macOS (i odwrotnie) by się nie zaimportował
        "import sys, os, tempfile; from pathlib import Path; import dotenv\n"
        f"sys.frozen = True; sys.platform = {platform!r}; sys.executable = {executable!r}\n"
        "from src import config\n"
        "print(config.PROJECT_DIR.as_posix())\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith(expected)


# ---------- przepływ w aplikacji ----------

def release_info(upd, kind: str = "windows") -> dict:
    """To, co `latest_release()` oddaje aplikacji dla danego systemu."""
    rel = release_json(upd.GITHUB_REPO, kind)
    asset = rel["assets"][0]
    return {
        "version": VERSION, "tag": rel["tag_name"], "published": rel["published_at"],
        "url": asset["url"], "size": asset["size"], "download": asset["browser_download_url"],
        "notes": "Co nowego", "page": rel["html_url"],
    }


@pytest.fixture
def windows_app(make_app, monkeypatch):
    from src import updater, webui
    monkeypatch.setattr(updater, "latest_release", lambda: release_info(updater))
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(updater, "packaged_mac", lambda: False)
    app = make_app()
    wait_for(lambda: app.state()["update"]["available"] == VERSION, 10, "wykryta aktualizacja")
    app.exits = []
    monkeypatch.setattr(webui.os, "_exit", lambda code: app.exits.append(code))
    monkeypatch.setattr(app, "stop", lambda: app.exits.append("stop"))
    return app


def test_windows_app_downloads_and_hands_over_to_updater(windows_app, monkeypatch, tmp_path):
    from src import updater
    app = windows_app
    u = app.state()["update"]
    assert u["canApply"] and not u["packagedMac"]
    assert any(f"Dostępna aktualizacja {VERSION}" in t for t in log_texts(app))
    calls = []
    def download(url, progress):
        calls.append(("download", url))
        progress(50)
        return tmp_path / "staging"
    monkeypatch.setattr(updater, "download_and_stage", download)
    monkeypatch.setattr(updater, "apply_update_and_restart",
                        lambda staging: calls.append(("apply", staging)) or tmp_path / "update.log")
    assert app.action({"action": "apply_update"})["ok"]
    wait_for(lambda: app.exits == ["stop", 0], 10, "zamknięcie po starcie aktualizatora")
    assert calls == [("download", release_info(updater)["url"]), ("apply", tmp_path / "staging")]


def test_windows_app_stays_open_when_updater_fails(windows_app, monkeypatch, tmp_path):
    from src import updater
    app = windows_app
    monkeypatch.setattr(updater, "download_and_stage", lambda url, progress: tmp_path)
    def fail(staging):
        raise RuntimeError("aktualizator nie wystartowal (kod 1)")
    monkeypatch.setattr(updater, "apply_update_and_restart", fail)
    app.action({"action": "apply_update"})
    wait_for(lambda: any("Nie udało się uruchomić aktualizatora" in t for t in log_texts(app)),
             10, "błąd aktualizatora w logu")
    assert app.exits == []
    assert app.state()["update"]["busy"] is False


def test_windows_app_does_not_update_during_a_photo(windows_app, monkeypatch):
    from src import updater
    app = windows_app
    called = []
    monkeypatch.setattr(updater, "download_and_stage", lambda *a: called.append(a))
    app.busy = "Zdjęcie…"
    app.action({"action": "apply_update"})
    wait_for(lambda: any("Trwa zdjęcie/obróbka" in t for t in log_texts(app)), 10, "odmowa")
    assert called == [] and app.exits == []


def test_windows_app_reports_failed_previous_update(make_app, monkeypatch):
    from src import updater
    monkeypatch.setattr(updater, "cleanup_after_update", lambda: "brak _internal")
    app = make_app()
    wait_for(lambda: any("Poprzednia aktualizacja nie doszła do skutku: brak _internal" in t
                         for t in log_texts(app)), 10, "błąd poprzedniej aktualizacji")


def test_windows_banner_updates_with_one_click(windows_app, page: Page, monkeypatch):
    from src import updater
    clicked = []
    monkeypatch.setattr(updater, "download_and_stage", lambda url, progress: clicked.append(url))
    page.goto(windows_app.url, wait_until="domcontentloaded")
    button = page.get_by_role("button", name="Zaktualizuj i uruchom ponownie")
    expect(button).to_be_visible()
    expect(page.get_by_text("git pull")).to_have_count(0)
    button.click()
    wait_for(lambda: clicked, 10, "pobranie po kliknięciu")


@pytest.fixture
def mac_app(make_app, monkeypatch):
    from src import updater
    monkeypatch.setattr(updater, "latest_release", lambda: release_info(updater, "macos"))
    monkeypatch.setattr(updater, "can_self_update", lambda: False)
    monkeypatch.setattr(updater, "packaged_mac", lambda: True)
    app = make_app()
    wait_for(lambda: app.state()["update"]["available"] == VERSION, 10, "wykryta aktualizacja")
    return app


def test_mac_app_points_to_the_macos_package(mac_app, monkeypatch):
    from src import updater
    u = mac_app.state()["update"]
    assert not u["canApply"] and u["packagedMac"]
    assert u["macDownload"] == release_info(updater, "macos")["download"]
    texts = log_texts(mac_app)
    assert any("Pobierz paczkę dla macOS" in t for t in texts)
    assert not any("git pull" in t for t in texts)
    # samo-aktualizacja na macOS nic nie pobiera
    called = []
    monkeypatch.setattr(updater, "download_and_stage", lambda *a: called.append(a))
    mac_app.action({"action": "apply_update"})
    wait_for(lambda: any("Samo-aktualizacja działa tylko dla .exe" in t for t in log_texts(mac_app)),
             10, "odmowa na macOS")
    assert called == []


def test_mac_banner_opens_the_macos_package(mac_app, page: Page, monkeypatch):
    import webbrowser
    from src import updater
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    page.goto(mac_app.url, wait_until="domcontentloaded")
    expect(page.get_by_role("button", name="Zaktualizuj i uruchom ponownie")).to_have_count(0)
    expect(page.get_by_text("git pull")).to_have_count(0)
    page.get_by_role("button", name="Pobierz dla macOS").click()
    wait_for(lambda: opened, 10, "otwarcie paczki macOS")
    assert opened == [release_info(updater, "macos")["download"]]


def test_source_run_suggests_git_pull(make_app, monkeypatch):
    from src import updater
    monkeypatch.setattr(updater, "latest_release", lambda: release_info(updater))
    monkeypatch.setattr(updater, "can_self_update", lambda: False)
    monkeypatch.setattr(updater, "packaged_mac", lambda: False)
    app = make_app()
    wait_for(lambda: any("git pull" in t for t in log_texts(app)), 10, "podpowiedź git pull")
    u = app.state()["update"]
    assert not u["canApply"] and not u["packagedMac"]


# ---------- tylko na Windowsie (CI) ----------

@pytest.mark.skipif(sys.platform != "win32", reason="uchwyt procesu z kernel32 tylko na Windowsie")
def test_win32_updater_waits_for_the_old_app_to_close(tmp_path):
    from src import updater
    old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    t0 = time.monotonic()
    said = []
    updater._wait_for_old_app(old.pid, tmp_path, said.append)
    assert time.monotonic() - t0 > 1.0
    assert old.poll() is not None
    assert any(f"czekam na zamkniecie pid {old.pid}" in s for s in said)
    # proces już zakończony: drugie czekanie wraca od razu (Popen trzyma
    # jeszcze jego uchwyt, więc Windows pozwala go otworzyć — nie czekamy 60 s)
    t0 = time.monotonic()
    updater._wait_for_old_app(old.pid, tmp_path, said.append)
    assert time.monotonic() - t0 < 1.0


@pytest.mark.skipif(sys.platform != "win32", reason="blokada pliku .exe tylko na Windowsie")
def test_win32_package_with_running_exe_counts_as_in_use(tmp_path):
    """Działający .exe jest zablokowany do zapisu — sprzątanie nie może wtedy
    skasować katalogu, z którego chodzi aktualizator."""
    from src import updater
    pkg = tmp_path / "staging"
    pkg.mkdir()
    venv = Path(sys.base_prefix)
    exe = pkg / "python.exe"
    exe.write_bytes((venv / "python.exe").read_bytes())
    for dll in venv.glob("python*.dll"):
        (pkg / dll.name).write_bytes(dll.read_bytes())
    for dll in venv.glob("vcruntime*.dll"):
        (pkg / dll.name).write_bytes(dll.read_bytes())
    assert not updater._in_use(pkg)
    proc = subprocess.Popen([str(exe), "-c", "import time; time.sleep(5)"],
                            env={"PYTHONHOME": str(venv), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    try:
        time.sleep(0.5)
        assert proc.poll() is None, "skopiowany python.exe nie wstał"
        assert updater._in_use(pkg)
    finally:
        proc.kill()
        proc.wait()
