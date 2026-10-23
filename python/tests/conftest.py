import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textfixer.backend import EchoBackend  # noqa: E402
from textfixer.clipboard import Selection  # noqa: E402
from textfixer.config import INCOMPATIBLE_MARK, Config  # noqa: E402


class GibberishAware(EchoBackend):
    """Echo, but refuses text containing GIBBERISH the way a model would."""

    def generate(self, messages, params, on_text=None):
        res = super().generate(messages, params, on_text)
        if any("GIBBERISH" in m["content"] for m in messages if m["role"] == "user"):
            res.text = INCOMPATIBLE_MARK
        return res


class FakeClipboard:
    def __init__(self, text="sample text  \n"):
        self.text = text
        self.pasted = []
        self.restored = []
        self.controller = None

    def copy_selection(self):
        return Selection(self.text, "SAVED") if self.text else None

    def paste(self, text, saved):
        self.pasted.append((text, saved))

    def restore(self, saved):
        self.restored.append(saved)


class FakeHotkeys:
    suppresses = False
    paused = False
    on_any_input = None

    def register(self, action, spec):
        from textfixer.hotkeys import parse_hotkey
        return parse_hotkey(spec)

    def start(self): pass
    def stop(self): pass
    def wait_mouse_release(self, *a, **k): pass


@pytest.fixture(scope="session")
def server():
    from textfixer.server import ServerThread

    srv = ServerThread(GibberishAware("m"), "127.0.0.1", 18766)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def cfg(tmp_path, server):
    path = tmp_path / "config.ini"
    shutil.copyfile(Path(__file__).resolve().parent.parent / "config.example.ini", path)
    c = Config(path)
    c.update("Settings", {"PROVIDER": "local", "TIMEOUT": "10"})
    c.update("Server", {"PORT": "18766"})
    return c


@pytest.fixture(scope="session")
def _ui():
    import tkinter as tk
    from textfixer.ui import Ui

    try:
        u = Ui()
    except tk.TclError:
        pytest.skip("no display (run under xvfb-run)")
    yield u
    u.reset()
    u.root.destroy()


@pytest.fixture
def ui(_ui):
    _ui.reset()
    yield _ui
    _ui.reset()


def pump(ui, cond, timeout=8.0):
    """Run the tk event loop until cond() is true."""
    end = time.time() + timeout
    while time.time() < end:
        ui.root.update()
        if cond():
            return True
        time.sleep(0.02)
    ui.root.update()
    return cond()


def run_thread(fn, *args):
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()
    return t
