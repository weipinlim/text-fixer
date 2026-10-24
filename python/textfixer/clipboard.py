"""Copy the current selection and paste a result over it, restoring the clipboard after."""

from __future__ import annotations

import time
from dataclasses import dataclass

import pyperclip

from . import winapi
from .keys import default_sender


@dataclass
class Selection:
    text: str
    saved: str  # clipboard text from before (restored after pasting)


class Clipboard:
    def __init__(self, wait_ms: int = 300, sender=None):
        self.wait_ms = wait_ms
        self._sender = sender
        # Optional: tells whether the user is really still holding a modifier. Without it, the
        # modifiers we lift are not pressed again (better a released key than one stuck down)
        self.physically_down = None

    @property
    def sender(self):
        """Types keys (SendInput on Windows). Created on first use."""
        if self._sender is None:
            self._sender = default_sender()
        return self._sender

    # -- keys -----------------------------------------------------------
    @staticmethod
    def _held_modifiers() -> list[tuple[str, int]]:
        """Shift/Alt/Win keys that are down right now (the hotkey's own modifiers): (name, vk)."""
        held = []
        if winapi.key_down(winapi.VK_SHIFT):
            held.append(("shift", winapi.VK_SHIFT))
        if winapi.key_down(winapi.VK_MENU):
            held.append(("alt", winapi.VK_MENU))
        if winapi.key_down(winapi.VK_LWIN) or winapi.key_down(winapi.VK_RWIN):
            held.append(("win", winapi.VK_LWIN))
        return held

    def send_ctrl(self, char: str) -> None:
        """Press Ctrl+<char> as if typed. Other held modifiers are lifted for the moment so
        Ctrl+Shift+Space does not turn the Ctrl+C into Ctrl+Shift+C. Afterwards they are pressed
        again only if the user is still really holding them, so no key is left stuck down."""
        s = self.sender
        vk = ord(char.upper())
        lifted = self._held_modifiers()
        for _, mod in lifted:
            s.release(mod)
        try:
            ctrl_held = winapi.key_down(winapi.VK_CONTROL)  # the user is holding Ctrl already
            if not ctrl_held:
                s.press(winapi.VK_CONTROL)
            s.press(vk)
            s.release(vk)
            if not ctrl_held:
                s.release(winapi.VK_CONTROL)
        finally:
            for name, mod in lifted:
                if self.physically_down and self.physically_down(name):
                    s.press(mod)

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


def send_combo(sender, combo) -> None:
    """Type a hotkey's keys (used to pass a hotkey on to the app when it was not used)."""
    mod_vks = {"ctrl": winapi.VK_CONTROL, "alt": winapi.VK_MENU, "shift": winapi.VK_SHIFT, "win": winapi.VK_LWIN}
    pressed = []
    for mod in combo.mods:
        vk = mod_vks[mod]
        if not winapi.key_down(vk):  # the user may already have let go
            sender.press(vk)
            pressed.append(vk)
    sender.press(combo.vk)
    sender.release(combo.vk)
    for vk in reversed(pressed):
        sender.release(vk)
