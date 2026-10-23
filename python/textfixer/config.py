"""config.ini handling. The format matches the AutoHotkey version."""

from __future__ import annotations

import configparser
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

INCOMPATIBLE_MARK = "ERROR_TEXT_INCOMPATIBLE_WITH_REQUEST"
INCOMPATIBLE_RULE = (
    "If the text is absolutely incompatible with this request (for example random gibberish), "
    f"output exactly {INCOMPATIBLE_MARK} and nothing else."
)
CUSTOM_PROMPT = (
    "You are a writing and coding assistant. Make the change the user describes to the text or "
    "code they give you. Output ONLY the modified text or code, without any extra comments. "
    "Respond in the same language as the input."
)
FOLLOWUP_SYSTEM = (
    "You are a helpful AI assistant. Answer clearly and directly, keep the same style as your "
    "earlier answers, and use Markdown where it helps readability."
)
FALLBACK_PROMPT = (
    "Fix spelling, grammar and punctuation in the user's text. Keep the meaning, tone and "
    "language. Return only the corrected text."
)
EXPLAIN_PROMPT = (
    "Explain the selected word, phrase or text briefly and simply, in the same language as the "
    "text. For a word, give its meaning and one short example sentence. Keep it under 80 words. "
    "Return only the explanation."
)

SETTINGS_DEFAULTS = {
    "PROVIDER": "ollama",  # ollama | openai | gemini
    "API_URL": "",
    "API_KEY": "",
    "MODEL": "llama3.2",
    "KEEP_ALIVE": "30m",  # how long Ollama keeps the model in memory after the last request
    "TEMPERATURE": "0.2",
    "TIMEOUT": "120",
    "SELECTION_WAIT_MS": "300",
    "EXCLUDE_APPS": "EXCEL.EXE",
    "DEFAULT_PRESET": "1",
    "DEFAULT_HOTKEY": "^LButton",
    "POPUP_HOTKEY": "^+Space",
    "MENU_HOTKEY": "^RButton",
    "PREVIEW_HOTKEY": "^+LButton",
    "RESULTS_MENU_HOTKEY": "^+RButton",
    "EXPLAIN_HOTKEY": "^MButton",
    "CHAT_HOTKEY": "^!Space",
    "EXPLAIN_SECONDS": "30",
    "EXPLAIN_PROMPT": "",
}

@dataclass
class Preset:
    index: int
    name: str
    hotkey: str
    mode: str  # "replace" or "window"
    prompt: str


def _new_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False, inline_comment_prefixes=None,
                                       comment_prefixes=(";", "#"))
    parser.optionxform = str  # keep KEY case
    return parser


class Config:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.parser = _new_parser()
        self.parser.read(self.path, encoding="utf-8-sig")
        self.presets = self._load_presets()

    # -- access ---------------------------------------------------------
    def setting(self, key: str) -> str:
        return self.parser.get("Settings", key, fallback=SETTINGS_DEFAULTS.get(key, "")).strip()

    def number(self, key: str, default: float) -> float:
        try:
            return float(self.setting(key))
        except ValueError:
            return default

    @property
    def provider(self) -> str:
        return self.setting("PROVIDER").lower()

    @property
    def tones(self) -> list[Preset]:
        return [p for p in self.presets if p.mode != "window"]

    def default_preset(self) -> Preset:
        for preset in self.presets:
            if str(preset.index) == self.setting("DEFAULT_PRESET"):
                return preset
        return (self.tones or self.presets)[0]

    def explain_prompt(self) -> str:
        return (self.setting("EXPLAIN_PROMPT") or EXPLAIN_PROMPT).replace("\\n", "\n")

    def excluded_apps(self) -> set[str]:
        return {a.strip().lower() for a in self.setting("EXCLUDE_APPS").split(",") if a.strip()}

    # -- presets --------------------------------------------------------
    def _load_presets(self) -> list[Preset]:
        presets = []
        for i in range(1, 10):
            section = f"Preset{i}"
            if not self.parser.has_section(section):
                continue
            name = self.parser.get(section, "NAME", fallback="").strip()
            prompt = self.parser.get(section, "PROMPT", fallback="").strip()
            if not name and not prompt:
                continue
            presets.append(Preset(
                index=i,
                name=name or section,
                hotkey=self.parser.get(section, "HOTKEY", fallback="").strip(),
                mode=self.parser.get(section, "MODE", fallback="replace").strip().lower(),
                prompt=(prompt or FALLBACK_PROMPT).replace("\\n", "\n"),
            ))
        return presets

    # -- writing --------------------------------------------------------
    def update(self, section: str, values: dict[str, str]) -> None:
        update_ini_values(self.path, section, values)
        self.__init__(self.path)


def update_ini_values(path: Path, section: str, values: dict[str, str]) -> None:
    """Set KEY=value lines in one section, keeping comments and everything else as is."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    pending = dict(values)
    out: list[str] = []
    in_section = False
    seen_section = False
    last_in_section = -1
    for line in lines:
        header = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if header:
            if in_section and pending:  # leaving the section: add what was missing
                out[last_in_section + 1:last_in_section + 1] = [f"{k}={v}" for k, v in pending.items()]
                pending = {}
            in_section = header.group(1) == section
            seen_section = seen_section or in_section
        elif in_section:
            m = re.match(r"^\s*([^=;#\s][^=]*?)\s*=", line)
            if m and m.group(1) in pending:
                line = f"{m.group(1)}={pending.pop(m.group(1))}"
        out.append(line)
        if in_section and line.strip():
            last_in_section = len(out) - 1
    if pending:
        if seen_section:
            out[last_in_section + 1:last_in_section + 1] = [f"{k}={v}" for k, v in pending.items()]
        else:
            out += ["", f"[{section}]"] + [f"{k}={v}" for k, v in pending.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def ensure_config(path: str | Path) -> Path:
    """Create config.ini from config.example.ini next to it on the first run."""
    path = Path(path)
    if not path.exists():
        example = path.with_name("config.example.ini")
        if not example.exists():
            raise FileNotFoundError(f"{path} not found and there is no config.example.ini next to it")
        shutil.copyfile(example, path)
    return path
