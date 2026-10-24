"""Tiny Markdown renderer for a tkinter Text widget: headings, bold/italic/strike, inline
code, code blocks, bullet/numbered lists, tables, quotes and rules."""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont

INLINE = re.compile(
    r"`([^`]+)`"                                          # 1 code
    r"|\*\*(.+?)\*\*|__(.+?)__"                           # 2, 3 bold
    r"|(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])"   # 4 italic
    r"|~~(.+?)~~"                                         # 5 strike
    r"|\[([^\]]+)\]\((https?://[^)\s]+)\)"                # 6, 7 link
)


def parse_inline(text: str, styles: frozenset = frozenset()) -> list[tuple[str, frozenset]]:
    """-> [(text, styles)] where styles is a set of "bold", "italic", "code", "strike"."""
    out: list[tuple[str, frozenset]] = []
    pos = 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], styles))
        if m.group(1) is not None:
            out.append((m.group(1), styles | {"code"}))
        elif m.group(2) is not None or m.group(3) is not None:
            out += parse_inline(m.group(2) or m.group(3), styles | {"bold"})
        elif m.group(4) is not None:
            out += parse_inline(m.group(4), styles | {"italic"})
        elif m.group(5) is not None:
            out += parse_inline(m.group(5), styles | {"strike"})
        else:
            out.append((f"{m.group(6)} ({m.group(7)})", styles))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], styles))
    return out


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


