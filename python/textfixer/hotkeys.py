"""Global keyboard hotkeys with the same syntax as the AutoHotkey version: ^ Ctrl, ! Alt,
+ Shift, # Win, then a key (e.g. ^+Space, ^1, ^!F5).

On Windows they use RegisterHotKey, the system's own hotkey mechanism: nothing of ours runs
on other keystrokes or mouse movements, so it cannot slow the PC down or leave keys stuck.
Mouse shortcuts (LButton...) are not supported here for that reason. Elsewhere (Linux, for
tests) hotkeys are only observed."""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

from . import winapi

log = logging.getLogger("textfixer.hotkeys")

MOUSE_KEYS = {"lbutton", "rbutton", "mbutton"}
NAMED_VK = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
            "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
            "pgup": 0x21, "pgdn": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
MOD_NAMES = {"^": "ctrl", "!": "alt", "+": "shift", "#": "win"}
MOD_FLAGS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}  # RegisterHotKey modifiers
MOD_NOREPEAT = 0x4000
MOD_LABEL = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}


@dataclass(frozen=True)
class Combo:
    mods: frozenset
    key: str  # lower case: "1", "space", "f5", "lbutton"
    spec: str

    @property
    def is_mouse(self) -> bool:
        return self.key in MOUSE_KEYS

    @property
    def vk(self) -> int:
        return vk_for(self.key)

    def describe(self) -> str:
        names = {"lbutton": "Left click", "rbutton": "Right click", "mbutton": "Middle click"}
        mods = "".join(MOD_LABEL[m] + "+" for m in ("ctrl", "alt", "shift", "win") if m in self.mods)
        return mods + names.get(self.key, self.key.upper() if len(self.key) == 1 else self.key.capitalize())


def vk_for(key: str) -> int:
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    if key in NAMED_VK:
        return NAMED_VK[key]
    if re.fullmatch(r"f([1-9]|1\d|2[0-4])", key):
        return 0x70 + int(key[1:]) - 1
    raise ValueError(f"unsupported key '{key}'")


def parse_hotkey(spec: str) -> Combo:
    m = re.fullmatch(r"([~$*<>^!+#]*)(\S+)", spec.strip())
    if not m:
        raise ValueError(f"invalid hotkey '{spec}'")
    mods = frozenset(MOD_NAMES[c] for c in m.group(1) if c in MOD_NAMES)
    key = m.group(2).lower()
    if key not in MOUSE_KEYS:
        vk_for(key)  # raises for keys we do not know
    return Combo(mods, key, spec.strip())


class MouseHotkeyError(ValueError):
    pass


WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
WM_PAUSE, WM_PASS = 0x8001, 0x8002  # our own messages (WM_APP + n)


