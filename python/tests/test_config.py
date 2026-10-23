from textfixer.config import Config, update_ini_values


def test_presets_and_defaults(tmp_path):
    import shutil
    from pathlib import Path

    path = tmp_path / "c.ini"
    shutil.copyfile(Path(__file__).resolve().parent.parent / "config.example.ini", path)
    cfg = Config(path)
    assert [p.name for p in cfg.presets][:3] == ["Casual", "Professional", "Sarcastic"]
    assert [p.mode for p in cfg.presets].count("window") == 3 and len(cfg.tones) == 5
    assert cfg.provider == "local" and cfg.default_preset().name == "Casual"
    assert cfg.excluded_apps() == {"excel.exe"}
    assert cfg.number("Server", "PORT", 0) == 8000 and cfg.server("DEVICE") == "NPU,GPU,CPU"
    assert "\\n" not in cfg.explain_prompt()


def test_update_keeps_comments_and_adds(tmp_path):
    path = tmp_path / "c.ini"
    path.write_text("; top\n[Settings]\n; about model\nMODEL=old\n\n[Server]\nPORT=1\n\n[Preset1]\nNAME=x\n", encoding="utf-8")
    update_ini_values(path, "Settings", {"MODEL": "new", "NEWKEY": "v"})
    update_ini_values(path, "Server", {"PORT": "2"})
    update_ini_values(path, "Extra", {"A": "b"})
    text = path.read_text(encoding="utf-8")
    assert "; top" in text and "; about model" in text
    cfg = Config(path)
    assert cfg.setting("MODEL") == "new" and cfg.parser.get("Settings", "NEWKEY") == "v"
    assert cfg.server("PORT") == "2" and cfg.parser.get("Extra", "A") == "b"
    assert text.index("NEWKEY") < text.index("[Server]")  # added inside its own section
    assert cfg.presets[0].name == "x"
