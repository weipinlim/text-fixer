import json
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textfixer.clipboard import Selection  # noqa: E402
from textfixer.config import INCOMPATIBLE_MARK, Config  # noqa: E402

PORT = 18766


class MockOllama(ThreadingHTTPServer):
    """Speaks the few Ollama endpoints TextFixer uses. Answers with the last user message."""

    def __init__(self):
        super().__init__(("127.0.0.1", PORT), MockHandler)
        self.requests: list[dict] = []
        self.installed = ["llama3.2:latest", "qwen2.5:3b"]
        self.delay = 0.0  # seconds each chat answer takes
        self.no_think_models = {"qwen2.5:3b"}  # these reject the "think" option, like some real models


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": n} for n in self.server.installed]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        record = {"path": self.path, "body": body, "start": time.time()}
        self.server.requests.append(record)
        if self.path == "/api/pull":
            self.send_response(200)
            self.end_headers()
            if body["model"].startswith("broken"):
                self.wfile.write(b'{"error": "pull model manifest: file does not exist"}\n')
                return
            for status, done in (("pulling manifest", None), ("pulling abc", 50), ("pulling abc", 100), ("success", None)):
                event = {"status": status}
                if done is not None:
                    event.update(total=100, completed=done)
                self.wfile.write((json.dumps(event) + "\n").encode())
                self.wfile.flush()
            self.server.installed.append(body["model"] if ":" in body["model"] else body["model"] + ":latest")
            return
        if self.path != "/api/chat":
            return self._send(404, {"error": "not found"})
        if body["model"] not in ("llama3.2", "qwen2.5:3b"):
            return self._send(404, {"error": f"model '{body['model']}' not found"})
        if "think" in body and body["model"] in self.server.no_think_models:
            return self._send(400, {"error": f'"{body["model"]}" does not support thinking'})
        last = next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user")
        if "SLOW" in last:
            time.sleep(0.5)
        time.sleep(self.server.delay)
        record["end"] = time.time()
        text = INCOMPATIBLE_MARK if "GIBBERISH" in last else f"ECHO: {last}"
        self._send(200, {"model": body["model"], "message": {"role": "assistant", "content": text}, "done": True})


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
def ollama():
    server = MockOllama()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def cfg(tmp_path, ollama):
    ollama.requests.clear()
    ollama.installed[:] = ["llama3.2:latest", "qwen2.5:3b"]
    ollama.delay = 0.0
    path = tmp_path / "config.ini"
    shutil.copyfile(Path(__file__).resolve().parent.parent / "config.example.ini", path)
    c = Config(path)
    c.update("Settings", {"PROVIDER": "ollama", "API_URL": f"http://127.0.0.1:{PORT}", "TIMEOUT": "10"})
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
