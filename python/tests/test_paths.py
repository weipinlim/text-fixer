import sys
from textfixer.app import App


def test_relaunch_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["whatever", "--config", "c.ini"])
    cmd, cwd = App.relaunch_command()
    assert cmd[0] == sys.executable and cmd[1].endswith("run_textfixer.py") and cmd[2:] == ["--config", "c.ini"] and cwd
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd, cwd = App.relaunch_command()
    assert cmd == [sys.executable, "--config", "c.ini"] and cwd is None
