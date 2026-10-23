import shutil
from pathlib import Path

from textfixer.config import Config
from textfixer.setup_cmd import run_setup


def fresh_cfg(tmp_path, url):
    path = tmp_path / "config.ini"
    shutil.copyfile(Path(__file__).resolve().parent.parent / "config.example.ini", path)
    cfg = Config(path)
    cfg.update("Settings", {"API_URL": url})
    return cfg


def test_setup_falls_back_to_the_next_model(tmp_path, ollama):
    ollama.installed[:] = []
    cfg = fresh_cfg(tmp_path, "http://127.0.0.1:18766")
    lines = []
    assert run_setup(cfg, ["broken-tag", "qwen3:4b"], wait=5, out=lines.append) == 0
    assert "qwen3:4b" in ollama.installed
    reread = Config(cfg.path)
    assert reread.setting("MODEL") == "qwen3:4b" and reread.provider == "ollama"
    assert any("could not download 'broken-tag'" in l for l in lines)


def test_setup_keeps_a_working_setup(tmp_path, ollama):
    ollama.installed[:] = ["llama3.2:latest"]
    cfg = fresh_cfg(tmp_path, "http://127.0.0.1:18766")  # MODEL=llama3.2 from the example
    lines = []
    assert run_setup(cfg, ["qwen3:4b"], wait=5, out=lines.append) == 0
    assert "Already set up" in lines[-1] and "qwen3:4b" not in ollama.installed


def test_setup_uses_an_installed_candidate_without_downloading(tmp_path, ollama):
    ollama.installed[:] = ["qwen3:4b"]
    ollama.requests.clear()
    cfg = fresh_cfg(tmp_path, "http://127.0.0.1:18766")
    cfg.update("Settings", {"MODEL": "something-missing"})
    assert run_setup(cfg, ["qwen3:4b", "qwen3:4b-instruct"], wait=5, out=lambda s: None) == 0
    assert Config(cfg.path).setting("MODEL") == "qwen3:4b"
    assert not [r for r in ollama.requests if r["path"] == "/api/pull"]


def test_setup_without_ollama_fails_clearly(tmp_path, monkeypatch):
    import textfixer.setup_cmd as sc

    monkeypatch.setattr(sc, "start_ollama", lambda: False)
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)
    cfg = fresh_cfg(tmp_path, "http://127.0.0.1:18999")
    lines = []
    assert run_setup(cfg, ["qwen3:4b"], wait=0, out=lines.append) == 1
    assert any("could not be started" in l for l in lines)
