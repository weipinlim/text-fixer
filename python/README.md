# TextFixer (Python, Ollama)

The Python version of TextFixer. Select text in any app, press a hotkey, and the text is rewritten
by an LLM running in **[Ollama](https://ollama.com)** on your PC (or any OpenAI-compatible server, or
Gemini). It does the same things as the [AutoHotkey version](../README.md) and uses the same
`config.ini` format, so tones and hotkeys move between them:

- `Ctrl+1`..`Ctrl+5`: rewrite the selection in a tone and replace it
- `Ctrl+6/7/8`: Summary, Key Points, Table in a result window (Markdown, follow-up chat)
- `Ctrl+Shift+Space`: popup at the cursor: describe any change, pick a tone, **Compare all**
  (every tone's answer, in tabs or as a list) or **Explain** (the selected word, in a tooltip)
- `Ctrl+Alt+Space`: chat window
- tray icon: settings, pause hotkeys, start with Windows

Shortcuts are **keyboard only** and use Windows' own hotkey system, so TextFixer never slows down
your mouse or keyboard. (Mouse shortcuts like Ctrl+click, which the AutoHotkey version has, are not
available here; an older `config.ini` that has them gets them switched off once, with a note.) You
can give Compare and Explain their own keys in Settings.

> The earlier OpenVINO/NPU version of this app is on the branch `feature/python-npu`. This branch
> replaces it with Ollama: Ollama is the model server, so there is no local API server, device
> choice or model conversion to deal with.

## One-click install (for most people)

Download **`TextFixer-Setup.exe`** from the repository's **Releases** page and double-click it. It
installs everything, with no admin rights needed:

1. TextFixer (in your user folder, with a Start Menu entry, and optionally started with Windows)
2. **Ollama**, if it is not installed yet (the official installer from Ollama's GitHub releases)
3. The AI model, **Qwen3 4B instruct** (about 2.5 GB; a window shows the download progress)

When it finishes, TextFixer is running: select text anywhere and press `Ctrl+1`. The installer is
not code-signed, so Windows SmartScreen may say "Windows protected your PC": click **More info** >
**Run anyway** if you trust where you downloaded it from.

Uninstalling (Settings > Apps, or the Start Menu) removes TextFixer. Ollama and the model stay, since
other programs may use them; remove them from Settings > Apps and with `ollama rm <model>` if you want.

### Making a release (for the maintainer)

The installer is built by GitHub Actions (`.github/workflows/installer.yml`) on a Windows machine:
every push that changes `python/` builds it (download it from the run's **Artifacts**), and pushing a
tag such as `v1.0.0` also attaches it to a GitHub release:

```
git tag v1.0.0
git push origin v1.0.0
```

The model the installer downloads is set in `textfixer/setup_cmd.py` (`DEFAULT_MODELS`): it tries
the names in order and uses the first one Ollama can download. `TextFixerCLI.exe setup` does the
same by hand (start Ollama, download the model, write `config.ini`).

## Install by hand (developers)

1. Install **Ollama** from https://ollama.com/download and start it (it runs in the background).
2. Install **Python 3.10 or newer** from python.org (it includes tkinter).
3. In this folder:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python -m textfixer
   ```
4. The first run creates `config.ini` and opens **Settings**. Type a model name (for example
   `llama3.2`) and click **Download model**; a window shows the progress. Then **Save and restart**.

Check any time that everything is connected:
```
python -m textfixer check
```
It says whether Ollama is reachable and the model is installed.

Which model? A 3B to 8B instruction model is a good start: `llama3.2` (3B), `qwen2.5:3b`,
`gemma2:2b`, `llama3.1:8b` for a stronger PC. Browse https://ollama.com/library. Smaller models are
faster but make more mistakes.

## Settings that matter

- `PROVIDER=ollama` (default), `openai` (any OpenAI-compatible server) or `gemini`.
- `MODEL`: the Ollama model name (see `ollama list`).
- `API_URL`: leave empty for Ollama on this PC. For Ollama on another PC use `http://ADDRESS:11434`
  (Ollama only listens on the local PC unless you set `OLLAMA_HOST` there).
- `KEEP_ALIVE=30m`: how long Ollama keeps the model in memory after your last request. The first
  request after it unloads is slow because the model loads again.
- `TIMEOUT=120`: seconds to wait for an answer (the first request also loads the model).
- `THINK=off`: "thinking" models such as Qwen3 normally reason (hidden) before answering, which
  makes every answer several times slower. `off` makes them answer straight away, which is plenty
  for rewriting. Set `on` if you want the reasoning.

Everything else (hotkeys, tones, `EXCLUDE_APPS`) works as in the AutoHotkey version. Hotkey syntax:
`^` Ctrl, `!` Alt, `+` Shift, `#` Win, then a key (letters, digits, `F1`..`F24`, `Space`, `Enter`...).

## Make a standalone .exe (no Python needed on other PCs)

On a Windows PC with Python 3.10+, double-click `build_exe.bat` in this folder. It creates a virtual
environment, installs the requirements and PyInstaller, and builds `dist\TextFixer\`:

- `TextFixer.exe`: the app, no console window (errors go to `textfixer.log` next to it)
- `TextFixerCLI.exe`: the same program with a console, for `check` and seeing errors
- `config.example.ini`: the first run copies it to `config.ini` and opens Settings

Copy the whole `dist\TextFixer` folder to another PC (which also needs Ollama) and run it. It is not
code-signed, so Windows SmartScreen or antivirus may warn on first run.

## Differences from the AutoHotkey version

- Keyboard shortcuts only (no Ctrl+click and so on): they use Windows' RegisterHotKey, so nothing
  runs on your other keystrokes or mouse moves. When nothing is selected the keys still reach the app
  (e.g. Ctrl+1 in Outlook), like in the AutoHotkey version.
- Only **text** on the clipboard is saved and restored (images or files on the clipboard are lost
  when a hotkey runs). The AutoHotkey version restores everything.
- The Settings window restarts the app when you save, and can download Ollama models.

## Troubleshooting

- **A key or the mouse seems stuck, or the mouse is sluggish**: that was the older version's mouse
  shortcuts, which this version no longer uses. Quit the old TextFixer (tray icon > Quit, or end it in
  Task Manager), press and release Ctrl, Shift and Alt once, and install the current version.
- **"... is already used by another program"**: another app owns that shortcut. Pick another one in
  Settings.
- **"Cannot reach Ollama"**: start Ollama (Start menu), or check `API_URL`.
- **"Ollama does not have the model ..."**: Settings > Download model, or `ollama pull <model>`.
- **"Every tone at once" takes a while**: a model on your PC writes one answer at a time, so 5 tones
  take about 5 times as long as one. The window shows "2 of 5 ready" and you can pick any finished
  version straight away; closing it stops the rest. Check `THINK=off` too.
- **The first answer is slow**: the model is loading into memory. Later ones are faster until
  `KEEP_ALIVE` runs out.
- **Nothing happens on a hotkey**: the tray icon's **Show hotkeys** lists what is active.
- **A hotkey acts on the wrong app or pastes nothing**: some apps (Excel, VS Code) copy even with no
  selection; add them to `EXCLUDE_APPS`.

## Tests

```
pip install pytest
python -m pytest tests
```
The window tests need a display (on Linux: `xvfb-run -a python -m pytest tests`). They use a small
mock Ollama, so Ollama itself is not needed.
