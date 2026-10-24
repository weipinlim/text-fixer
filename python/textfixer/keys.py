"""Typing keys (to send Ctrl+C / Ctrl+V and to pass a hotkey on to the app).

On Windows this uses SendInput directly, so the Windows build needs no keyboard library at all.
Elsewhere (Linux, for tests) it uses pynput."""

from __future__ import annotations

import sys

# Keys Windows treats as "extended" (they need KEYEVENTF_EXTENDEDKEY to be sent correctly)
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x6F, 0x90, 0xA3, 0xA5}


def input_structs():
    """The ctypes structures for SendInput: (INPUT, union, KEYBDINPUT). Portable, so testable anywhere."""
    import ctypes

    # Fixed-size types (WORD = 16 bit, DWORD/LONG = 32 bit) so the layout is the Windows one everywhere
    WORD, DWORD, LONG, ULONG_PTR = ctypes.c_uint16, ctypes.c_uint32, ctypes.c_int32, ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD), ("time", DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):  # only here so the union has the right size
        _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD), ("dwFlags", DWORD), ("time", DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", DWORD), ("u", INPUTUNION)]

    return INPUT, INPUTUNION, KEYBDINPUT


def key_event(vk: int, up: bool, scan: int = 0):
    """One keyboard INPUT record for SendInput."""
    INPUT, INPUTUNION, KEYBDINPUT = input_structs()
    flags = (0x0001 if vk in EXTENDED else 0) | (0x0002 if up else 0)  # KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP
    return INPUT(type=1, u=INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))  # 1 = INPUT_KEYBOARD


class WinSender:
    """Presses and releases keys with SendInput."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ct = ctypes
        self._INPUT = input_structs()[0]
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(self._INPUT), ctypes.c_int]
        self.user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]

    def _send(self, vk: int, up: bool) -> None:
        scan = self.user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC: some apps look at the scan code
        event = key_event(vk, up, scan)
        self.user32.SendInput(1, self._ct.byref(event), self._ct.sizeof(self._INPUT))

    def press(self, vk: int) -> None:
        self._send(vk, up=False)

    def release(self, vk: int) -> None:
        self._send(vk, up=True)


class PynputSender:
    """For Linux (tests): the same calls through pynput."""

    def __init__(self):
        from pynput.keyboard import Controller

        self._c = Controller()

    @staticmethod
    def _key(vk: int):
        from pynput.keyboard import Key

        named = {0x10: Key.shift, 0x11: Key.ctrl, 0x12: Key.alt, 0x5B: Key.cmd, 0x5C: Key.cmd, 0x20: Key.space,
                 0x0D: Key.enter, 0x09: Key.tab, 0x1B: Key.esc}
        if vk in named:
            return named[vk]
        if 0x70 <= vk <= 0x87:
            return getattr(Key, f"f{vk - 0x70 + 1}")
        return chr(vk).lower()

    def press(self, vk: int) -> None:
        self._c.press(self._key(vk))

    def release(self, vk: int) -> None:
        self._c.release(self._key(vk))


def default_sender():
    return WinSender() if sys.platform == "win32" else PynputSender()
