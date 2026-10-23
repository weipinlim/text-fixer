"""Copy the current selection and paste a result over it, restoring the clipboard after."""

from __future__ import annotations

import time
from dataclasses import dataclass

import pyperclip

from . import winapi


@dataclass
class Selection:
    text: str
    saved: str  # clipboard text from before (restored after pasting)


class Clipboard:
    def __init__(self, wait_ms: int = 300, controller=None):
        self.wait_ms = wait_ms
        self._controller = controller

    @property
    def controller(self):
        if self._controller is None:
            from pynput import keyboard  # imported late: it needs a display

            self._controller = keyboard.Controller()
        return self._controller

    # -- keys -----------------------------------------------------------
    def _held_modifiers(self):
        """Shift/Alt/Win keys physically held right now (the hotkey's own modifiers)."""
        from pynput.keyboard import Key

        held = []
        if winapi.key_down(winapi.VK_SHIFT):
            held.append(Key.shift)
        if winapi.key_down(winapi.VK_MENU):
            held.append(Key.alt)
        if winapi.key_down(winapi.VK_LWIN) or winapi.key_down(winapi.VK_RWIN):
            held.append(Key.cmd)
        return held

    def send_ctrl(self, char: str) -> None:
        """Press Ctrl+<char> as if typed. Other held modifiers are lifted for the moment so
        Ctrl+Shift+Space does not turn the Ctrl+C into Ctrl+Shift+C."""
        from pynput.keyboard import Key

        c = self.controller
        lifted = self._held_modifiers()
        for key in lifted:
            c.release(key)
        try:
            with c.pressed(Key.ctrl):
                c.press(char)
                c.release(char)
        finally:
            for key in lifted:
                c.press(key)

    # -- clipboard ------------------------------------------------------
    def copy_selection(self) -> Selection | None:
        """Ctrl+C the selection. None if nothing (or only files) was copied."""
        try:
            saved = pyperclip.paste()
        except Exception:
            saved = ""
        pyperclip.copy("")
        self.send_ctrl("c")
        text = ""
        deadline = time.time() + self.wait_ms / 1000
        while time.time() < deadline:
            try:
                text = pyperclip.paste()
            except Exception:
                text = ""
            if text:
                break
            time.sleep(0.02)
        if not text or winapi.clipboard_has_files():
            self.restore(saved)
            return None
        return Selection(text, saved)

    def restore(self, saved: str) -> None:
        try:
            pyperclip.copy(saved)
        except Exception:
            pass

    def paste(self, text: str, saved: str) -> None:
        pyperclip.copy(text)
        time.sleep(0.05)
        self.send_ctrl("v")
        time.sleep(0.5)  # let the app read the clipboard before it is restored
        self.restore(saved)


def match_whitespace(fixed: str, original: str) -> str:
    """Keep the selection's trailing whitespace/newline, Windows line endings."""
    fixed = fixed.strip(" \t\r\n")
    tail = original[len(original.rstrip()):]
    fixed += tail
    return fixed.replace("\r\n", "\n").replace("\n", "\r\n")


def send_combo(controller, combo) -> None:
    """Type a hotkey's keys (used to pass a swallowed hotkey on to the app)."""
    from pynput.keyboard import Key

    from .hotkeys import pynput_key

    mod_keys = {"ctrl": (Key.ctrl, winapi.VK_CONTROL), "alt": (Key.alt, winapi.VK_MENU),
                "shift": (Key.shift, winapi.VK_SHIFT), "win": (Key.cmd, winapi.VK_LWIN)}
    pressed = []
    for mod in combo.mods:
        key, vk = mod_keys[mod]
        if not winapi.key_down(vk):  # the user may already have let go
            controller.press(key)
            pressed.append(key)
    key = pynput_key(combo.key)
    controller.press(key)
    controller.release(key)
    for k in pressed:
        controller.release(k)
