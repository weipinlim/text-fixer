"""The desktop app: hotkeys -> selection -> LLM -> paste / windows."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import tkinter as tk

from . import winapi
from .clipboard import Clipboard, match_whitespace, send_combo
from .config import (CUSTOM_PROMPT, INCOMPATIBLE_MARK, INCOMPATIBLE_RULE, Config, Preset)
from .hotkeys import Combo, HotkeyManager, MouseHotkeyError
from .llm import LLMClient
from .ui import CompareWindow, Context, Job, PopupWindow, ResultWindow, SettingsWindow, Ui

log = logging.getLogger("textfixer.app")

ACTIONS = {  # setting name -> action id, label
    "DEFAULT_HOTKEY": ("default", "default tone"),
    "POPUP_HOTKEY": ("popup", "popup: describe a change or pick a tone"),
    "MENU_HOTKEY": ("menu", "choose a tone from a menu"),
    "PREVIEW_HOTKEY": ("preview", "show every tone in tabs, then pick one"),
    "RESULTS_MENU_HOTKEY": ("results", "show every tone as a list, then pick one"),
    "EXPLAIN_HOTKEY": ("explain", "explain the selected word in a tooltip"),
    "CHAT_HOTKEY": ("chat", "open the chat window"),
}
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class App:
    def __init__(self, cfg: Config, ui: Ui, clip: Clipboard | None = None, llm: LLMClient | None = None,
                 hotkeys: HotkeyManager | None = None):
        self.cfg, self.ui = cfg, ui
        self.clip = clip or Clipboard(int(cfg.number("SELECTION_WAIT_MS", 300)))
        self.llm = llm or LLMClient(cfg)
        self.hk = hotkeys or HotkeyManager(self.on_hotkey)
        self.busy = False
        self.registered: list[tuple[str, Combo]] = []
        self.hotkey_errors: list[str] = []
        self.mouse_dropped: list[str] = []  # mouse shortcuts from an older config.ini, now switched off
        self.on_restart = self.restart

    # -- setup -----------------------------------------------------------------
    def register_hotkeys(self) -> None:
        self.registered.clear()
        dropped: dict[str, dict[str, str]] = {}
        for setting, (action, label) in ACTIONS.items():
            spec = self.cfg.setting(setting)
            if spec and not self._register(action, spec, setting, label):
                dropped.setdefault("Settings", {})[setting] = ""
        for preset in self.cfg.presets:
            if preset.hotkey and not self._register(f"preset{preset.index}", preset.hotkey,
                                                    f"[Preset{preset.index}] HOTKEY", preset.name):
                dropped.setdefault(f"Preset{preset.index}", {})["HOTKEY"] = ""
        # Mouse shortcuts from an older config.ini: switch them off in the file, so the note shows once
        for section, values in dropped.items():
            self.cfg.update(section, values)

    def _register(self, action: str, spec: str, where: str, label: str) -> bool:
        """False only for a mouse shortcut (dropped); other problems are reported as errors."""
        try:
            combo = self.hk.register(action, spec)
        except MouseHotkeyError:
            self.mouse_dropped.append(f"{spec} ({label})")
            return False
        except ValueError as exc:
            self.hotkey_errors.append(f"{where}={spec}: {exc}")
            return True
        self.registered.append((label, combo))
        return True

    def hotkey_summary(self) -> str:
        return "\n".join(f"{combo.describe()} = {label}" for label, combo in self.registered)

    def start(self) -> None:
        self.register_hotkeys()
        try:
            self.hk.start()
        except Exception as exc:
            log.error("Could not start the hotkeys: %s", exc)
            self.hotkey_errors.append(f"Hotkeys could not be started: {exc}")
        problems = self.hotkey_errors + getattr(self.hk, "errors", [])
        if problems:
            self.ui.call(self.ui.error, "Some hotkeys do not work:\n\n" + "\n".join(problems) +
                         "\n\nChange them in Settings (tray icon).")
        if self.mouse_dropped:
            self.ui.call(self.ui.info, "Mouse shortcuts are switched off in this version, because they made the "
                         "mouse slow:\n\n" + "\n".join(self.mouse_dropped) + "\n\nUse Ctrl+Shift+Space (popup) "
                         "instead: it has every tone plus Compare and Explain. You can also give those "
                         "keyboard shortcuts in Settings.")

    # -- helpers ---------------------------------------------------------------
    def check_ollama(self) -> None:
        """At start-up: is Ollama running, and is the chosen model installed? (runs in a thread)"""
        if self.cfg.provider != "ollama":
            return
        model = self.cfg.setting("MODEL")
        try:
            if not self.llm.has_model(model):
                self.ui.call(self.ui.show_tip, f"Ollama does not have the model '{model}' yet.\n"
                             "Open Settings (tray icon) and click Download.", 8)
        except Exception as exc:
            self.ui.call(self.ui.show_tip, f"Cannot reach Ollama.\nStart Ollama, then try a hotkey again.\n({exc})", 8)

    def is_excluded(self, hwnd: int) -> bool:
        return winapi.process_name(hwnd).lower() in self.cfg.excluded_apps()

    def passthrough(self, combo: Combo | None) -> None:
        """The hotkey was not used (nothing selected...): give the keys to the app after all."""
        if combo is None or not self.hk.suppresses:
            return
        self.hk.passthrough(combo, lambda: send_combo(self.clip.controller, combo))

    def release(self, ctx: Context) -> None:
        """Nothing was done with the selection: put the clipboard back."""
        self.clip.restore(ctx.saved)

    # -- hotkey entry (runs in its own thread) -------------------------------------
    def on_hotkey(self, action: str, combo: Combo) -> None:
        try:
            if action == "chat":
                self.ui.call(self.open_chat)
                return
            if self.busy or self.ui.windows or self.is_excluded(winapi.foreground_window()):
                self.passthrough(combo)
                return
            hwnd = winapi.foreground_window()
            selection = self.clip.copy_selection()
            if selection is None:
                self.passthrough(combo)
                return
            ctx = Context(selection.text, selection.saved, hwnd, combo)
            if action.startswith("preset"):
                preset = next((p for p in self.cfg.presets if f"preset{p.index}" == action), None)
                if preset:
                    self.run_preset(preset, ctx)
            elif action == "default":
                self.run_preset(self.cfg.default_preset(), ctx)
            elif action == "popup":
                self.ui.call(self.show_popup, ctx)
            elif action == "menu":
                self.ui.call(self.show_menu, ctx)
            elif action in ("preview", "results"):
                self.compare(ctx, "tabs" if action == "preview" else "list")
            elif action == "explain":
                self.explain(ctx)
        except Exception:
            log.exception("hotkey action failed")

    # -- actions -----------------------------------------------------------------
    def run_preset(self, preset: Preset, ctx: Context) -> None:
        ctx.taken = True
        if preset.mode == "window":
            self.clip.restore(ctx.saved)
            self.ui.call(self._open_window, preset, ctx.original)
        else:
            threading.Thread(target=self.apply_tone, args=(preset, ctx), daemon=True).start()

    def run_custom(self, instruction: str, ctx: Context) -> None:
        ctx.taken = True
        custom = Preset(0, "Custom", "", "replace", CUSTOM_PROMPT)
        text = f"Make this change to the text below.\nDescribed change: {instruction}\n\nText:\n{ctx.original}"
        threading.Thread(target=self.apply_tone, args=(custom, ctx, text), daemon=True).start()

    def _open_window(self, preset: Preset, original: str) -> None:
        ResultWindow(self.ui, self, preset.name, preset.prompt, original)

    def open_chat(self) -> None:
        ResultWindow(self.ui, self, "Chat")

    def apply_tone(self, preset: Preset, ctx: Context, user_text: str = "") -> None:
        """Rewrite the selection with a tone and paste it over the selection."""
        self.busy = True
        try:
            self.ui.call(self.ui.show_tip, f"{preset.name}...")
            try:
                out = self.llm.complete([{"role": "user", "content": user_text or ctx.original}],
                                        f"{preset.prompt} {INCOMPATIBLE_RULE}")
            except Exception as exc:
                self.release(ctx)
                self.ui.call(self.ui.hide_tip)
                self.ui.call(self.ui.error, f"Request failed:\n\n{exc}")
                return
            self.ui.call(self.ui.hide_tip)
            if out.strip() == INCOMPATIBLE_MARK:
                self.release(ctx)
                self.ui.call(self.ui.show_tip, "The text isn't compatible with this request.", 2.5)
                return
            self.deliver_now(out, ctx)
        finally:
            self.busy = False

    def deliver(self, text: str, ctx: Context) -> None:
        threading.Thread(target=self.deliver_now, args=(text, ctx), daemon=True).start()

    def deliver_now(self, text: str, ctx: Context) -> None:
        winapi.activate(ctx.hwnd)
        self.clip.paste(match_whitespace(text, ctx.original), ctx.saved)

    def explain(self, ctx: Context) -> None:
        self.clip.restore(ctx.saved)
        self.busy = True
        try:
            self.ui.call(self.ui.show_tip, "Explaining...")
            try:
                answer = self.llm.complete([{"role": "user", "content": ctx.original}], self.cfg.explain_prompt())
            except Exception as exc:
                self.ui.call(self.ui.hide_tip)
                self.ui.call(self.ui.error, f"Request failed:\n\n{exc}")
                return
            seconds = self.cfg.number("EXPLAIN_SECONDS", 30)
            self.ui.call(self.ui.show_tip, answer.strip(), seconds)
        finally:
            self.busy = False

    def compare(self, ctx: Context, mode: str) -> None:
        """Run every tone on the selection and show the answers as they come in.

        With Ollama the tones run one after another: a local model shares one CPU/GPU, so asking
        for all at once only makes every answer arrive late. One at a time, the first answer shows
        up quickly and you can pick it while the rest are still being written. Closing the window
        (or picking one) stops the ones not started yet."""
        jobs = [Job(p) for p in self.cfg.tones]
        if not jobs:
            self.release(ctx)
            return
        stop = threading.Event()
        holder: list[CompareWindow] = []
        self.ui.call(lambda: holder.append(CompareWindow(self.ui, self, ctx, jobs, mode, stop)))

        def refresh() -> None:
            self.ui.call(lambda: holder and holder[0].refresh())

        def run_one(job: Job) -> None:
            job.running = True
            refresh()
            try:
                text = self.llm.complete([{"role": "user", "content": ctx.original}],
                                         f"{job.preset.prompt} {INCOMPATIBLE_RULE}")
            except Exception as exc:
                job.error = str(exc)
            else:
                if text.strip() == INCOMPATIBLE_MARK:
                    job.error = "the text isn't compatible with this request"
                else:
                    job.text = text.strip()
            job.running = False
            job.done = True
            refresh()

        if self.cfg.provider == "ollama":
            def one_by_one() -> None:
                for job in jobs:
                    if stop.is_set():
                        break
                    run_one(job)

            threading.Thread(target=one_by_one, daemon=True).start()
        else:  # cloud servers answer in parallel
            for job in jobs:
                threading.Thread(target=run_one, args=(job,), daemon=True).start()

    # -- UI thread helpers ------------------------------------------------------
    def show_popup(self, ctx: Context) -> None:
        PopupWindow(self.ui, self, ctx)

    def show_menu(self, ctx: Context) -> None:
        menu = tk.Menu(self.ui.root, tearoff=0)
        for preset in self.cfg.presets:
            menu.add_command(label=f"{preset.index}. {preset.name}", command=lambda p=preset: self.run_preset(p, ctx))
        menu.bind("<Unmap>", lambda e: self.ui.root.after(300, lambda: self._menu_closed(ctx)))
        x, y = self.ui.root.winfo_pointerxy()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _menu_closed(self, ctx: Context) -> None:
        if not ctx.taken:  # closed without choosing
            ctx.taken = True
            self.release(ctx)

    def show_settings(self) -> None:
        SettingsWindow(self.ui, self, self.on_restart)

    # -- tray actions -------------------------------------------------------------
    def toggle_pause(self) -> bool:
        self.hk.set_paused(not self.hk.paused)
        return self.hk.paused

    @staticmethod
    def startup_enabled() -> bool:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, "TextFixer")
            return True
        except Exception:
            return False

    @staticmethod
    def relaunch_command(extra: list[str] | None = None) -> tuple[list[str], str | None]:
        """Command (and working folder) that starts this app again, as .exe or from source."""
        args = [*sys.argv[1:], *(extra or [])]
        if getattr(sys, "frozen", False):
            return [sys.executable, *args], None
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return [sys.executable, os.path.join(root, "run_textfixer.py"), *args], root

    def toggle_startup(self, config_path: str) -> bool:
        """Add/remove TextFixer from the Windows Run key. Returns the new state."""
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if self.startup_enabled():
                winreg.DeleteValue(key, "TextFixer")
                return False
            if getattr(sys, "frozen", False):
                command = f'"{sys.executable}" --config "{config_path}"'
            else:
                pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                exe = pythonw if os.path.exists(pythonw) else sys.executable
                script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run_textfixer.py")
                command = f'"{exe}" "{script}" --config "{config_path}"'
            winreg.SetValueEx(key, "TextFixer", 0, winreg.REG_SZ, command)
            return True

    def restart(self) -> None:
        """Start a fresh copy (settings changed) and close this one."""
        self.hk.stop()
        command, cwd = self.relaunch_command()
        subprocess.Popen(command, cwd=cwd)
        self.ui.call(self.ui.quit)
