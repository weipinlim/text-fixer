"""System tray icon (pystray). Optional: the app still works without it."""

from __future__ import annotations

import logging

log = logging.getLogger("textfixer.tray")


def make_icon_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(46, 125, 50, 255))
    draw.rectangle((18, 16, 46, 24), fill="white")
    draw.rectangle((28, 16, 36, 50), fill="white")
    return image


def start_tray(app, config_path: str):
    """Show the tray icon; returns it (or None if pystray is not usable here)."""
    try:
        import pystray
        from pystray import Menu, MenuItem as Item
    except Exception as exc:
        log.warning("No tray icon (%s)", exc)
        return None

    def toggle_pause(icon, item):
        app.toggle_pause()

    def toggle_startup(icon, item):
        app.toggle_startup(config_path)

    items = [
        Item("Chat window", lambda icon, item: app.ui.call(app.open_chat)),
        Item("Settings...", lambda icon, item: app.ui.call(app.show_settings)),
        Item("Show hotkeys", lambda icon, item: app.ui.call(app.ui.info, app.hotkey_summary() or "(none)")),
        Item("Pause hotkeys", toggle_pause, checked=lambda item: app.hk.paused),
    ]
    try:
        import winreg  # noqa: F401  (only exists on Windows)

        items.append(Item("Start with Windows", toggle_startup, checked=lambda item: app.startup_enabled()))
    except ImportError:
        pass
    items.append(Item("Quit", lambda icon, item: (icon.stop(), app.hk.stop(), app.ui.call(app.ui.quit))))
    try:
        icon = pystray.Icon("TextFixer", make_icon_image(), "TextFixer", Menu(*items))
        icon.run_detached()
        return icon
    except Exception as exc:
        log.warning("No tray icon (%s)", exc)
        return None
