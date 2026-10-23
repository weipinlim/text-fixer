"""python -m textfixer [run|serve|app|check|convert]"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from .config import Config, ensure_config

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.ini"


def load_config(path: str | None) -> tuple[Config, bool]:
    target = Path(path or os.environ.get("TEXTFIXER_CONFIG") or DEFAULT_CONFIG)
    created = not target.exists()
    return Config(ensure_config(target)), created


def start_server(cfg: Config, backend_kind: str, block: bool):
    from .backend import create_backend
    from .server import ServerThread, serve

    backend = create_backend(cfg, backend_kind)
    host, port = cfg.server("HOST"), int(cfg.number("Server", "PORT", 8000))
    key, max_new = cfg.server("API_KEY"), int(cfg.number("Server", "MAX_NEW_TOKENS", 1024))
    logging.getLogger("textfixer").info("API server on http://%s:%s/v1 (model '%s' on %s)", host, port,
                                        backend.model_name, backend.device)
    if block:
        serve(backend, host, port, key, max_new)
        return None
    server = ServerThread(backend, host, port, key, max_new)
    server.start()
    return server


def cmd_serve(args) -> int:
    cfg, _ = load_config(args.config)
    start_server(cfg, args.backend, block=True)
    return 0


def cmd_check(args) -> int:
    cfg, _ = load_config(args.config)
    try:
        import openvino as ov

        core = ov.Core()
        print("OpenVINO devices:")
        for device in core.available_devices:
            print(f"  {device}: {core.get_property(device, 'FULL_DEVICE_NAME')}")
        if "NPU" not in core.available_devices:
            print("  (no NPU found: update the Intel NPU driver, or use DEVICE=GPU,CPU)")
    except Exception as exc:
        print("OpenVINO is not usable:", exc)
        return 1
    model_dir = Path(cfg.server("MODEL_DIR"))
    print(f"Model folder {model_dir}: {'found' if model_dir.exists() else 'NOT found (see README: convert or download a model)'}")
    return 0


def cmd_convert(args) -> int:
    """Export a Hugging Face model to OpenVINO int4 (the format the NPU needs)."""
    command = ["optimum-cli", "export", "openvino", "-m", args.model, "--weight-format", "int4", "--sym",
               "--ratio", "1.0", "--group-size", str(args.group_size), "--trust-remote-code", args.out]
    print("Running:", " ".join(command))
    return subprocess.call(command)


def cmd_app(args, with_server: bool) -> int:
    from .app import App
    from .tray import start_tray
    from .ui import Ui

    cfg, created = load_config(args.config)
    ui = Ui()
    app = App(cfg, ui)
    config_path = str(cfg.path)
    start_tray(app, config_path)
    app.start()

    if with_server and cfg.provider == "local" and not cfg.setting("API_URL"):
        app.server_status = "loading"

        def load() -> None:
            try:
                start_server(cfg, args.backend, block=False)
                app.server_status = "ready"
                ui.call(ui.show_tip, f"Model ready. Hotkeys:\n{app.hotkey_summary()}", 6)
            except Exception as exc:
                logging.getLogger("textfixer").exception("model failed to load")
                app.server_status = f"failed ({exc})"
                ui.call(ui.error, f"The local model could not be loaded:\n\n{exc}\n\nSee the README (model folder, NPU "
                                  "driver), or open Settings and use another provider.")

        threading.Thread(target=load, daemon=True, name="model-loader").start()
    else:
        ui.call(ui.show_tip, f"TextFixer is running. Hotkeys:\n{app.hotkey_summary()}", 6)
    if created:
        ui.call(app.show_settings)
    ui.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="textfixer", description=__doc__)
    parser.add_argument("--config", help="path to config.ini (default: python/config.ini)")
    parser.add_argument("--backend", choices=["openvino", "echo"], default="openvino",
                        help="echo = no model, answers with your own text (to try the app)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="the app and the local API server (default)")
    sub.add_parser("serve", help="only the local OpenAI-compatible API server")
    sub.add_parser("app", help="only the app (uses the provider/URL from config.ini)")
    sub.add_parser("check", help="list OpenVINO devices (is the NPU found?)")
    conv = sub.add_parser("convert", help="convert a Hugging Face model to OpenVINO int4 for the NPU")
    conv.add_argument("--model", required=True, help="e.g. Qwen/Qwen2.5-3B-Instruct")
    conv.add_argument("--out", required=True, help="output folder, e.g. models/qwen2.5-3b")
    conv.add_argument("--group-size", type=int, default=-1, help="-1 = channel-wise (NPU default), or 128")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    command = args.command or "run"
    if command == "serve":
        return cmd_serve(args)
    if command == "check":
        return cmd_check(args)
    if command == "convert":
        return cmd_convert(args)
    return cmd_app(args, with_server=(command == "run"))


if __name__ == "__main__":
    sys.exit(main())
