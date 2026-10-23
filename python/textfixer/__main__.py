"""python -m textfixer [run|check]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

from .config import Config, ensure_config

FROZEN = getattr(sys, "frozen", False)  # running as the packaged .exe
DEFAULT_CONFIG = (Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent) / "config.ini"


def load_config(path: str | None) -> tuple[Config, bool]:
    target = Path(path or os.environ.get("TEXTFIXER_CONFIG") or DEFAULT_CONFIG)
    created = not target.exists()
    return Config(ensure_config(target)), created


def cmd_check(args) -> int:
    """Is Ollama running, and is the chosen model installed?"""
    from .llm import LLMClient

    cfg, _ = load_config(args.config)
    llm = LLMClient(cfg)
    print(f"Provider: {cfg.provider}   Model: {cfg.setting('MODEL')}")
    if cfg.provider != "ollama":
        print("(the Ollama check only applies to PROVIDER=ollama)")
        return 0
    print(f"Ollama at {llm.ollama_base()}: ", end="")
    try:
        models = llm.list_models()
    except Exception as exc:
        print("NOT reachable")
        print(f"  {exc}")
        print("  Install Ollama from https://ollama.com/download and make sure it is running.")
        return 1
    print("running")
    print("Installed models:", ", ".join(models) or "(none)")
    model = cfg.setting("MODEL")
    if llm.has_model(model):
        print(f"Model '{model}': installed")
        return 0
    print(f"Model '{model}': NOT installed. Download it in Settings, or run:  ollama pull {model}")
    return 1


def cmd_run(args) -> int:
    from .app import App
    from .tray import start_tray
    from .ui import Ui

    cfg, created = load_config(args.config)
    ui = Ui()
    app = App(cfg, ui)
    start_tray(app, str(cfg.path))
    app.start()
    if created:
        ui.call(app.show_settings)
    else:
        ui.call(ui.show_tip, f"TextFixer is running. Hotkeys:\n{app.hotkey_summary()}", 6)
        threading.Thread(target=app.check_ollama, daemon=True, name="ollama-check").start()
    ui.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="textfixer", description=__doc__)
    parser.add_argument("--config", help="path to config.ini (default: next to the program)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="start the app (default)")
    sub.add_parser("check", help="is Ollama running and the model installed?")
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if sys.stderr is None:  # the windowed .exe has no console: log to a file next to the config
        logging.basicConfig(level=level, format=fmt, filename=str(DEFAULT_CONFIG.with_name("textfixer.log")))
    else:
        logging.basicConfig(level=level, format=fmt)

    return cmd_check(args) if args.command == "check" else cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
