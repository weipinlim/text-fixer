# TextFixer

Fix or rewrite selected text in any Windows app with one hotkey. TextFixer sends the selection to
your self-hosted vLLM server (OpenAI-compatible API) and pastes the result back in place.

## Setup

1. Install [AutoHotkey v2](https://www.autohotkey.com/) (not needed if you use a compiled `TextFixer.exe`).
2. Download or clone this repo:
   ```
   git clone https://github.com/weipinlim/text-fixer.git
   ```
3. Copy `config.example.ini` to `config.ini` in the same folder.
4. Open `config.ini` and fill in:
   - `API_URL`: your server's chat endpoint, e.g. `http://192.168.1.10:8000/v1/chat/completions`
   - `API_KEY`: your key (leave empty if the server has no `--api-key`)
   - `MODEL`: the model name, as listed at `http://YOUR_SERVER:8000/v1/models`
   - the `[Preset1]`…`[Preset5]` prompts (the examples are placeholders, replace them with your own)
5. Double-click `TextFixer.ahk`. A green **H** icon appears in the system tray.

`config.ini` is in `.gitignore`, so your real key is never uploaded.

## Usage

1. Select text in any app (email, Word, browser, chat…).
2. Press a preset hotkey:

   | Hotkey | Example preset       |
   |--------|----------------------|
   | Ctrl+1 | Fix grammar          |
   | Ctrl+2 | Professional         |
   | Ctrl+3 | Friendly             |
   | Ctrl+4 | Shorten              |
   | Ctrl+5 | Translate to English |

3. Wait for the tooltip to disappear. The selection is replaced with the result.

**No text selected?** The hotkey is passed straight through to the app, so normal shortcuts such as
Ctrl+1–5 in Outlook, Teams and browser tabs keep working.

Your clipboard is restored afterwards. Right-click the tray icon → **Show hotkeys** to see the
current list.

## Changing hotkeys and presets

Each preset in `config.ini` has its own section:

```ini
[Preset1]
NAME=Fix grammar
HOTKEY=^1
PROMPT=You are a proofreader. ...
```

- `HOTKEY` uses AutoHotkey syntax: `^` = Ctrl, `!` = Alt, `+` = Shift, `#` = Win.
  For example, `^1` = Ctrl+1 and `^!1` = Ctrl+Alt+1 (the old style).
- You can have up to 9 presets (`[Preset1]`…`[Preset9]`). Delete a section to remove a preset.
- Use `\n` for a line break inside a `PROMPT`.

After editing, right-click the tray icon → **Reload config**.

Other settings in `[Settings]`:

- `EXCLUDE_APPS`: apps where the hotkeys always act as normal shortcuts (comma-separated process
  names). The default is `EXCEL.EXE`, because Excel copies the active cell even when no text is
  selected, so Ctrl+1 (Format Cells) would otherwise be taken over.
- `SELECTION_WAIT_MS`: how long to wait for the selection to be copied (default 300). Raise it if a
  slow app sometimes gets the normal shortcut when text *is* selected.

## Make a standalone .exe (optional)

So you can run it on PCs without AutoHotkey:

1. Right-click `TextFixer.ahk` → **Compile Script** (or open *Ahk2Exe* from the AutoHotkey Dash).
2. Put `config.ini` in the same folder as `TextFixer.exe`.
3. Double-click `TextFixer.exe`.

To start it automatically with Windows, press `Win+R`, type `shell:startup`, and put a shortcut to
`TextFixer.ahk` / `TextFixer.exe` in that folder.

## Troubleshooting

- **"config.ini not found"**: create it from `config.example.ini` next to the script/exe.
- **"Request failed: HTTP 401"**: wrong `API_KEY`.
- **"Request failed: HTTP 404"**: check `API_URL` ends with `/v1/chat/completions` and `MODEL` matches the server.
- **Timeout / cannot connect**: check that the server is reachable from this PC, or raise `TIMEOUT`.
- **A hotkey rewrites text when nothing is selected**: some editors (e.g. VS Code) copy the whole
  line on Ctrl+C with no selection. Add that app to `EXCLUDE_APPS` (e.g. `EXCEL.EXE,Code.exe`).
- **Non-English characters in prompts look broken**: in Notepad, *Save As* `config.ini` with
  encoding **UTF-16 LE** (Windows INI files don't read UTF-8).
