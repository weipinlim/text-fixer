"""The Windows low-level hook filters, fed simulated events (the logic is plain Python)."""
from types import SimpleNamespace

import pytest

import textfixer.hotkeys as hotkeys
from textfixer.hotkeys import HotkeyManager

LDOWN, LUP, RDOWN, RUP = 0x201, 0x202, 0x204, 0x205
KEYDOWN, KEYUP = 0x100, 0x101


class FakeListener:
    def __init__(self):
        self.suppressed = 0

    def suppress_event(self):
        self.suppressed += 1


@pytest.fixture
def mgr(monkeypatch):
    fired = []
    m = HotkeyManager(lambda action, combo: fired.append(action))
    m._fire = lambda action, combo: fired.append(action)  # no threads in tests
    m.fired = fired
    m.register("default", "^LButton")
    m.register("preset1", "^1")
    m.mods = frozenset()
    monkeypatch.setattr(hotkeys, "_mods_now", lambda: m.mods)
    return m


def mouse(m, msg, injected=False):
    lst = FakeListener()
    m._win_mouse(lst, msg, SimpleNamespace(flags=1 if injected else 0))
    return lst.suppressed


def key(m, msg, vk, injected=False):
    lst = FakeListener()
    m._win_key(lst, msg, SimpleNamespace(flags=0x10 if injected else 0, vkCode=vk))
    return lst.suppressed


def test_ctrl_click_is_swallowed_with_its_release(mgr):
    mgr.mods = frozenset({"ctrl"})
    assert mouse(mgr, LDOWN) == 1 and mgr.fired == ["default"]
    assert mouse(mgr, LUP) == 1


def test_normal_clicks_after_a_hotkey_click_are_not_swallowed(mgr):
    mgr.mods = frozenset({"ctrl"})
    mouse(mgr, LDOWN)
    mouse(mgr, LUP)
    mgr.mods = frozenset()
    for _ in range(3):  # ordinary clicks afterwards must reach Windows untouched
        assert mouse(mgr, LDOWN) == 0
        assert mouse(mgr, LUP) == 0
    assert mgr.fired == ["default"]


def test_release_is_known_after_the_swallowed_up(mgr):
    mgr.mods = frozenset({"ctrl"})
    mouse(mgr, LDOWN)
    mouse(mgr, LUP)
    mgr.wait_mouse_release("lbutton", timeout=0.1)  # returns at once: already released


def test_injected_clicks_pass(mgr):
    mgr.mods = frozenset({"ctrl"})
    assert mouse(mgr, LDOWN, injected=True) == 0 and mouse(mgr, LUP, injected=True) == 0
    assert mgr.fired == []


def test_other_button_is_not_affected(mgr):
    mgr.mods = frozenset({"ctrl"})
    mouse(mgr, LDOWN)
    mouse(mgr, LUP)
    mgr.mods = frozenset()
    assert mouse(mgr, RDOWN) == 0 and mouse(mgr, RUP) == 0


def test_key_hotkey_down_and_up_swallowed_then_normal_typing_passes(mgr):
    mgr.mods = frozenset({"ctrl"})
    assert key(mgr, KEYDOWN, 0x31) == 1 and mgr.fired == ["preset1"]
    assert key(mgr, KEYDOWN, 0x31) == 1 and mgr.fired == ["preset1"]  # auto-repeat: no second fire
    assert key(mgr, KEYUP, 0x31) == 1
    mgr.mods = frozenset()
    assert key(mgr, KEYDOWN, 0x31) == 0 and key(mgr, KEYUP, 0x31) == 0


def test_paused_swallows_nothing(mgr):
    mgr.paused = True
    mgr.mods = frozenset({"ctrl"})
    assert mouse(mgr, LDOWN) == 0 and mouse(mgr, LUP) == 0
    assert key(mgr, KEYDOWN, 0x31) == 0 and key(mgr, KEYUP, 0x31) == 0


# ---- Clipboard.send_ctrl must never leave a modifier stuck down ----------------------------

class RecordingController:
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(("press", str(key)))

    def release(self, key):
        self.events.append(("release", str(key)))

    def pressed(self, key):
        import contextlib

        @contextlib.contextmanager
        def ctx():
            self.press(key)
            yield
            self.release(key)
        return ctx()


def send(monkeypatch, logical_down, physically_down):
    import textfixer.clipboard as clipboard
    from textfixer.winapi import VK_CONTROL, VK_LWIN, VK_MENU, VK_SHIFT

    names = {VK_SHIFT: "shift", VK_MENU: "alt", VK_LWIN: "win", VK_CONTROL: "ctrl"}
    monkeypatch.setattr(clipboard.winapi, "key_down", lambda vk: names.get(vk) in logical_down)
    c = clipboard.Clipboard(controller=RecordingController())
    c.physically_down = (lambda mod: mod in physically_down) if physically_down is not None else None
    c.send_ctrl("c")
    return c.controller.events


def test_lifted_shift_is_not_pressed_again_after_the_user_let_go(monkeypatch):
    events = send(monkeypatch, {"shift"}, physically_down=set())
    assert events == [("release", "Key.shift"), ("press", "Key.ctrl"), ("press", "c"), ("release", "c"),
                      ("release", "Key.ctrl")]


def test_lifted_shift_is_restored_while_still_held(monkeypatch):
    events = send(monkeypatch, {"shift", "ctrl"}, physically_down={"shift", "ctrl"})
    # Ctrl is already down: it is not pressed/released again; Shift comes back since it is still held
    assert events == [("release", "Key.shift"), ("press", "c"), ("release", "c"), ("press", "Key.shift")]


def test_without_hook_information_nothing_is_pressed_again(monkeypatch):
    events = send(monkeypatch, {"alt"}, physically_down=None)
    assert ("press", "Key.alt") not in events and events[0] == ("release", "Key.alt")


def test_hook_tracks_physical_modifiers(mgr):
    assert not mgr.physically_down("shift")
    key(mgr, KEYDOWN, 0xA0)  # left shift
    assert mgr.physically_down("shift")
    key(mgr, KEYDOWN, 0xA0, injected=True)  # our own events do not count
    key(mgr, KEYUP, 0xA0)
    assert not mgr.physically_down("shift")
