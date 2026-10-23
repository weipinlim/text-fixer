import sys
from pathlib import Path

from textfixer.app import App
from textfixer.config import Config


def test_relative_paths_follow_the_config_file(tmp_path):
    p = tmp_path / "config.ini"
    p.write_text("[Server]\nMODEL_DIR=models/m\n", encoding="utf-8")
    cfg = Config(p)
    assert Path(cfg.resolve_path(cfg.server("MODEL_DIR"))) == (tmp_path / "models" / "m").resolve()
    absolute = str(Path(sys.executable).resolve())
    assert cfg.resolve_path(absolute) == absolute


def test_relaunch_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["whatever", "--config", "c.ini"])
    cmd, cwd = App.relaunch_command()
    assert cmd[0] == sys.executable and cmd[1].endswith("run_textfixer.py") and cmd[2:] == ["--config", "c.ini"] and cwd
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd, cwd = App.relaunch_command()
    assert cmd == [sys.executable, "--config", "c.ini"] and cwd is None
