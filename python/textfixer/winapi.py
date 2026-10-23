"""Small Windows helpers (foreground window, key state...). Harmless no-ops elsewhere."""

from __future__ import annotations

import os
import sys
import time

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
CF_HDROP = 15


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0) if IS_WINDOWS else 0


def process_name(hwnd: int) -> str:
    """Executable name (e.g. "EXCEL.EXE") of the process owning a window, "" if unknown."""
    if not IS_WINDOWS or not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


def activate(hwnd: int) -> None:
    """Bring a window to the front (so the paste goes into the app the text came from)."""
    if not IS_WINDOWS or not hwnd:
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if not user32.SetForegroundWindow(hwnd):
        # Windows only lets the foreground process do this; a tap on Alt lifts the restriction
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)
    for _ in range(40):  # wait up to 2 s
        if user32.GetForegroundWindow() == hwnd:
            break
        time.sleep(0.05)


def key_down(vk: int) -> bool:
    return bool(IS_WINDOWS and user32.GetAsyncKeyState(vk) & 0x8000)


def clipboard_has_files() -> bool:
    """True when files are on the clipboard (selected in Explorer): not text to rewrite."""
    return bool(IS_WINDOWS and user32.IsClipboardFormatAvailable(CF_HDROP))
