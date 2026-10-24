import pytest

from textfixer.clipboard import match_whitespace
from textfixer.hotkeys import HotkeyManager, parse_hotkey, vk_for


def test_parse():
    c = parse_hotkey("^+Space")
    assert c.mods == {"ctrl", "shift"} and c.key == "space" and c.vk == 0x20 and c.describe() == "Ctrl+Shift+Space"
    assert parse_hotkey("^LButton").is_mouse and parse_hotkey("^LButton").describe() == "Ctrl+Left click"
    assert parse_hotkey("^1").vk == 0x31 and parse_hotkey("!f5").vk == 0x74
    assert parse_hotkey("$#a").mods == {"win"}
    for bad in ("", "^", "^+Nonsense"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)
    assert vk_for("a") == 0x41


def test_register_first_wins():
    m = HotkeyManager(lambda a, c: None)
    m.register("one", "^1")
    m.register("two", "^1")
    assert m.combos[(frozenset({"ctrl"}), "1")][0] == "one"
    assert m._key_for_vk(0x31) == "1" and m._key_for_vk(0x20) == "space" and m._key_for_vk(0x72) == "f3"
    assert parse_hotkey("^LButton").is_mouse


def test_match_whitespace():
    assert match_whitespace(" fixed \n", "orig\n") == "fixed\r\n"
    assert match_whitespace("a\nb", "x") == "a\r\nb"
