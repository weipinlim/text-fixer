"""Global hotkeys with the same syntax as the AutoHotkey version: ^ Ctrl, ! Alt, + Shift,
# Win, then a key or LButton/RButton/MButton (e.g. ^+Space, ^LButton, ^!1).

On Windows the matched key or click is swallowed (the app never sees it) so you can pass it
through yourself when nothing is selected. Elsewhere hotkeys are only observed."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Callable

from . import winapi

log = logging.getLogger("textfixer.hotkeys")

MOUSE_KEYS = {"lbutton", "rbutton", "mbutton"}
NAMED_VK = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
            "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
            "pgup": 0x21, "pgdn": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
MOD_NAMES = {"^": "ctrl", "!": "alt", "+": "shift", "#": "win"}
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


def pynput_key(name: str):
    """pynput key (character or Key.xxx) for a key name used in hotkeys."""
    from pynput.keyboard import Key

    if len(name) == 1:
        return name
    aliases = {"return": "enter", "escape": "esc", "pgup": "page_up", "pgdn": "page_down"}
    return getattr(Key, aliases.get(name, name))


def parse_hotkey(spec: str) -> Combo:
    m = re.fullmatch(r"([~$*<>^!+#]*)(\S+)", spec.strip())
    if not m:
        raise ValueError(f"invalid hotkey '{spec}'")
    mods = frozenset(MOD_NAMES[c] for c in m.group(1) if c in MOD_NAMES)
    key = m.group(2).lower()
    if key not in MOUSE_KEYS:
        vk_for(key)  # raises for keys we do not know
    return Combo(mods, key, spec.strip())


def _mods_now() -> frozenset:
    mods = set()
    if winapi.key_down(winapi.VK_CONTROL):
        mods.add("ctrl")
    if winapi.key_down(winapi.VK_MENU):
        mods.add("alt")
    if winapi.key_down(winapi.VK_SHIFT):
        mods.add("shift")
    if winapi.key_down(winapi.VK_LWIN) or winapi.key_down(winapi.VK_RWIN):
        mods.add("win")
    return frozenset(mods)


class HotkeyManager:
    """Calls on_trigger(action, combo) in a new thread when a registered hotkey is pressed."""

    def __init__(self, on_trigger: Callable[[str, Combo], None]):
        self.on_trigger = on_trigger
        self.combos: dict[tuple, tuple[str, Combo]] = {}  # (mods, key) -> (action, combo)
        self.paused = False
        self.on_any_input: Callable[[], None] | None = None  # any click or Esc that is not a hotkey
        self._listeners = []
        self._held: set = set()            # keys whose press we swallowed (until released)
        self._swallowed: dict[str, threading.Event] = {}  # mouse buttons: set when physically released
        self.suppresses = winapi.IS_WINDOWS

    def register(self, action: str, spec: str) -> Combo:
        combo = parse_hotkey(spec)
        self.combos.setdefault((combo.mods, combo.key), (action, combo))
        return combo

    def _any_input(self) -> None:
        if self.on_any_input:
            threading.Thread(target=self.on_any_input, daemon=True).start()

    def _fire(self, action: str, combo: Combo) -> None:
        if self.paused:
            return
        threading.Thread(target=self.on_trigger, args=(action, combo), daemon=True).start()

    # -- start / stop ---------------------------------------------------
    def start(self) -> None:
        from pynput import keyboard, mouse

        if winapi.IS_WINDOWS:
            kl = keyboard.Listener(win32_event_filter=lambda msg, data: self._win_key(kl, msg, data))
            ml = mouse.Listener(win32_event_filter=lambda msg, data: self._win_mouse(ml, msg, data))
        else:
            kl = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            ml = mouse.Listener(on_click=self._on_click)
            self._pressed: set = set()
        for listener in (kl, ml):
            listener.daemon = True
            listener.start()
            self._listeners.append(listener)

    def stop(self) -> None:
        for listener in self._listeners:
            listener.stop()
        self._listeners.clear()

    # -- Windows: low level hooks that can swallow events ----------------
    def _win_key(self, listener, msg, data) -> bool:
        if msg not in (0x100, 0x104, 0x101, 0x105) or data.flags & 0x10:  # not a key event / injected by us
            return True
        vk, down = data.vkCode, msg in (0x100, 0x104)
        if not down:
            if vk in self._held:
                self._held.discard(vk)
                listener.suppress_event()
            return True
        found = self.combos.get((_mods_now(), self._key_for_vk(vk)))
        if found and not self.paused:
            if vk not in self._held:  # ignore auto-repeat
                self._held.add(vk)
                self._fire(*found)
            listener.suppress_event()
        elif vk == 0x1B:
            self._any_input()
        return True

    def _win_mouse(self, listener, msg, data) -> bool:
        names = {0x201: "lbutton", 0x204: "rbutton", 0x207: "mbutton"}
        ups = {0x202: "lbutton", 0x205: "rbutton", 0x208: "mbutton"}
        if data.flags & 0x01:  # injected by us
            return True
        if msg in names:
            found = self.combos.get((_mods_now(), names[msg]))
            if found and not self.paused:
                self._swallowed[names[msg]] = threading.Event()
                self._fire(*found)
                listener.suppress_event()
            else:
                self._any_input()
        elif msg in ups and ups[msg] in self._swallowed:
            self._swallowed[ups[msg]].set()
            listener.suppress_event()
        return True

    @staticmethod
    def _key_for_vk(vk: int) -> str:
        for name, value in NAMED_VK.items():
            if value == vk:
                return name
        if 0x70 <= vk <= 0x87:
            return f"f{vk - 0x70 + 1}"
        return chr(vk).lower() if 0x30 <= vk <= 0x5A else ""

    def wait_mouse_release(self, button: str, timeout: float = 3.0) -> None:
        event = self._swallowed.get(button)
        if event:
            event.wait(timeout)

    # -- elsewhere: observe only -------------------------------------------
    @staticmethod
    def _norm(key) -> str:
        from pynput.keyboard import Key, KeyCode

        if isinstance(key, KeyCode):
            return (key.char or "").lower()
        names = {Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl", Key.alt_l: "alt", Key.alt_r: "alt", Key.alt_gr: "alt",
                 Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift", Key.cmd: "win",
                 Key.cmd_l: "win", Key.cmd_r: "win"}
        return names.get(key) or str(key).split(".")[-1].lower()

    def _on_press(self, key) -> None:
        name = self._norm(key)
        if name in MOD_LABEL:
            self._pressed.add(name)
            return
        found = self.combos.get((frozenset(self._pressed), name))
        # With Ctrl held the key may arrive as a control character: also try the raw key code
        if not found and getattr(key, "vk", None):
            found = self.combos.get((frozenset(self._pressed), self._key_for_vk(key.vk)))
        if found:
            self._fire(*found)
        elif name == "esc":
            self._any_input()

    def _on_release(self, key) -> None:
        self._pressed.discard(self._norm(key))

    def _on_click(self, x, y, button, pressed) -> None:
        if pressed:
            name = {"left": "lbutton", "right": "rbutton", "middle": "mbutton"}.get(button.name, "")
            found = self.combos.get((frozenset(self._pressed), name))
            if found:
                self._fire(*found)
            else:
                self._any_input()
