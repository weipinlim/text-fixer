"""tkinter user interface. Everything here runs in the UI thread; other threads use Ui.call()."""

from __future__ import annotations

import gc
import logging
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Callable

from .config import FOLLOWUP_SYSTEM, Config, Preset
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
    running: bool = False  # the server is working on it now (others may be waiting their turn)


class Ui:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("TextFixer")
        self.dark = is_dark_mode()
        apply_theme(self)
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
        row = 3 + (len(app.cfg.presets) - 1) // 3
        tk.Label(body, text="Or:", anchor="w").grid(row=row, column=0, columnspan=3, sticky="we", pady=(6, 0))
        extras = [("Compare all (tabs)", lambda: self.compare("tabs")),
                  ("Compare all (list)", lambda: self.compare("list")),
                  ("Explain", self.explain)]
        for i, (text, command) in enumerate(extras):
            tk.Button(body, text=text, width=20, command=command).grid(row=row + 1, column=i, padx=2, pady=2)
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

    def compare(self, mode: str) -> None:
        self._take()
        threading.Thread(target=self.app.compare, args=(self.ctx, mode), daemon=True).start()

    def explain(self) -> None:
        self._take()
        threading.Thread(target=self.app.explain, args=(self.ctx,), daemon=True).start()


# ---------------------------------------------------------------------------
# Compare windows: every tone's answer, as tabs or as a list with hover text
# ---------------------------------------------------------------------------

class CompareWindow(tk.Toplevel):
    def __init__(self, ui: Ui, app, ctx: Context, jobs: list[Job], mode: str, stop=None):
        super().__init__(ui.root)
        self.ui, self.app, self.ctx, self.jobs, self.mode = ui, app, ctx, jobs, mode
        self.stop = stop  # threading.Event: set when the window closes, so no more answers are asked for
        self.selected = 0
        self.user_picked_tab = False
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
                label = tk.Label(row, text="Waiting for its turn...", width=70, anchor="w", relief="solid", bd=1, padx=4)
                label.pack(side="left")
                label.bind("<Button-1>", lambda e, i=i: self.use(i))
                label.bind("<Enter>", lambda e, i=i: self.hover(i))
                label.bind("<Leave>", lambda e: self.ui.hide_tip())
                self.rows.append(label)
            tk.Button(body, text="Cancel", width=10, command=self.close).pack(anchor="w", pady=(6, 0))
        self.progress = tk.Label(body, text="", anchor="w", fg="#666")
        self.progress.pack(fill="x", pady=(4, 0))
        for n in range(1, 10):
            self.bind(str(n), lambda e, n=n: self.key(n - 1))
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.ui.place_near_cursor(self)
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
                name = f"{job.preset.index} {job.preset.name}"
                b.configure(text=f"[{name}]" if i == self.selected else name)
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
PROVIDERS = {"ollama": "Ollama (on this PC)", "openai": "OpenAI-compatible server", "gemini": "Google Gemini"}


def apply_theme(ui: "Ui") -> None:
    """Windows 11 look (Sun Valley ttk theme), light or dark like Windows. Falls back quietly."""
    if getattr(ui, "_themed", False):
        return
    ui._themed = True
    try:
        import sv_ttk

        sv_ttk.set_theme("dark" if ui.dark else "light", ui.root)
        # The theme sets its colours on an event our hidden main window never gets: apply them now
        ui.root.tk.call("configure_colors")
    except Exception as exc:  # not installed / Tk too old: the standard look still works
        log.info("Sun Valley theme not used (%s)", exc)
        try:
            ttk.Style().theme_use("vista" if "vista" in ttk.Style().theme_names() else "clam")
        except tk.TclError:
            pass


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