class Win32Api:
    """The few Windows calls the hotkey thread needs (a fake stands in for it in tests)."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ct, self._wt = ctypes, wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self.user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                             wintypes.UINT, wintypes.UINT]
        self.user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._msg = wintypes.MSG()

    def thread_id(self) -> int:
        return self.kernel32.GetCurrentThreadId()

    def init_queue(self) -> None:
        self.user32.PeekMessageW(self._ct.byref(self._msg), None, 0, 0, 0)  # creates the message queue

    def register(self, hotkey_id: int, mods: int, vk: int) -> bool:
        return bool(self.user32.RegisterHotKey(None, hotkey_id, mods, vk))

    def unregister(self, hotkey_id: int) -> None:
        self.user32.UnregisterHotKey(None, hotkey_id)

    def get_message(self):
        """Wait for the next message: (message, wparam), or None when the loop should end."""
        if self.user32.GetMessageW(self._ct.byref(self._msg), None, 0, 0) <= 0:
            return None
        return self._msg.message, self._msg.wParam

    def post(self, thread_id: int, message: int, wparam: int = 0) -> None:
        self.user32.PostThreadMessageW(thread_id, message, wparam, 0)


class HotkeyManager:
    """Calls on_trigger(action, combo) in a new thread when a registered hotkey is pressed."""

    def __init__(self, on_trigger: Callable[[str, Combo], None], api=None):
        self.on_trigger = on_trigger
        self.combos: dict[tuple, tuple[str, Combo]] = {}  # (mods, key) -> (action, combo)
        self.errors: list[str] = []  # hotkeys Windows refused (usually: another program has them)
        self.paused = False
        self.suppresses = winapi.IS_WINDOWS  # Windows swallows a registered hotkey: pass it on if unused
        self._api = api
        self._ids: dict[int, tuple[str, Combo]] = {}
        self._thread_id = 0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._sends: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._listener = None

    def register(self, action: str, spec: str) -> Combo:
        combo = parse_hotkey(spec)
        if combo.is_mouse:
            raise MouseHotkeyError(f"mouse shortcuts ({spec}) are not supported in the Python version")
        self.combos.setdefault((combo.mods, combo.key), (action, combo))
        return combo

    def _fire(self, action: str, combo: Combo) -> None:
        threading.Thread(target=self.on_trigger, args=(action, combo), daemon=True).start()

    # -- start / stop ---------------------------------------------------------------
    def start(self) -> None:
        if self._api is not None or winapi.IS_WINDOWS:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="hotkeys")
            self._thread.start()
            self._ready.wait(5)
        else:
            from pynput import keyboard

            self._pressed: set = set()
            self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener.daemon = True
            self._listener.start()

    def stop(self) -> None:
        if self._thread_id:
            self._api.post(self._thread_id, WM_QUIT)
        if self._listener:
            self._listener.stop()

    def set_paused(self, paused: bool) -> None:
        """Paused hotkeys are given back to Windows, so the keys work as normal in every app."""
        self.paused = paused
        if self._thread_id:
            self._api.post(self._thread_id, WM_PAUSE)

    def passthrough(self, combo: Combo, send: Callable[[], None]) -> None:
        """Let the app have the keys after all: send() types them while our hotkey is off."""
        if not self._thread_id:
            return
        for hotkey_id, (_, c) in self._ids.items():
            if c == combo:
                self._sends.put(send)
                self._api.post(self._thread_id, WM_PASS, hotkey_id)
                return

    # -- the hotkey thread (Windows) -------------------------------------------------
    def _register_all(self) -> None:
        for hotkey_id, (_, combo) in self._ids.items():
            mods = sum(MOD_FLAGS[m] for m in combo.mods) | MOD_NOREPEAT
            if not self._api.register(hotkey_id, mods, combo.vk):
                self.errors.append(f"{combo.describe()} is already used by another program")

    def _unregister_all(self) -> None:
        for hotkey_id in self._ids:
            self._api.unregister(hotkey_id)

    def _loop(self) -> None:
        if self._api is None:
            self._api = Win32Api()
        api = self._api
        api.init_queue()
        self._thread_id = api.thread_id()
        self._ids = {i: found for i, found in enumerate(self.combos.values(), start=1)}
        if not self.paused:
            self._register_all()
        self._ready.set()
        while True:
            message = api.get_message()
            if message is None or message[0] == WM_QUIT:
                break
            kind, wparam = message
            if kind == WM_HOTKEY and wparam in self._ids and not self.paused:
                self._fire(*self._ids[wparam])
            elif kind == WM_PAUSE:
                self._unregister_all()
                if not self.paused:
                    self._register_all()
            elif kind == WM_PASS and wparam in self._ids:
                api.unregister(wparam)
                try:
                    self._sends.get_nowait()()
                    time.sleep(0.1)  # let Windows deliver the keys before the hotkey is back
                except Exception:
                    log.exception("pass-through failed")
                finally:
                    if not self.paused:
                        _, combo = self._ids[wparam]
                        api.register(wparam, sum(MOD_FLAGS[m] for m in combo.mods) | MOD_NOREPEAT, combo.vk)
        self._unregister_all()
        self._thread_id = 0

    # -- elsewhere: observe only -------------------------------------------------------
    @staticmethod
    def _norm(key) -> str:
        from pynput.keyboard import Key, KeyCode

        if isinstance(key, KeyCode):
            return (key.char or "").lower()
        names = {Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl", Key.alt_l: "alt", Key.alt_r: "alt", Key.alt_gr: "alt",
                 Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift", Key.cmd: "win",
                 Key.cmd_l: "win", Key.cmd_r: "win"}
        return names.get(key) or str(key).split(".")[-1].lower()

    @staticmethod
    def _key_for_vk(vk: int) -> str:
        for name, value in NAMED_VK.items():
            if value == vk:
                return name
        if 0x70 <= vk <= 0x87:
            return f"f{vk - 0x70 + 1}"
        return chr(vk).lower() if 0x30 <= vk <= 0x5A else ""

    def _on_press(self, key) -> None:
        name = self._norm(key)
        if name in MOD_LABEL:
            self._pressed.add(name)
            return
        found = self.combos.get((frozenset(self._pressed), name))
        # With Ctrl held the key may arrive as a control character: also try the raw key code
        if not found and getattr(key, "vk", None):
            found = self.combos.get((frozenset(self._pressed), self._key_for_vk(key.vk)))
        if found and not self.paused:
            self._fire(*found)

    def _on_release(self, key) -> None:
        self._pressed.discard(self._norm(key))
