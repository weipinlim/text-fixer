"""User interface (CustomTkinter: rounded, modern, light/dark like Windows).

Everything here runs in the UI thread; other threads use Ui.call()."""

from __future__ import annotations

import gc
import logging
import queue
import re
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from .config import FOLLOWUP_SYSTEM, Config, Preset
from .markdown_tk import MarkdownView

log = logging.getLogger("textfixer.ui")

# Colours as (light, dark) pairs; CustomTkinter picks the one for the current mode
ACCENT = ("#2563eb", "#3b82f6")
ACCENT_HOVER = ("#1d4ed8", "#2563eb")
CARD = ("gray98", "gray16")
CARD_BORDER = ("gray85", "gray25")
CHIP = ("gray90", "gray22")
CHIP_HOVER = ("#dbeafe", "#1e3a8a")
MUTED = ("gray40", "gray62")
ERROR = ("#c42b1c", "#ff6b6b")
TEXT_BG = {"light": "#fafafa", "dark": "#292929"}  # gray98 / gray16, for the plain tk Text widgets
KEY = "#010203"  # see-through colour for the rounded corners of borderless windows (Windows)


def is_dark_mode() -> bool:
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def secondary_button(parent, text: str, command, height: int = 34, **kw) -> ctk.CTkButton:
    """A quiet grey button (the blue accent is kept for the main action)."""
    return ctk.CTkButton(parent, text=text, command=command, corner_radius=10, height=height, font=font(),
                         fg_color=CHIP, hover_color=("gray82", "gray30"), text_color=("gray10", "gray92"), **kw)