_FENCE = re.compile(r"^\s*```")
_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def parse_markdown(md: str) -> list[tuple]:
    """Blocks: ("h", level, text) ("p", text) ("li", marker, text) ("code", text) ("quote", text)
    ("hr",) ("table", header, rows)."""
    lines = md.replace("\r\n", "\n").split("\n")
    blocks: list[tuple] = []
    para: list[str] = []
    counters: dict[str, int] = {}

    def flush():
        if para:
            blocks.append(("p", "\n".join(para)))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if _FENCE.match(line):
            flush()
            code = []
            while i < len(lines) and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", "\n".join(code)))
            continue
        if not line.strip():
            flush()
            continue
        if (m := re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", line)):
            flush()
            blocks.append(("h", len(m.group(1)), m.group(2)))
            continue
        if re.match(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$", line):
            flush()
            blocks.append(("hr",))
            continue
        if "|" in line and i < len(lines) and _SEP.match(lines[i]):
            flush()
            header = _cells(line)
            i += 1
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            blocks.append(("table", header, rows))
            continue
        if (m := re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)):
            flush()
            marker = m.group(2)
            if marker[0].isdigit():
                counters["ol"] = counters.get("ol", 0) + 1
                marker = f"{counters['ol']}."
            else:
                counters["ol"] = 0
                marker = "•"
            blocks.append(("li", marker, m.group(3), len(m.group(1)) // 2))
            continue
        if (m := re.match(r"^\s*>\s?(.*)$", line)):
            flush()
            blocks.append(("quote", m.group(1)))
            continue
        counters["ol"] = 0
        para.append(line)
    flush()
    return blocks


class MarkdownView:
    """Renders Markdown into a (read-only) Text widget."""

    def __init__(self, text: tk.Text, dark: bool = False, bg: str | None = None, family: str | None = None):
        self.text = text
        base = tkfont.nametofont("TkDefaultFont")
        size = max(base.cget("size"), 10)
        family = family or base.cget("family")
        mono = tkfont.Font(family="Courier New", size=size - 1)
        self._fonts = {  # keep references so they are not garbage collected
            "base": tkfont.Font(family=family, size=size),
            "bold": tkfont.Font(family=family, size=size, weight="bold"),
            "italic": tkfont.Font(family=family, size=size, slant="italic"),
            "bolditalic": tkfont.Font(family=family, size=size, weight="bold", slant="italic"),
            "mono": mono,
            "h1": tkfont.Font(family=family, size=size + 6, weight="bold"),
            "h2": tkfont.Font(family=family, size=size + 4, weight="bold"),
            "h3": tkfont.Font(family=family, size=size + 2, weight="bold"),
        }
        fg, default_bg = ("#e6e6e6", "#1e1e1e") if dark else ("#202020", "#ffffff")
        bg = bg or default_bg
        code_bg = "#2b2b2b" if dark else "#f1f1f1"
        text.configure(font=self._fonts["base"], fg=fg, bg=bg, insertbackground=fg, wrap="word", padx=14, pady=10,
                       borderwidth=0, highlightthickness=0, selectbackground="#3b82f6")
        t = text.tag_configure
        t("bold", font=self._fonts["bold"])
        t("italic", font=self._fonts["italic"])
        t("bolditalic", font=self._fonts["bolditalic"])
        t("strike", overstrike=True)
        t("code", font=mono, background=code_bg)
        t("codeblock", font=mono, background=code_bg, lmargin1=12, lmargin2=12, spacing1=1, spacing3=1)
        t("h1", font=self._fonts["h1"], spacing1=8, spacing3=4)
        t("h2", font=self._fonts["h2"], spacing1=8, spacing3=4)
        t("h3", font=self._fonts["h3"], spacing1=6, spacing3=2)
        t("li", lmargin1=16, lmargin2=34)
        t("li2", lmargin1=36, lmargin2=54)
        t("quote", lmargin1=14, lmargin2=14, foreground="#888888")
        t("table", font=mono, lmargin1=8, lmargin2=8)
        t("user", background="#2d3b55" if dark else "#e3ecfb", lmargin1=60, lmargin2=60, spacing1=6, spacing3=6)
        t("error", foreground="#d33")
        t("dim", foreground="#888888")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def add_plain(self, text: str, tag: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", text + "\n\n", tag)
        self.text.configure(state="disabled")

    def add_markdown(self, md: str) -> None:
        self.text.configure(state="normal")
        prev = ""
        for block in parse_markdown(md):
            kind = block[0]
            if prev in ("li", "quote") and kind != prev:
                self.text.insert("end", "\n")  # air after a list or quote
            prev = kind
            if kind == "h":
                self._inline(block[2], (f"h{min(block[1], 3)}",))
                self.text.insert("end", "\n")
            elif kind == "p":
                self._inline(block[1], ())
                self.text.insert("end", "\n\n")
            elif kind == "li":
                tag = "li2" if block[3] else "li"
                self.text.insert("end", f"{block[1]} ", tag)
                self._inline(block[2], (tag,))
                self.text.insert("end", "\n", tag)
            elif kind == "code":
                self.text.insert("end", block[1] + "\n\n", "codeblock")
            elif kind == "quote":
                self._inline(block[1], ("quote",))
                self.text.insert("end", "\n")
            elif kind == "hr":
                self.text.insert("end", "─" * 40 + "\n\n", "dim")
            elif kind == "table":
                self._table(block[1], block[2])
        self.text.configure(state="disabled")
        self.text.see("end")

    def _inline(self, text: str, base_tags: tuple) -> None:
        for chunk, styles in parse_inline(text):
            tags = list(base_tags)
            if "bold" in styles and "italic" in styles:
                tags.append("bolditalic")
            else:
                tags += [s for s in ("bold", "italic") if s in styles]
            tags += [s for s in ("code", "strike") if s in styles]
            self.text.insert("end", chunk, tuple(tags))

    def _table(self, header: list[str], rows: list[list[str]]) -> None:
        strip = lambda s: "".join(c for c, _ in parse_inline(s))  # noqa: E731 - plain text of a cell
        grid = [[strip(c) for c in header]] + [[strip(c) for c in r] for r in rows]
        cols = max(len(r) for r in grid)
        widths = [max(len(r[i]) if i < len(r) else 0 for r in grid) for i in range(cols)]
        for n, row in enumerate(grid):
            line = " | ".join((row[i] if i < len(row) else "").ljust(widths[i]) for i in range(cols))
            self.text.insert("end", line + "\n", ("table", "bold") if n == 0 else ("table",))
            if n == 0:
                self.text.insert("end", "-+-".join("-" * w for w in widths) + "\n", "table")
        self.text.insert("end", "\n")
