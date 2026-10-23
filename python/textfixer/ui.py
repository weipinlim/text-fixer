"""tkinter user interface. Everything here runs in the UI thread; other threads use Ui.call()."""

from __future__ import annotations

import gc
import logging
import queue
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox
from typing import Callable

from .config import FOLLOWUP_SYSTEM, INCOMPATIBLE_MARK, INCOMPATIBLE_RULE, Config, Preset
from .markdown_tk import MarkdownView

log = logging.getLogger("textfixer.ui")


def is_dark_mode() -> bool:
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


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


class Ui:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("TextFixer")
        self.dark = is_dark_mode()
        self._queue: queue.Queue = queue.Queue()
        self._tip: tk.Toplevel | None = None
        self._tip_job = None
        self.windows: set = set()  # open popup/compare windows
        # Tk objects must be freed by the UI thread; a cyclic garbage collection started by another
        # thread would crash Python ("Tcl_AsyncDelete"). So collect cycles only from here.
        gc.disable()
        self.root.after(30, self._pump)
        self.root.after(5000, self._collect)

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
        win.bind("<Destroy>", lambda e, w=win: self.windows.discard(w) if e.widget is w else None, add="+")

    def error(self, message: str, title: str = "TextFixer") -> None:
        messagebox.showerror(title, message)

    def info(self, message: str, title: str = "TextFixer") -> None:
        messagebox.showinfo(title, message)

    # -- tooltip ---------------------------------------------------------------
    def show_tip(self, text: str, seconds: float = 0, wrap: int = 520, dismiss: Callable | None = None) -> None:
        self.hide_tip()
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        bg, fg = ("#2b2b2b", "#f0f0f0") if self.dark else ("#ffffe1", "#202020")
        label = tk.Label(tip, text=text, justify="left", wraplength=wrap, bg=bg, fg=fg, bd=1, relief="solid",
                         padx=8, pady=6)
        label.pack()
        label.bind("<Button-1>", lambda e: self.hide_tip())
        self.place_near_cursor(tip)
        self._tip = tip
        if seconds:
            self._tip_job = self.root.after(int(seconds * 1000), self.hide_tip)

    def hide_tip(self) -> None:
        if self._tip_job:
            self.root.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def _text_view(parent, ui: Ui, height: int = 20, width: int = 90) -> tuple[tk.Text, MarkdownView]:
    frame = tk.Frame(parent)
    text = tk.Text(frame, height=height, width=width, state="disabled", relief="solid", bd=1)
    bar = tk.Scrollbar(frame, command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    frame.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    return text, MarkdownView(text, ui.dark)


# ---------------------------------------------------------------------------
# Result / chat window
# ---------------------------------------------------------------------------

class ResultWindow(tk.Toplevel):
    """Shows an answer (Markdown) and lets you ask follow-up questions."""

    def __init__(self, ui: Ui, app, title: str, system: str = "", original: str = ""):
        super().__init__(ui.root)
        self.ui, self.app = ui, app
        self.title(f"TextFixer - {title}")
        self.geometry("820x560")
        self.items: list[tuple[str, str]] = []   # (role, text) as displayed
        self.history: list[dict] = []            # what is sent to the LLM
        self.waiting = False
        self.text, self.view = _text_view(self, ui, 22)

        bottom = tk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        self.entry = tk.Entry(bottom)
        self.entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.send_btn = tk.Button(bottom, text="Send", width=9, command=self.send)
        self.send_btn.pack(side="left", padx=(6, 0))
        tk.Button(bottom, text="Copy last answer", command=self.copy_last).pack(side="left", padx=(12, 0))
        tk.Button(bottom, text="Close", width=8, command=self.destroy).pack(side="left", padx=(6, 0))
        self.entry.bind("<Return>", lambda e: self.send())
        self.bind("<Escape>", lambda e: self.destroy())
        self.entry.focus_set()
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
# Popup at the cursor: "describe your change" box plus a button per tone
# ---------------------------------------------------------------------------

class PopupWindow(tk.Toplevel):
    def __init__(self, ui: Ui, app, ctx: Context):
        super().__init__(ui.root)
        self.ui, self.app, self.ctx = ui, app, ctx
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        body = tk.Frame(self, bd=1, relief="solid", padx=8, pady=8)
        body.pack()
        tk.Label(body, text="Describe a change and press Enter, or pick a tone:", anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="we")
        self.entry = tk.Entry(body, width=58)
        self.entry.grid(row=1, column=0, columnspan=3, sticky="we", pady=(2, 6), ipady=3)
        for i, preset in enumerate(app.cfg.presets):
            tk.Button(body, text=f"{preset.index} {preset.name}", width=20,
                      command=lambda p=preset: self.pick(p)).grid(row=2 + i // 3, column=i % 3, padx=2, pady=2)
        self.entry.bind("<Return>", lambda e: self.send())
        self.bind("<Escape>", lambda e: self.close())
        self.ui.place_near_cursor(self)
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


# ---------------------------------------------------------------------------
# Compare windows: every tone's answer, as tabs or as a list with hover text
# ---------------------------------------------------------------------------

class CompareWindow(tk.Toplevel):
    def __init__(self, ui: Ui, app, ctx: Context, jobs: list[Job], mode: str):
        super().__init__(ui.root)
        self.ui, self.app, self.ctx, self.jobs, self.mode = ui, app, ctx, jobs, mode
        self.selected = 0
        self.title("TextFixer - pick a version" if mode == "tabs" else "TextFixer - click one to use it (hover for the full text)")
        self.attributes("-topmost", True)
        body = tk.Frame(self, padx=8, pady=8)
        body.pack()
        self.rows: list[tk.Label] = []
        if mode == "tabs":
            bar = tk.Frame(body)
            bar.pack(fill="x")
            self.tabs = []
            for i, job in enumerate(jobs):
                b = tk.Button(bar, text=f"{job.preset.index} {job.preset.name}", width=14, command=lambda i=i: self.select(i))
                b.pack(side="left", padx=2)
                self.tabs.append(b)
            self.box = tk.Text(body, height=7, width=84, wrap="word", state="disabled", relief="solid", bd=1)
            self.box.pack(pady=6)
            buttons = tk.Frame(body)
            buttons.pack(fill="x")
            self.use_btn = tk.Button(buttons, text="Use this", width=12, command=lambda: self.use(self.selected))
            self.use_btn.pack(side="left")
            tk.Button(buttons, text="Cancel", width=10, command=self.close).pack(side="left", padx=6)
            self.bind("<Return>", lambda e: self.use(self.selected))
        else:
            for i, job in enumerate(jobs):
                row = tk.Frame(body)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=f"{job.preset.index}. {job.preset.name}", width=16, anchor="w").pack(side="left")
                label = tk.Label(row, text="Working...", width=70, anchor="w", relief="solid", bd=1, padx=4)
                label.pack(side="left")
                label.bind("<Button-1>", lambda e, i=i: self.use(i))
                label.bind("<Enter>", lambda e, i=i: self.hover(i))
                label.bind("<Leave>", lambda e: self.ui.hide_tip())
                self.rows.append(label)
            tk.Button(body, text="Cancel", width=10, command=self.close).pack(anchor="w", pady=(6, 0))
        for n in range(1, 10):
            self.bind(str(n), lambda e, n=n: self.key(n - 1))
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.ui.place_near_cursor(self)
        self.after(60, self.focus_force)
        self.ui.track(self)
        self.refresh()

    def refresh(self) -> None:
        if not self.winfo_exists():
            return
        if self.mode == "tabs":
            for i, (b, job) in enumerate(zip(self.tabs, self.jobs)):
                name = f"{job.preset.index} {job.preset.name}"
                b.configure(text=f"[{name}]" if i == self.selected else name)
            job = self.jobs[self.selected]
            text = f"Error: {job.error}" if job.error else (job.text if job.done else "Working...")
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

    def select(self, i: int) -> None:
        self.selected = i
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
        self.destroy()
        self.app.deliver(job.text, self.ctx)

    def close(self) -> None:
        self.ui.hide_tip()
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

SETTINGS_FIELDS = [  # (section, key, label)
    ("Settings", "API_URL", "API URL"),
    ("Settings", "API_KEY", "API key"),
    ("Settings", "MODEL", "Model"),
    ("Settings", "TEMPERATURE", "Temperature"),
    ("Settings", "TIMEOUT", "Timeout (s)"),
    ("Settings", "EXCLUDE_APPS", "Hotkeys off in"),
    ("Server", "MODEL_DIR", "Local model folder"),
    ("Server", "DEVICE", "Devices (in order)"),
    ("Server", "PORT", "Server port"),
    ("Server", "MAX_PROMPT_LEN", "NPU max prompt tokens"),
    ("Settings", "DEFAULT_HOTKEY", "Default tone"),
    ("Settings", "POPUP_HOTKEY", "Popup"),
    ("Settings", "MENU_HOTKEY", "Tone menu"),
    ("Settings", "PREVIEW_HOTKEY", "All tones (tabs)"),
    ("Settings", "RESULTS_MENU_HOTKEY", "All tones (list)"),
    ("Settings", "EXPLAIN_HOTKEY", "Explain word"),
    ("Settings", "CHAT_HOTKEY", "Chat window"),
]


class SettingsWindow(tk.Toplevel):
    def __init__(self, ui: Ui, cfg: Config, on_saved: Callable[[], None]):
        super().__init__(ui.root)
        self.cfg, self.on_saved = cfg, on_saved
        self.title("TextFixer - Settings")
        self.resizable(False, False)
        body = tk.Frame(self, padx=10, pady=10)
        body.pack()
        tk.Label(body, text="Provider", anchor="w", width=20).grid(row=0, column=0, sticky="w", pady=2)
        self.provider = tk.StringVar(value=cfg.provider)
        tk.OptionMenu(body, self.provider, "local", "openai", "gemini", "ollama").grid(row=0, column=1, sticky="we")
        self.vars: dict[tuple, tk.StringVar] = {}
        for i, (section, key, label) in enumerate(SETTINGS_FIELDS, start=1):
            tk.Label(body, text=label, anchor="w", width=20).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=cfg.setting(key) if section == "Settings" else cfg.server(key))
            self.vars[(section, key)] = var
            entry = tk.Entry(body, textvariable=var, width=46, show="*" if key == "API_KEY" else "")
            entry.grid(row=i, column=1, sticky="we")
            if key == "MODEL_DIR":
                tk.Button(body, text="Browse...", command=self.browse).grid(row=i, column=2, padx=(4, 0))
        hint = ("Provider: local = the model on this PC (NPU/GPU/CPU, see [Server]); openai = any OpenAI-compatible "
                "server (set API URL); gemini = Google; ollama = local Ollama.\nHotkeys: ^ Ctrl, ! Alt, + Shift, "
                "# Win; empty turns one off. Saving restarts TextFixer.")
        tk.Label(body, text=hint, wraplength=560, justify="left", fg="#666").grid(
            row=len(SETTINGS_FIELDS) + 1, column=0, columnspan=3, sticky="w", pady=8)
        buttons = tk.Frame(body)
        buttons.grid(row=len(SETTINGS_FIELDS) + 2, column=0, columnspan=3, sticky="w")
        tk.Button(buttons, text="Save and restart", width=16, command=self.save).pack(side="left")
        tk.Button(buttons, text="Cancel", width=10, command=self.destroy).pack(side="left", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())

    def browse(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Folder with the OpenVINO model")
        if folder:
            self.vars[("Server", "MODEL_DIR")].set(folder)

    def save(self) -> None:
        settings = {"PROVIDER": self.provider.get()}
        server: dict[str, str] = {}
        for (section, key), var in self.vars.items():
            (settings if section == "Settings" else server)[key] = var.get().strip()
        self.cfg.update("Settings", settings)
        self.cfg.update("Server", server)
        self.destroy()
        self.on_saved()