def accent_button(parent, text: str, command, height: int = 34, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(parent, text=text, command=command, corner_radius=10, height=height,
                         font=font(13, "bold"), fg_color=ACCENT, hover_color=ACCENT_HOVER, **kw)


def rounded_shell(win: tk.Toplevel, radius: int = 16) -> ctk.CTkFrame:
    """For borderless windows (popup, tooltip): a rounded card filling the window. On Windows the
    corners outside the card are made see-through, so the window itself looks rounded."""
    see_through = sys.platform == "win32"
    if see_through:
        win.configure(fg_color=KEY)
        win.attributes("-transparentcolor", KEY)
    card = ctk.CTkFrame(win, corner_radius=radius, fg_color=CARD, border_width=1, border_color=CARD_BORDER,
                        bg_color=KEY if see_through else "transparent")
    card.pack(fill="both", expand=True)
    return card


@dataclass
class Context:
    """The selection a hotkey was pressed on."""
    original: str
    saved: str  # clipboard text from before
    hwnd: int  # window to paste into
    combo: object = None
    taken: bool = False  # set once something used the selection


@dataclass
class Job:
    """One tone's answer to the selected text (for the compare windows)."""
    preset: Preset
    text: str = ""
    error: str = ""
    done: bool = False
    running: bool = False  # the server is working on it now (others may be waiting their turn)


class Ui:
    def __init__(self):
        self.dark = is_dark_mode()
        ctk.set_appearance_mode("dark" if self.dark else "light")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title("TextFixer")
        self._queue: queue.Queue = queue.Queue()
        self._tip: tk.Toplevel | None = None
        self._tip_label: ctk.CTkLabel | None = None
        self._tip_job = None
        self.windows: set = set()  # open popup/compare windows
        # Tk objects must be freed by the UI thread; a cyclic garbage collection started by another
        # thread would crash Python ("Tcl_AsyncDelete"). So collect cycles only from here.
        gc.disable()
        self.root.after(30, self._pump)
        self.root.after(5000, self._collect)

    @property
    def mode(self) -> str:
        return "dark" if self.dark else "light"

    # -- thread plumbing --------------------------------------------------
    def call(self, fn: Callable, *args, **kwargs) -> None:
        """Run fn(*args) in the UI thread (safe from any thread)."""
        self._queue.put((fn, args, kwargs))

    def _pump(self) -> None:
        try:
            while True:
                fn, args, kwargs = self._queue.get_nowait()
                try:
                    fn(*args, **kwargs)
                except Exception:
                    log.exception("UI call failed")
        except queue.Empty:
            pass
        self.root.after(30, self._pump)

    def _collect(self) -> None:
        gc.collect()
        self.root.after(5000, self._collect)

    def reset(self) -> None:
        """Close every window and tooltip (used by tests)."""
        self.hide_tip()
        for child in list(self.root.winfo_children()):
            if isinstance(child, tk.Toplevel):
                child.destroy()
        self.windows.clear()
        gc.collect()

    def run(self) -> None:
        self.root.mainloop()

    def quit(self) -> None:
        self.root.quit()

    # -- helpers ---------------------------------------------------------------
    def place_near_cursor(self, win: tk.Toplevel) -> None:
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        mx, my = self.root.winfo_pointerxy()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(0, min(mx + 10, sw - w))
        y = my + 20 if my + 20 + h <= sh else max(0, my - 10 - h)
        win.geometry(f"+{x}+{y}")

    def track(self, win: tk.Toplevel) -> None:
        """Register a modal window: hotkeys are passed through to the app while one is open."""
        self.windows.add(win)
        win.bind("<Destroy>", lambda e=None, w=win: self.windows.discard(w) if e is not None and e.widget is w else None, add="+")

    def error(self, message: str, title: str = "TextFixer") -> None:
        messagebox.showerror(title, message)

    def info(self, message: str, title: str = "TextFixer") -> None:
        messagebox.showinfo(title, message)

    # -- tooltip ---------------------------------------------------------------
    def show_tip(self, text: str, seconds: float = 0, wrap: int = 520) -> None:
        self.hide_tip()
        tip = ctk.CTkToplevel(self.root)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        card = rounded_shell(tip, radius=12)
        text = re.sub(r"(\*\*|__|`)", "", text)  # tooltips are plain text: drop Markdown markers
        label = ctk.CTkLabel(card, text=text, justify="left", wraplength=wrap, font=font(13), anchor="w")
        label.pack(padx=14, pady=10)
        label.bind("<Button-1>", lambda *_e: self.hide_tip())
        self.place_near_cursor(tip)
        tip.deiconify()
        self._tip, self._tip_label = tip, label
        if seconds:
            self._tip_job = self.root.after(int(seconds * 1000), self.hide_tip)

    def tip_text(self) -> str:
        return self._tip_label.cget("text") if self._tip is not None and self._tip_label is not None else ""

    def hide_tip(self) -> None:
        if self._tip_job:
            self.root.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = self._tip_label = None


def _text_view(parent, ui: Ui, height: int = 20) -> tuple[tk.Text, MarkdownView]:
    """A rounded card holding a read-only text area with a slim scrollbar."""
    card = ctk.CTkFrame(parent, corner_radius=14, fg_color=CARD, border_width=1, border_color=CARD_BORDER)
    card.pack(fill="both", expand=True, padx=16, pady=(16, 10))
    text = tk.Text(card, height=height, state="disabled")
    bar = ctk.CTkScrollbar(card, command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y", padx=(0, 4), pady=8)
    text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
    return text, MarkdownView(text, ui.dark, bg=TEXT_BG[ui.mode], family="Segoe UI")


# ---------------------------------------------------------------------------
# Result / chat window
# ---------------------------------------------------------------------------

class ResultWindow(ctk.CTkToplevel):
    """Shows an answer (Markdown) and lets you ask follow-up questions."""

    def __init__(self, ui: Ui, app, title: str, system: str = "", original: str = ""):
        super().__init__(ui.root)
        self.ui, self.app = ui, app
        self.title(f"TextFixer - {title}")
        self.geometry("820x580")
        self.minsize(520, 360)
        self.items: list[tuple[str, str]] = []   # (role, text) as displayed
        self.history: list[dict] = []            # what is sent to the LLM
        self.waiting = False

        ctk.CTkLabel(self, text=title, font=font(20, "bold")).pack(anchor="w", padx=20, pady=(16, 0))
        self.text, self.view = _text_view(self, ui, 18)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 16))
        self.entry = ctk.CTkEntry(bottom, height=36, corner_radius=10, font=font(),
                                  placeholder_text="Ask a follow-up question...")
        self.entry.pack(side="left", fill="x", expand=True)
        self.send_btn = accent_button(bottom, "Send", self.send, width=80)
        self.send_btn.pack(side="left", padx=(8, 0))
        secondary_button(bottom, "Copy last answer", self.copy_last).pack(side="left", padx=(8, 0))
        secondary_button(bottom, "Close", self.destroy, width=80).pack(side="left", padx=(8, 0))
        self.entry.bind("<Return>", lambda *_e: self.send())
        self.bind("<Escape>", lambda *_e: self.destroy())
        self.after(150, self.entry.focus_set)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        if original:
            self.history.append({"role": "user", "content": original})
            self.ask(system)
        else:
            self.render()

    def ask(self, system: str) -> None:
        self.waiting = True
        self.send_btn.configure(state="disabled")
        self.render()
        self.app.llm.complete_async(list(self.history), system,
                                    lambda text, err: self.ui.call(self._answer, text, err))

    def _answer(self, text, err) -> None:
        if not self.winfo_exists():
            return
        self.waiting = False
        if err is not None:
            self.items.append(("error", str(err)))
        else:
            self.history.append({"role": "assistant", "content": text})
            self.items.append(("assistant", text.strip()))
        self.send_btn.configure(state="normal")
        self.render()

    def send(self) -> None:
        question = self.entry.get().strip()
        if not question or self.waiting:
            return
        self.entry.delete(0, "end")
        self.history.append({"role": "user", "content": question})
        self.items.append(("user", question))
        self.ask(FOLLOWUP_SYSTEM)

    def render(self) -> None:
        self.view.clear()
        for role, text in self.items:
            if role == "assistant":
                self.view.add_markdown(text)
            else:
                self.view.add_plain(text, "user" if role == "user" else "error")
        if self.waiting:
            self.view.add_plain("Thinking...", "dim")
        self.text.see("end")

    def copy_last(self) -> None:
        for role, text in reversed(self.items):
            if role == "assistant":
                self.clipboard_clear()
                self.clipboard_append(text)
                return


