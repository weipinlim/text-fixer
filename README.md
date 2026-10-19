# TextFixer

Fix any selected text in any Windows app with one hotkey. TextFixer sends the selection to your
self-hosted vLLM server (OpenAI-compatible API) and pastes the corrected text back in place.

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
   - `SYSTEM_PROMPT`: optional, the instructions for how to fix text
5. Double-click `TextFixer.ahk`. A green **H** icon appears in the system tray.

`config.ini` is in `.gitignore`, so your real key is never uploaded.

## Usage

1. Select text in any app (email, Word, browser, chat…).
2. Press **Ctrl+Alt+F**.
3. Wait for the "Fixing text..." tooltip to disappear. The selection is replaced with the fixed text.

Your clipboard is restored afterwards. To change the hotkey, edit `HOTKEY` in `config.ini`.
After editing the config, right-click the tray icon → **Reload config**.

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
- **Non-English characters in `SYSTEM_PROMPT` look broken**: in Notepad, *Save As* `config.ini` with
  encoding **UTF-16 LE** (Windows INI files don't read UTF-8).
