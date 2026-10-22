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
   - optionally, `DEFAULT_PRESET` and the `[Preset1]`…`[Preset5]` prompts
5. Double-click `TextFixer.ahk`. A green **H** icon appears in the system tray.

`config.ini` is in `.gitignore`, so your real key is never uploaded.

## Usage

1. Select text in any app (email, Word, browser, chat…).
2. Hold **Ctrl** and **left-click** the selection to rewrite it in your **default tone**,
   **Ctrl+right-click** to pick any tone from a menu at the cursor,
   **Ctrl+Shift+left-click** to see every tone's result in a box next to the cursor (one tab each) and pick
   one, **Ctrl+Shift+right-click** to see every tone in one list at the cursor (hover for the full text),
   or press a tone hotkey:

   | Hotkey | Tone         | What it does                                              |
   |--------|--------------|-----------------------------------------------------------|
   | Ctrl+1 | Casual       | Relaxed, conversational (**default** for Ctrl+Left click) |
   | Ctrl+2 | Professional | Polite business tone for work email                       |
   | Ctrl+3 | Sarcastic    | Dry, witty, playful sarcasm                               |
   | Ctrl+4 | Diplomatic   | Softens blunt or negative wording, stays clear            |
   | Ctrl+5 | Confident    | Direct and assertive, removes "just", "sorry to bother"…  |

   Every tone also fixes spelling and grammar.

3. Wait for the tooltip to disappear. The selection is replaced with the result.

**No text selected?** The key or click is passed straight through to the app, so normal shortcuts
keep working: Ctrl+1–5 in Outlook, Teams and browser tabs, and Ctrl+click to open links,
multi-select or Ctrl+drag. Because TextFixer first checks for a selection, these take about 0.3 s
longer than usual.

Your clipboard is restored afterwards. Right-click the tray icon → **Show hotkeys** to see the
current list.

## Choosing the default tone

The default tone (used by Ctrl+Left click) is tone 1, Casual. To change it:

- Right-click the tray icon → **Default tone** → pick a tone. It is saved to `config.ini`.
- Or set `DEFAULT_PRESET` in `config.ini` to the tone's number, e.g. `DEFAULT_PRESET=2` for
  Professional, then **Reload config**.

To use a different click or key for the default, change `DEFAULT_HOTKEY` (e.g. `DEFAULT_HOTKEY=^!d`
for Ctrl+Alt+D). Leave it empty to turn it off.

The tone menu opens with `MENU_HOTKEY` (default `^RButton`, Ctrl+Right click). Change or empty it
the same way. If nothing is selected, the right-click goes to the app as normal.

Two hotkeys run **every tone at once** so you can compare before choosing:

- `PREVIEW_HOTKEY` (default `^+LButton`, Ctrl+Shift+Left click) opens a box next to the cursor
  with one tab per tone. Click a tab or press `1`–`9` to read that version, then **Use this**
  (or Enter) to replace your selection. **Cancel** or Esc leaves the text alone.
- `RESULTS_MENU_HOTKEY` (default `^+RButton`, Ctrl+Shift+Right click) opens one small window at the
  cursor with a row per tone, each showing the first 60 characters of its result. Hover a row to see
  the full text in a tooltip. Click a row (or press `1`–`9`) to use it; Cancel or Esc leaves the
  text alone.

Leave either setting empty to turn it off.

## Changing tones and hotkeys

Each tone has its own section in `config.ini`:

```ini
[Preset3]
NAME=Sarcastic
HOTKEY=^3
PROMPT=Rewrite the user's text with a dry, witty, sarcastic tone. ...
```

- `HOTKEY` uses AutoHotkey syntax: `^` = Ctrl, `!` = Alt, `+` = Shift, `#` = Win,
  `LButton` = left click. For example, `^3` = Ctrl+3 and `^!3` = Ctrl+Alt+3 (the old style).
- Leave `HOTKEY` empty (`HOTKEY=`) if a tone should only be used as the default.
- You can have up to 9 tones (`[Preset1]`…`[Preset9]`). Delete a section to remove a tone.
- Use `\n` for a line break inside a `PROMPT`.

After editing, right-click the tray icon → **Reload config**.

Other settings in `[Settings]`:

- `EXCLUDE_APPS`: apps where the hotkeys always act as normal shortcuts (comma-separated process
  names). The default is `EXCEL.EXE`, because Excel copies the active cell even when no text is
  selected, so Ctrl+1 (Format Cells) and Ctrl+click would otherwise be taken over.
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
- **Ctrl+click on a link rewrites text instead of opening the link**: this happens when text
  elsewhere in the same window is still selected. Click once to clear the selection first, or
  change `DEFAULT_HOTKEY`.
- **A hotkey rewrites text when nothing is selected**: some editors (e.g. VS Code) copy the whole
  line on Ctrl+C with no selection. Add that app to `EXCLUDE_APPS` (e.g. `EXCEL.EXE,Code.exe`).
- **Non-English characters in prompts look broken**: in Notepad, *Save As* `config.ini` with
  encoding **UTF-16 LE** (Windows INI files don't read UTF-8).