# ---------------------------------------------------------------------------
# Popup at the cursor: "describe your change" box, a button per tone, compare and explain
# ---------------------------------------------------------------------------

class PopupWindow(ctk.CTkToplevel):
    def __init__(self, ui: Ui, app, ctx: Context):
        super().__init__(ui.root)
        self.ui, self.app, self.ctx = ui, app, ctx
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        card = rounded_shell(self, radius=16)
        ctk.CTkLabel(card, text="Describe a change and press Enter, or pick a tone", font=font(12),
                     text_color=MUTED, anchor="w").pack(fill="x", padx=18, pady=(12, 0))
        self.entry = ctk.CTkEntry(card, height=40, corner_radius=12, font=font(14), width=560,
                                  placeholder_text="e.g. translate to French, make it shorter...")
        self.entry.pack(fill="x", padx=16, pady=(4, 10))

        chips = ctk.CTkFrame(card, fg_color="transparent")
        chips.pack(fill="x", padx=12)
        for i, preset in enumerate(app.cfg.presets):
            ctk.CTkButton(chips, text=preset.name, width=134, height=34, corner_radius=17, font=font(),
                          fg_color=CHIP, hover_color=CHIP_HOVER, text_color=("gray10", "gray92"),
                          command=lambda p=preset: self.pick(p)).grid(row=i // 4, column=i % 4, padx=4, pady=4)

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(8, 14))
        ctk.CTkButton(actions, text="Compare all", width=134, height=34, corner_radius=17, font=font(),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=lambda: self.compare("tabs")).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Compare as list", width=134, height=34, corner_radius=17, font=font(),
                      fg_color=CHIP, hover_color=CHIP_HOVER, text_color=("gray10", "gray92"),
                      command=lambda: self.compare("list")).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Explain", width=134, height=34, corner_radius=17, font=font(),
                      fg_color=CHIP, hover_color=CHIP_HOVER, text_color=("gray10", "gray92"),
                      command=self.explain).pack(side="left", padx=4)
        ctk.CTkLabel(actions, text="Esc to close", font=font(12), text_color=MUTED).pack(side="right", padx=6)

        self.entry.bind("<Return>", lambda *_e: self.send())
        self.bind("<Escape>", lambda *_e: self.close())
        self.ui.place_near_cursor(self)
        self.deiconify()
        self.after(60, self._focus)
        self.after(500, self._watch)
        self.ui.track(self)

    def _focus(self) -> None:
        self.focus_force()
        self.entry.focus_set()

    def _watch(self) -> None:
        """Close when you click somewhere else."""
        if not self.winfo_exists():
            return
        focus = self.focus_displayof()
        if focus is None or focus.winfo_toplevel() is not self:
            self.close()
        else:
            self.after(150, self._watch)

    def close(self) -> None:
        if self.winfo_exists():
            self.destroy()
        if not self.ctx.taken:
            self.ctx.taken = True
            self.app.release(self.ctx)

    def _take(self) -> None:
        self.ctx.taken = True
        self.destroy()

    def pick(self, preset: Preset) -> None:
        self._take()
        self.app.run_preset(preset, self.ctx)

    def send(self) -> None:
        instruction = self.entry.get().strip()
        if not instruction:
            return
        self._take()
        self.app.run_custom(instruction, self.ctx)

    def compare(self, mode: str) -> None:
        self._take()
        threading.Thread(target=self.app.compare, args=(self.ctx, mode), daemon=True).start()

    def explain(self) -> None:
        self._take()
        threading.Thread(target=self.app.explain, args=(self.ctx,), daemon=True).start()


