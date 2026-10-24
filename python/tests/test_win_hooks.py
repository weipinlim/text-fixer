"""The Windows hotkey thread (RegisterHotKey), driven by a fake Windows API."""
import queue
import time

import pytest

from textfixer.hotkeys import MOD_NOREPEAT, WM_HOTKEY, HotkeyManager, MouseHotkeyError


class FakeApi:
    """Records RegisterHotKey calls and lets the test post messages like Windows would."""

    def __init__(self, taken=()):
        self.registered: dict[int, tuple[int, int]] = {}
        self.calls: list[tuple] = []
        self.taken = set(taken)  # (mods, vk) another program owns
        self.messages: "queue.Queue" = queue.Queue()

    def init_queue(self):
        pass

    def thread_id(self):
        return 42

    def register(self, hotkey_id, mods, vk):
        self.calls.append(("register", hotkey_id))
        if (mods & ~MOD_NOREPEAT, vk) in self.taken:
            return False
        self.registered[hotkey_id] = (mods, vk)
        return True

    def unregister(self, hotkey_id):
        self.calls.append(("unregister", hotkey_id))
        self.registered.pop(hotkey_id, None)

    def get_message(self):
        return self.messages.get(timeout=5)

    def post(self, thread_id, message, wparam=0):
        self.messages.put((message, wparam))


def wait_for(cond, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


@pytest.fixture
def setup():
    fired = []
    api = FakeApi(taken={(0x2 | 0x1, 0x20)})  # Ctrl+Alt+Space belongs to another program
    m = HotkeyManager(lambda action, combo: fired.append(action), api=api)
    m.register("preset1", "^1")
    m.register("popup", "^+Space")
    m.register("chat", "^!Space")
    m.start()
    yield m, api, fired
    m.stop()


def id_of(m, action):
    return next(i for i, (a, _) in m._ids.items() if a == action)


def test_registers_with_the_right_modifiers_and_reports_taken_ones(setup):
    m, api, _ = setup
    assert api.registered[id_of(m, "preset1")] == (0x2 | MOD_NOREPEAT, 0x31)
    assert api.registered[id_of(m, "popup")] == (0x2 | 0x4 | MOD_NOREPEAT, 0x20)
    assert id_of(m, "chat") not in api.registered
    assert m.errors == ["Ctrl+Alt+Space is already used by another program"]


def test_hotkey_message_fires_the_action(setup):
    m, api, fired = setup
    api.post(42, WM_HOTKEY, id_of(m, "popup"))
    assert wait_for(lambda: fired == ["popup"])


def test_pause_gives_the_keys_back_and_resume_takes_them_again(setup):
    m, api, fired = setup
    m.set_paused(True)
    assert wait_for(lambda: not api.registered)
    api.post(42, WM_HOTKEY, id_of(m, "preset1"))  # a late message while paused does nothing
    assert wait_for(api.messages.empty)
    time.sleep(0.05)  # let the hotkey thread finish handling it
    m.set_paused(False)
    assert wait_for(lambda: id_of(m, "preset1") in api.registered)
    assert fired == []


def test_passthrough_types_the_keys_while_the_hotkey_is_off(setup):
    m, api, _ = setup
    hid = id_of(m, "preset1")
    seen = []
    m.passthrough(m._ids[hid][1], lambda: seen.append(hid in api.registered))
    assert wait_for(lambda: seen and hid in api.registered)
    assert seen == [False]  # the keys were sent while our hotkey was unregistered
    assert api.calls[-2:] == [("unregister", hid), ("register", hid)]


def test_stop_unregisters_everything(setup):
    m, api, _ = setup
    m.stop()
    assert wait_for(lambda: not api.registered)


def test_mouse_hotkeys_are_refused():
    m = HotkeyManager(lambda a, c: None, api=FakeApi())
    with pytest.raises(MouseHotkeyError):
        m.register("default", "^LButton")


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
