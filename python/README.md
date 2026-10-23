# TextFixer (Python, Ollama)

The Python version of TextFixer. Select text in any app, press a hotkey, and the text is rewritten
by an LLM running in **[Ollama](https://ollama.com)** on your PC (or any OpenAI-compatible server, or
Gemini). It does the same things as the [AutoHotkey version](../README.md) and uses the same
`config.ini` format, so tones and hotkeys move between them:

- tone hotkeys (`Ctrl+1`..`Ctrl+5`) replace the selection; `Ctrl+Left click` runs the default tone
- `Ctrl+Shift+Space`: popup with a "describe your change" box and a button per tone
- `Ctrl+6/7/8`: Summary, Key Points, Table in a result window (Markdown, follow-up chat)
- `Ctrl+Shift+Left click` / `Ctrl+Shift+Right click`: every tone's answer in tabs / as a list (hover for full text)
- `Ctrl+Middle click`: explain the selected word in a tooltip
- `Ctrl+Alt+Space`: chat window
- tray icon: settings, pause hotkeys, start with Windows

> The earlier OpenVINO/NPU version of this app is on the branch `feature/python-npu`. This branch
> replaces it with Ollama: Ollama is the model server, so there is no local API server, device
> choice or model conversion to deal with.

## Install

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

Everything else (hotkeys, tones, `EXCLUDE_APPS`) works as in the AutoHotkey version. Hotkey syntax:
`^` Ctrl, `!` Alt, `+` Shift, `#` Win, then a key or `LButton`/`RButton`/`MButton`.

## Make a standalone .exe (no Python needed on other PCs)

On a Windows PC with Python 3.10+, double-click `build_exe.bat` in this folder. It creates a virtual
environment, installs the requirements and PyInstaller, and builds `dist\TextFixer\`:

- `TextFixer.exe`: the app, no console window (errors go to `textfixer.log` next to it)
- `TextFixerCLI.exe`: the same program with a console, for `check` and seeing errors
- `config.example.ini`: the first run copies it to `config.ini` and opens Settings

Copy the whole `dist\TextFixer` folder to another PC (which also needs Ollama) and run it. It is not
code-signed, so Windows SmartScreen or antivirus may warn on first run.

## Differences from the AutoHotkey version

- On Windows the matched hotkey or click is swallowed and passed through to the app when nothing is
  selected, like the AutoHotkey version. This uses low-level hooks and is the part most worth testing
  on your PC.
- Only **text** on the clipboard is saved and restored (images or files on the clipboard are lost
  when a hotkey runs). The AutoHotkey version restores everything.
- The Settings window restarts the app when you save, and can download Ollama models.

## Troubleshooting

- **"Cannot reach Ollama"**: start Ollama (Start menu), or check `API_URL`.
- **"Ollama does not have the model ..."**: Settings > Download model, or `ollama pull <model>`.
- **The first answer is slow**: the model is loading into memory. Later ones are faster until
  `KEEP_ALIVE` runs out.
- **Nothing happens on a hotkey**: another program may own it. Change it in Settings. The tray
  icon's **Show hotkeys** lists what is active.
- **A hotkey acts on the wrong app or pastes nothing**: some apps (Excel, VS Code) copy even with no
  selection; add them to `EXCLUDE_APPS`.

## Tests

```
pip install pytest
python -m pytest tests
```
The window tests need a display (on Linux: `xvfb-run -a python -m pytest tests`). They use a small
mock Ollama, so Ollama itself is not needed.