class SettingsWindow(tk.Toplevel):
    """Settings, in three tabs (Model, Shortcuts, Advanced). Saving writes config.ini and restarts."""

    def __init__(self, ui: Ui, app, on_saved: Callable[[], None]):
        super().__init__(ui.root)
        self.ui, self.app, self.cfg, self.on_saved = ui, app, app.cfg, on_saved
        self.title("TextFixer Settings")
        self.resizable(False, False)
        style = ttk.Style()
        self.configure(bg=style.lookup("TFrame", "background") or self.cget("bg"))
        style.configure("Hint.TLabel", foreground="#8a8a8a")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Error.TLabel", foreground="#d13438")

        outer = ttk.Frame(self, padding=(24, 20, 24, 20))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Settings", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Changes take effect when you save (TextFixer restarts).",
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 14))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self.vars: dict[str, tk.StringVar] = {}
        notebook.add(self._model_tab(notebook), text="  Model  ")
        notebook.add(self._shortcuts_tab(notebook), text="  Shortcuts  ")
        notebook.add(self._advanced_tab(notebook), text="  Advanced  ")

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(16, 0))
        self.error_label = ttk.Label(footer, text="", style="Error.TLabel", wraplength=420, justify="left")
        self.error_label.pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Save and restart", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(footer, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh_models()

    # -- layout helpers ------------------------------------------------------------
    def _rows(self, parent, fields, start: int = 0) -> int:
        for row, (key, label) in enumerate(fields, start=start):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 16))
            var = tk.StringVar(value=self.cfg.setting(key))
            self.vars[key] = var
            ttk.Entry(parent, textvariable=var, width=32, show="\u2022" if key == "API_KEY" else "").grid(
                row=row, column=1, sticky="we", pady=5)
        return start + len(fields)

    def _section(self, parent, text: str, row: int) -> None:
        ttk.Label(parent, text=text, font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(14 if row else 0, 4))

    # -- tabs -------------------------------------------------------------------------
    def _model_tab(self, notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=18)
        tab.columnconfigure(1, weight=1)
        self._section(tab, "AI model", 0)

        ttk.Label(tab, text="Provider").grid(row=1, column=0, sticky="w", pady=5, padx=(0, 16))
        self.provider = tk.StringVar(value=self.cfg.provider if self.cfg.provider in PROVIDERS else "ollama")
        self._provider_label = tk.StringVar(value=PROVIDERS[self.provider.get()])
        box = ttk.Combobox(tab, textvariable=self._provider_label, values=list(PROVIDERS.values()),
                           state="readonly", width=30)
        box.grid(row=1, column=1, sticky="we", pady=5)
        labels_to_keys = {v: k for k, v in PROVIDERS.items()}
        box.bind("<<ComboboxSelected>>", lambda e: self.provider.set(labels_to_keys[self._provider_label.get()]))
        self.provider.trace_add("write", lambda *a: self._provider_label.set(PROVIDERS.get(self.provider.get(), "")))

        ttk.Label(tab, text="Model").grid(row=2, column=0, sticky="w", pady=5, padx=(0, 16))
        self.model = tk.StringVar(value=self.cfg.setting("MODEL"))
        self.model_box = ttk.Combobox(tab, textvariable=self.model, width=30)
        self.model_box.grid(row=2, column=1, sticky="we", pady=5)
        buttons = ttk.Frame(tab)
        buttons.grid(row=2, column=2, padx=(8, 0))
        ttk.Button(buttons, text="Refresh", command=self.refresh_models).pack(side="left")
        ttk.Button(buttons, text="Download", command=self.download).pack(side="left", padx=(6, 0))
        self.status = ttk.Label(tab, text="", style="Hint.TLabel", wraplength=380)
        self.status.grid(row=3, column=1, columnspan=2, sticky="w")

        self._section(tab, "Connection", 4)
        row = self._rows(tab, MODEL_FIELDS, start=5)
        self.vars["THINK"] = tk.StringVar(value="on" if self.cfg.setting("THINK").lower() in ("on", "true", "yes", "1")
                                          else "off")
        ttk.Checkbutton(tab, text="Let \"thinking\" models reason before answering (much slower)",
                        variable=self.vars["THINK"], onvalue="on", offvalue="off").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(tab, text="Ollama on this PC: leave the server address empty. Another PC: http://address:11434.\n"
                            "OpenAI-compatible: the .../v1/chat/completions address. Gemini: only the API key.",
                  style="Hint.TLabel", justify="left").grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        return tab

    @staticmethod
    def _two_columns(parent, items: list[tuple[str, tk.StringVar]], label_width: int) -> None:
        """Label + entry pairs in two columns (half of them on the right)."""
        per_column = (len(items) + 1) // 2
        for i, (label, var) in enumerate(items):
            r, c = i % per_column, (i // per_column) * 2
            ttk.Label(parent, text=label, width=label_width).grid(row=r, column=c, sticky="w", pady=4,
                                                                  padx=(0 if c == 0 else 24, 8))
            ttk.Entry(parent, textvariable=var, width=12).grid(row=r, column=c + 1, sticky="w", pady=4)

    def _shortcuts_tab(self, notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=18)
        self._section(tab, "Tones", 0)
        tones = ttk.Frame(tab)
        tones.grid(row=1, column=0, sticky="w")
        self.tone_vars: dict[int, tk.StringVar] = {}
        for preset in self.cfg.presets:
            self.tone_vars[preset.index] = tk.StringVar(value=preset.hotkey)
        self._two_columns(tones, [(f"{p.index}  {p.name}", self.tone_vars[p.index]) for p in self.cfg.presets], 15)
        ttk.Button(tab, text="Use Ctrl+Shift+F1 \u2026 F8", command=self.use_function_keys).grid(
            row=2, column=0, sticky="w", pady=(8, 0))

        self._section(tab, "Other shortcuts", 3)
        other = ttk.Frame(tab)
        other.grid(row=4, column=0, sticky="w")
        for key, _ in SHORTCUT_FIELDS:
            self.vars[key] = tk.StringVar(value=self.cfg.setting(key))
        self._two_columns(other, [(label, self.vars[key]) for key, label in SHORTCUT_FIELDS], 15)
        ttk.Label(tab, text="Keyboard only: ^ Ctrl, ! Alt, + Shift, # Win, then a key (e.g. ^+F1, ^!E).\n"
                            "Leave one empty to turn it off. The popup can do everything.",
                  style="Hint.TLabel", justify="left").grid(row=5, column=0, sticky="w", pady=(10, 0))
        return tab

    def _advanced_tab(self, notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=18)
        tab.columnconfigure(1, weight=1)
        self._section(tab, "Advanced", 0)
        row = self._rows(tab, ADVANCED_FIELDS, start=1)
        ttk.Label(tab, text="Apps: process names separated by commas, e.g. EXCEL.EXE, Code.exe.\n"
                            "Tones and their prompts are edited in config.ini.",
                  style="Hint.TLabel", justify="left").grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(tab, text="Open config.ini", command=self.open_file).grid(row=row + 1, column=0, sticky="w",
                                                                              pady=(12, 0))
        return tab

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
        self.status.configure(text=error or (f"{len(names)} model(s) installed in Ollama" if names else
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
        import sys

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


class PullWindow(tk.Toplevel):
    """Downloads an Ollama model and shows the progress."""

    def __init__(self, ui: Ui, llm, name: str, on_done: Callable[[], None] | None = None):
        super().__init__(ui.root)
        self.ui, self.llm, self.name, self.on_done = ui, llm, name, on_done
        self.title(f"Downloading {name}")
        self.resizable(False, False)
        self.status = tk.Label(self, text="Starting...", width=60, anchor="w", padx=10, pady=8)
        self.status.pack()
        self.bar = ttk.Progressbar(self, length=420, maximum=100)
        self.bar.pack(padx=10)
        self.close = tk.Button(self, text="Close", state="disabled", command=self.destroy)
        self.close.pack(pady=10)
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # let the download finish
        import threading

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
            self.bar.configure(value=fraction * 100)

    def finish(self, message: str) -> None:
        if not self.winfo_exists():
            return
        self.status.configure(text=message)
        self.close.configure(state="normal")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        if message.startswith("Done"):
            self.bar.configure(value=100)
            if self.on_done:
                self.on_done()
