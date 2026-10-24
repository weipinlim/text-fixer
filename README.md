# TextFixer

Select text in any Windows app, press a shortcut, and an AI rewrites it in place: fix the grammar,
change the tone (casual, professional, diplomatic...), summarize it, turn it into a table, translate
it, or explain a word. The AI can run **on your own PC** with [Ollama](https://ollama.com), so your
text never leaves it, or use any OpenAI-compatible server or Google Gemini.

There are two versions. They do the same job and share the same `config.ini` format.

| | [AutoHotkey version](ahk/README.md) (`ahk/`) | [Python version](python/README.md) (`python/`) |
|---|---|---|
| **Best for** | The lightest setup, mouse shortcuts | The easiest setup for most people |
| **Install** | One-click installer (TextFixer, Ollama and the model), or the script itself | One-click installer (TextFixer, Ollama and the model) |
| **Shortcuts** | Keyboard **and mouse** (Ctrl+click, Ctrl+Shift+click...) | Keyboard only (nothing runs on your other keystrokes or mouse moves) |
| **Look** | Standard Windows windows | Rounded, modern windows, light and dark |
| **Size** | About 1.3 MB (plus Ollama and the model) | About 60 MB (plus Ollama and the model) |

Both can: rewrite in a tone and replace the selection, open a popup where you describe any change,
compare every tone's answer and pick one, show summaries and tables in a result window with
follow-up chat, and explain a word in a tooltip.

## Which one?

- **Not sure?** Use the **Python version's one-click installer** from the
  [Releases](../../releases) page: it installs TextFixer, Ollama and the AI model for you.
- **Want Ctrl+click and the smallest footprint?** Use the **AutoHotkey version**: its installer,
  `TextFixer-AHK-Setup.exe`, also installs Ollama and the AI model.

Both installers are built by GitHub Actions: open the **Actions** tab, pick *Windows installer*
(Python) or *Build AutoHotkey installer*, open the latest green run and download the artifact.

## Repository layout

```
ahk/       AutoHotkey version (TextFixer.ahk, lib/, config.example.ini, installer/)
python/    Python version (textfixer/ package, tests, installer, build scripts)
.github/   GitHub Actions: builds the Windows installers
```

`config.ini` (your settings and API keys) is never committed: it is in `.gitignore`.