# ---------------------------------------------------------------------------
# Compare windows: every tone's answer, as tabs or as a list with hover text
# ---------------------------------------------------------------------------

class CompareWindow(ctk.CTkToplevel):
    def __init__(self, ui: Ui, app, ctx: Context, jobs: list[Job], mode: str, stop=None):
        super().__init__(ui.root)
        self.ui, self.app, self.ctx, self.jobs, self.mode = ui, app, ctx, jobs, mode
        self.stop = stop  # threading.Event: set when the window closes, so no more answers are asked for
        self.selected = 0
        self.user_picked_tab = False
        self.withdraw()
        self.title("TextFixer - pick a version" if mode == "tabs" else "TextFixer - click one to use it")
        self.attributes("-topmost", True)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=14)
        self.rows: list[ctk.CTkLabel] = []
        if mode == "tabs":
            bar = ctk.CTkFrame(body, fg_color="transparent")
            bar.pack(fill="x")
            self.tabs = []
            for i, job in enumerate(jobs):
                b = ctk.CTkButton(bar, text=job.preset.name, width=118, height=32, corner_radius=16, font=font(),
                                  command=lambda i=i: self.select(i))
                b.pack(side="left", padx=3)
                self.tabs.append(b)
            self.box = ctk.CTkTextbox(body, width=660, height=170, corner_radius=12, font=font(13), wrap="word",
                                      fg_color=CARD, border_width=1, border_color=CARD_BORDER)
            self.box.pack(fill="both", expand=True, pady=10)
            buttons = ctk.CTkFrame(body, fg_color="transparent")
            buttons.pack(fill="x")
            self.use_btn = accent_button(buttons, "Use this", lambda: self.use(self.selected), width=110)
            self.use_btn.pack(side="left")
            secondary_button(buttons, "Cancel", self.close, width=90).pack(side="left", padx=8)
            self.bind("<Return>", lambda *_e: self.use(self.selected))
        else:
            for i, job in enumerate(jobs):
                row = ctk.CTkFrame(body, corner_radius=12, fg_color=CARD, border_width=1, border_color=CARD_BORDER)
                row.pack(fill="x", pady=3)
                ctk.CTkLabel(row, text=job.preset.name, width=110, anchor="w", font=font(13, "bold")).pack(
                    side="left", padx=(12, 6), pady=8)
                label = ctk.CTkLabel(row, text="Waiting for its turn...", width=480, anchor="w", font=font(),
                                     cursor="hand2")
                label.pack(side="left", padx=(0, 12), pady=8)
                for widget in (row, label):
                    widget.bind("<Button-1>", lambda *_e, i=i: self.use(i))
                    widget.bind("<Enter>", lambda *_e, i=i: self.hover(i))
                    widget.bind("<Leave>", lambda *_e: self.ui.hide_tip())
                self.rows.append(label)
            footer = ctk.CTkFrame(body, fg_color="transparent")
            footer.pack(fill="x", pady=(6, 0))
            secondary_button(footer, "Cancel", self.close, width=90).pack(side="left")
        self.progress = ctk.CTkLabel(body, text="", font=font(12), text_color=MUTED, anchor="w")
        self.progress.pack(fill="x", pady=(6, 0))
        for n in range(1, 10):
            self.bind(str(n), lambda *_e, n=n: self.key(n - 1))
        self.bind("<Escape>", lambda *_e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.ui.place_near_cursor(self)
        self.deiconify()
        self.after(60, self.focus_force)
        self.ui.track(self)
        self.refresh()

    @staticmethod
    def _state(job: Job) -> str:
        return "Working..." if job.running else "Waiting for its turn..."

    def refresh(self) -> None:
        if not self.winfo_exists():
            return
        ready, total = sum(1 for j in self.jobs if j.done), len(self.jobs)
        if ready == total:
            progress = f"All {total} ready"
        elif ready == 0:
            progress = f"Writing the first of {total} versions..."
        else:
            progress = f"{ready} of {total} ready - you can pick a finished one now"
        self.progress.configure(text=progress)
        if self.mode == "tabs":
            # Until you pick a tab yourself, show the first finished answer
            if not self.user_picked_tab and not self.jobs[self.selected].done:
                self.selected = next((i for i, j in enumerate(self.jobs) if j.done and not j.error), self.selected)
            for i, (b, job) in enumerate(zip(self.tabs, self.jobs)):
                on = i == self.selected
                b.configure(fg_color=ACCENT if on else CHIP, hover_color=ACCENT_HOVER if on else CHIP_HOVER,
                            text_color=("white", "white") if on else ("gray10", "gray92"))
            job = self.jobs[self.selected]
            text = f"Error: {job.error}" if job.error else (job.text if job.done else self._state(job))
            self.box.configure(state="normal")
            self.box.delete("1.0", "end")
            self.box.insert("end", text)
            self.box.configure(state="disabled")
            self.use_btn.configure(state="normal" if job.done and not job.error else "disabled")
        else:
            for label, job in zip(self.rows, self.jobs):
                if job.error:
                    label.configure(text=f"Error: {_one_line(job.error)}")
                elif job.done:
                    label.configure(text=_one_line(job.text))
                else:
                    label.configure(text=self._state(job))

    def select(self, i: int) -> None:
        self.selected = i
        self.user_picked_tab = True
        self.refresh()

    def key(self, i: int) -> None:
        if i < len(self.jobs):
            self.use(i) if self.mode == "list" else self.select(i)

    def hover(self, i: int) -> None:
        job = self.jobs[i]
        full = f"Error: {job.error}" if job.error else job.text
        if full:
            self.ui.show_tip(full, wrap=520)

    def use(self, i: int) -> None:
        job = self.jobs[i]
        if not job.done or job.error:
            return
        self.ui.hide_tip()
        self.ctx.taken = True
        if self.stop:
            self.stop.set()
        self.destroy()
        self.app.deliver(job.text, self.ctx)

    def close(self) -> None:
        self.ui.hide_tip()
        if self.stop:
            self.stop.set()
        if self.winfo_exists():
            self.destroy()
        if not self.ctx.taken:
            self.ctx.taken = True
            self.app.release(self.ctx)


def _one_line(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Settings window layout: (key, label) per tab. Hotkey keys end in _HOTKEY.
MODEL_FIELDS = [
    ("API_URL", "Server address"),
    ("API_KEY", "API key"),
    ("KEEP_ALIVE", "Keep model loaded for"),
]
SHORTCUT_FIELDS = [
    ("POPUP_HOTKEY", "Popup (everything)"),
    ("CHAT_HOTKEY", "Chat window"),
    ("DEFAULT_HOTKEY", "Default tone"),
    ("MENU_HOTKEY", "Tone menu"),
    ("PREVIEW_HOTKEY", "Compare all (tabs)"),
    ("RESULTS_MENU_HOTKEY", "Compare all (list)"),
    ("EXPLAIN_HOTKEY", "Explain word"),
]
ADVANCED_FIELDS = [
    ("EXCLUDE_APPS", "Shortcuts off in these apps"),
    ("TEMPERATURE", "Temperature"),
    ("TIMEOUT", "Timeout (seconds)"),
    ("SELECTION_WAIT_MS", "Wait for the selection (ms)"),
]
SETTINGS_FIELDS = MODEL_FIELDS + SHORTCUT_FIELDS + ADVANCED_FIELDS
PROVIDERS = {"ollama": "Ollama", "openai": "OpenAI-compatible", "gemini": "Gemini"}


class _Overlay:
    """A Config with a few values replaced (what is typed in the settings window)."""

    def __init__(self, cfg: Config, **overrides: str):
        self._cfg, self._over = cfg, overrides

    @property
    def provider(self) -> str:
        return self._over.get("PROVIDER", self._cfg.provider)

    def setting(self, key: str) -> str:
        return self._over[key] if key in self._over else self._cfg.setting(key)

    def number(self, key: str, default: float) -> float:
        try:
            return float(self.setting(key))
        except ValueError:
            return default


class SettingsWindow(ctk.CTkToplevel):
    """Settings, in three tabs (Model, Shortcuts, Advanced). Saving writes config.ini and restarts."""

    def __init__(self, ui: Ui, app, on_saved: Callable[[], None]):
        super().__init__(ui.root)
        self.ui, self.app, self.cfg, self.on_saved = ui, app, app.cfg, on_saved
        self.title("TextFixer Settings")
        self.resizable(False, False)
        self.vars: dict[str, tk.StringVar] = {}

        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=24, pady=(18, 20))
        ctk.CTkLabel(outer, text="Settings", font=font(24, "bold")).pack(anchor="w")
        ctk.CTkLabel(outer, text="Changes take effect when you save (TextFixer restarts).", font=font(),
                     text_color=MUTED).pack(anchor="w", pady=(0, 6))

        tabs = ctk.CTkTabview(outer, width=700, height=440, corner_radius=14,
                              segmented_button_selected_color=ACCENT,
                              segmented_button_selected_hover_color=ACCENT_HOVER)
        tabs.pack(fill="both", expand=True)
        for name in ("Model", "Shortcuts", "Advanced"):
            tabs.add(name)
        self._model_tab(tabs.tab("Model"))
        self._shortcuts_tab(tabs.tab("Shortcuts"))
        self._advanced_tab(tabs.tab("Advanced"))

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(fill="x", pady=(14, 0))
        self.error_label = ctk.CTkLabel(footer, text="", text_color=ERROR, font=font(12), wraplength=430,
                                        justify="left", anchor="w")
        self.error_label.pack(side="left", fill="x", expand=True)
        accent_button(footer, "Save and restart", self.save, width=150, height=38).pack(side="right")
        secondary_button(footer, "Cancel", self.destroy, width=100, height=38).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda *_e: self.destroy())
        self.after(100, self.lift)
        self.refresh_models()

    # -- layout helpers ------------------------------------------------------------
    @staticmethod
    def _card(parent, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, corner_radius=12, fg_color=CARD, border_width=1, border_color=CARD_BORDER)
        card.pack(fill="x", padx=4, pady=6)
        ctk.CTkLabel(card, text=title, font=font(15, "bold")).grid(row=0, column=0, columnspan=4, sticky="w",
                                                                   padx=16, pady=(12, 4))
        return card

    @staticmethod
    def _label(parent, text: str, row: int, column: int = 0, padx=(16, 12)) -> None:
        ctk.CTkLabel(parent, text=text, font=font(), anchor="w").grid(row=row, column=column, sticky="w",
                                                                      padx=padx, pady=4)

    def _entry(self, parent, key: str, row: int, width: int = 360, column: int = 1, padx=(0, 16)) -> None:
        var = self.vars.setdefault(key, tk.StringVar(value=self.cfg.setting(key)))
        ctk.CTkEntry(parent, textvariable=var, width=width, height=34, corner_radius=10, font=font(),
                     show="•" if key == "API_KEY" else "").grid(row=row, column=column, sticky="w",
                                                                    padx=padx, pady=6)

    def _hint(self, parent, text: str) -> None:
        ctk.CTkLabel(parent, text=text, font=font(12), text_color=MUTED, justify="left", anchor="w").pack(
            fill="x", padx=8, pady=(6, 0))

    def _pairs(self, card, items: list[tuple[str, tk.StringVar]], start_row: int = 1) -> None:
        """Label + entry pairs in two columns."""
        per_column = (len(items) + 1) // 2
        for i, (label, var) in enumerate(items):
            r, c = start_row + i % per_column, (i // per_column) * 2
            self._label(card, label, r, c, padx=(16 if c == 0 else 8, 10))
            ctk.CTkEntry(card, textvariable=var, width=150, height=30, corner_radius=10, font=font(),
                         placeholder_text="none").grid(row=r, column=c + 1, sticky="w", padx=(0, 16), pady=3)

    # -- tabs -------------------------------------------------------------------------
    def _model_tab(self, tab) -> None:
        card = self._card(tab, "AI model")
        self._label(card, "Provider", 1)
        self.provider = tk.StringVar(value=self.cfg.provider if self.cfg.provider in PROVIDERS else "ollama")
        self._provider_label = tk.StringVar(value=PROVIDERS[self.provider.get()])
        labels_to_keys = {v: k for k, v in PROVIDERS.items()}
        ctk.CTkSegmentedButton(card, values=list(PROVIDERS.values()), variable=self._provider_label,
                               corner_radius=10, font=font(), selected_color=ACCENT,
                               selected_hover_color=ACCENT_HOVER,
                               command=lambda label: self.provider.set(labels_to_keys[label])).grid(
            row=1, column=1, columnspan=3, sticky="w", pady=6)
        self.provider.trace_add("write", lambda *a: self._provider_label.set(PROVIDERS.get(self.provider.get(), "")))

        self._label(card, "Model", 2)
        self.model = tk.StringVar(value=self.cfg.setting("MODEL"))
        self.model_box = ctk.CTkComboBox(card, variable=self.model, values=[], width=240, height=34,
                                         corner_radius=10, font=font(), dropdown_font=font())
        self.model_box.grid(row=2, column=1, sticky="w", pady=6)
        secondary_button(card, "Refresh", self.refresh_models, width=84).grid(row=2, column=2, padx=(8, 0), pady=6)
        accent_button(card, "Download", self.download, width=96).grid(row=2, column=3, padx=(8, 16), pady=6)
        self.status = ctk.CTkLabel(card, text="", font=font(12), text_color=MUTED, anchor="w")
        self.status.grid(row=3, column=1, columnspan=3, sticky="w", pady=(0, 12))

        card = self._card(tab, "Connection")
        for row, (key, label) in enumerate(MODEL_FIELDS, start=1):
            self._label(card, label, row)
            self._entry(card, key, row, width=360 if key != "KEEP_ALIVE" else 120)
        self.vars["THINK"] = tk.StringVar(value="on" if self.cfg.setting("THINK").lower() in ("on", "true", "yes", "1")
                                          else "off")
        ctk.CTkSwitch(card, text='Let "thinking" models reason before answering (much slower)', font=font(),
                      variable=self.vars["THINK"], onvalue="on", offvalue="off", progress_color=ACCENT).grid(
            row=len(MODEL_FIELDS) + 1, column=0, columnspan=4, sticky="w", padx=16, pady=(6, 14))
        self._hint(tab, "Ollama on this PC: leave the server address empty. Another PC: http://address:11434.\n"
                        "OpenAI-compatible: the .../v1/chat/completions address. Gemini: only the API key.")

    def _shortcuts_tab(self, tab) -> None:
        card = self._card(tab, "Tones")
        self.tone_vars: dict[int, tk.StringVar] = {p.index: tk.StringVar(value=p.hotkey) for p in self.cfg.presets}
        self._pairs(card, [(f"{p.index}  {p.name}", self.tone_vars[p.index]) for p in self.cfg.presets])
        rows = (len(self.cfg.presets) + 1) // 2
        secondary_button(card, "Use Ctrl+Shift+F1 … F8", self.use_function_keys, height=28).grid(
            row=0, column=2, columnspan=2, sticky="e", padx=16, pady=(10, 2))
        ctk.CTkLabel(card, text="", height=4).grid(row=rows + 1, column=0)

        card = self._card(tab, "Other shortcuts")
        for key, _ in SHORTCUT_FIELDS:
            self.vars[key] = tk.StringVar(value=self.cfg.setting(key))
        self._pairs(card, [(label, self.vars[key]) for key, label in SHORTCUT_FIELDS])
        ctk.CTkLabel(card, text="", height=6).grid(row=20, column=0)
        self._hint(tab, "Keyboard only: ^ Ctrl, ! Alt, + Shift, # Win, then a key (e.g. ^+F1, ^!E). "
                        "Empty = off; the popup can do everything.")

    def _advanced_tab(self, tab) -> None:
        card = self._card(tab, "Advanced")
        for row, (key, label) in enumerate(ADVANCED_FIELDS, start=1):
            self._label(card, label, row)
            self._entry(card, key, row, width=300 if key == "EXCLUDE_APPS" else 120)
        secondary_button(card, "Open config.ini", self.open_file).grid(row=len(ADVANCED_FIELDS) + 1, column=0,
                                                                       sticky="w", padx=16, pady=(8, 14))
        self._hint(tab, "Apps: process names separated by commas, e.g. EXCEL.EXE, Code.exe. "
                        "Tones and their prompts are edited in config.ini.")

    # -- models ----------------------------------------------------------------------
    def _current_llm(self):
        """An LLM client using what is typed in the window (nothing is saved or changed)."""
        from .llm import LLMClient

        return LLMClient(_Overlay(self.cfg, PROVIDER=self.provider.get(), MODEL=self.model.get().strip(),
                                  API_URL=self.vars["API_URL"].get().strip(), API_KEY=self.vars["API_KEY"].get().strip()))

    def refresh_models(self) -> None:
        """Fill the model list from Ollama (in a thread: Ollama may be off)."""
        self.status.configure(text="Looking for installed models...")
        llm = self._current_llm()
        self._refresh_id = getattr(self, "_refresh_id", 0) + 1
        mine = self._refresh_id

        def work():
            try:
                names, error = llm.list_models(), ""
            except Exception:
                names, error = [], "Cannot reach Ollama. Is it running? Start it, then click Refresh."
            self.ui.call(self._models_found, names, error, mine)

        threading.Thread(target=work, daemon=True).start()

    def _models_found(self, names: list[str], error: str, request_id: int) -> None:
        if not self.winfo_exists() or request_id != self._refresh_id:  # closed, or a newer refresh is running
            return
        self.model_box.configure(values=names)
        self.status.configure(text=error or (f"● {len(names)} model(s) installed in Ollama" if names else
                                             "No models installed yet: type a name and click Download"))

    def download(self) -> None:
        name = self.model.get().strip()
        if not name:
            return
        PullWindow(self.ui, self._current_llm(), name, on_done=self.refresh_models)

    # -- shortcuts ------------------------------------------------------------------
    def use_function_keys(self) -> None:
        for n, (index, var) in enumerate(sorted(self.tone_vars.items()), start=1):
            var.set(f"^+F{n}")

    def open_file(self) -> None:
        import os
        import subprocess

        if sys.platform == "win32":
            os.startfile(str(self.cfg.path))  # noqa: S606 - opens it in the user's editor
        else:
            subprocess.Popen(["xdg-open", str(self.cfg.path)])

    def check_hotkeys(self, settings: dict[str, str]) -> list[str]:
        """Problems with the typed shortcuts: unknown keys, mouse buttons, the same keys twice."""
        from .hotkeys import parse_hotkey

        entries = [(label, settings[key]) for key, label in SHORTCUT_FIELDS]
        names = {p.index: f"{p.index} {p.name}" for p in self.cfg.presets}
        entries += [(names[i], var.get().strip()) for i, var in sorted(self.tone_vars.items())]
        problems, seen = [], {}
        for label, spec in entries:
            if not spec:
                continue
            try:
                combo = parse_hotkey(spec)
            except ValueError:
                problems.append(f"{label}: '{spec}' is not a key combination TextFixer knows")
                continue
            if combo.is_mouse:
                problems.append(f"{label}: '{spec}' is a mouse button; use a key")
                continue
            key = (combo.mods, combo.key)
            if key in seen:
                problems.append(f"{label} and {seen[key]} both use {combo.describe()}")
            else:
                seen[key] = label
        return problems

    def save(self) -> None:
        settings = {"PROVIDER": self.provider.get(), "MODEL": self.model.get().strip()}
        for key, var in self.vars.items():
            settings[key] = var.get().strip()
        problems = self.check_hotkeys(settings)
        if problems:
            self.error_label.configure(text="Please fix: " + "; ".join(problems))
            return
        self.cfg.update("Settings", settings)
        for index, var in self.tone_vars.items():
            self.cfg.update(f"Preset{index}", {"HOTKEY": var.get().strip()})
        self.destroy()
        self.on_saved()


class PullWindow(ctk.CTkToplevel):
    """Downloads an Ollama model and shows the progress."""

    def __init__(self, ui: Ui, llm, name: str, on_done: Callable[[], None] | None = None):
        super().__init__(ui.root)
        self.ui, self.llm, self.name, self.on_done = ui, llm, name, on_done
        self.title(f"Downloading {name}")
        self.resizable(False, False)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=18)
        ctk.CTkLabel(body, text=f"Downloading {name}", font=font(16, "bold"), anchor="w").pack(fill="x")
        self.status = ctk.CTkLabel(body, text="Starting...", width=420, anchor="w", font=font(), text_color=MUTED)
        self.status.pack(fill="x", pady=(4, 10))
        self.bar = ctk.CTkProgressBar(body, width=420, height=10, corner_radius=5, progress_color=ACCENT)
        self.bar.set(0)
        self.bar.pack(fill="x")
        self.close = secondary_button(body, "Close", self.destroy, width=90)
        self.close.configure(state="disabled")
        self.close.pack(anchor="e", pady=(14, 0))
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # let the download finish
        threading.Thread(target=self.work, daemon=True).start()

    def work(self) -> None:
        try:
            for status, fraction in self.llm.pull_model(self.name):
                self.ui.call(self.progress, status, fraction)
            self.ui.call(self.finish, f"Done: '{self.name}' is installed.")
        except Exception as exc:
            self.ui.call(self.finish, f"Failed: {exc}")

    def progress(self, status: str, fraction: float | None) -> None:
        if not self.winfo_exists():
            return
        self.status.configure(text=status if fraction is None else f"{status}  {fraction:.0%}")
        if fraction is not None:
            self.bar.set(fraction)

    def finish(self, message: str) -> None:
        if not self.winfo_exists():
            return
        self.status.configure(text=message)
        self.close.configure(state="normal")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        if message.startswith("Done"):
            self.bar.set(1)
            if self.on_done:
                self.on_done()
