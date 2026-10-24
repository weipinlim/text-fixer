"""`textfixer setup`: get Ollama ready for TextFixer (used by the installer).

Waits for Ollama (starting it if needed), downloads the first model from a list that Ollama has,
and writes PROVIDER/MODEL into config.ini. Keeps an existing, working setup as it is."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

from .config import Config
from .llm import LLMClient, LLMError

# Tried in order; the first one Ollama can download is used. Several names because Ollama's
# exact tags for Qwen3 4B instruct may differ.
DEFAULT_MODELS = ["qwen3:4b-instruct-2507-q4_K_M", "qwen3:4b-instruct", "qwen3:4b"]


def start_ollama() -> bool:
    """Start Ollama in the background if we can find it. True if something was started."""
    candidates = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append([os.path.join(local, "Programs", "Ollama", "ollama app.exe")])
        candidates.append([os.path.join(local, "Programs", "Ollama", "ollama.exe"), "serve"])
    found = shutil.which("ollama")
    if found:
        candidates.append([found, "serve"])
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    for command in candidates:
        if os.path.exists(command[0]):
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            return True
    return False


def wait_for_ollama(llm: LLMClient, seconds: float, out=print) -> bool:
    deadline = time.time() + seconds
    started = False
    while True:
        try:
            llm.list_models()
            return True
        except LLMError:
            pass
        if not started:
            started = True
            if start_ollama():
                out("Starting Ollama...")
        if time.time() >= deadline:
            return False
        time.sleep(2)


def pull_with_progress(llm: LLMClient, name: str, out=print) -> None:
    last = ""
    for status, fraction in llm.pull_model(name):
        line = status if fraction is None else f"{status}  {fraction:6.1%}"
        if status != last and last:
            sys.stdout.write("\n")
        sys.stdout.write("\r" + line.ljust(70))
        sys.stdout.flush()
        last = status
    sys.stdout.write("\n")


def run_setup(cfg: Config, models: list[str], wait: float, out=print) -> int:
    llm = LLMClient(cfg)
    out(f"Waiting for Ollama at {llm.ollama_base()} ...")
    if not wait_for_ollama(llm, wait, out):
        out("Ollama is not running and could not be started.")
        out("Install it from https://ollama.com/download, start it, then open TextFixer > Settings > Download.")
        return 1

    current = cfg.setting("MODEL")
    if cfg.provider == "ollama" and current and llm.has_model(current):
        out(f"Already set up: Ollama has '{current}'.")
        return 0

    for name in models:
        if llm.has_model(name):
            out(f"Ollama already has '{name}'.")
        else:
            out(f"Downloading '{name}' (this can take a while)...")
            try:
                pull_with_progress(llm, name, out)
            except LLMError as exc:
                out(f"  could not download '{name}': {exc}")
                continue
        cfg.update("Settings", {"PROVIDER": "ollama", "MODEL": name})
        out(f"Done. TextFixer will use '{name}'.")
        return 0

    out("None of the models could be downloaded: " + ", ".join(models))
    out("Check your internet connection, then use TextFixer > Settings > Download.")
    return 1
