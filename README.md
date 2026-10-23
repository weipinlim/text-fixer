# TextFixer

Fix or rewrite selected text in any Windows app with one hotkey. TextFixer sends the selection to
your LLM and pastes the result back in place. It works with any OpenAI-compatible server (vLLM,
llama.cpp, LM Studio, ChatGPT...), Google Gemini and Ollama.

Besides rewriting, it can summarize, list key points or make a table in a result window with
follow-up chat, run every tone at once so you can pick the best, take a free-form instruction
("translate to French"), and explain a word in a tooltip.

## Setup

1. Install [AutoHotkey v2](https://www.autohotkey.com/) (not needed if you use a compiled `TextFixer.exe`).
2. Download or clone this repo:
   ```
   git clone https://github.com/weipinlim/text-fixer.git
   ```
3. Double-click `TextFixer.ahk` (keep the `lib` folder next to it). The first time, it creates
   `config.ini` from `config.example.ini` and opens the **Settings** window. Fill in:
   - **Provider**: `openai` (vLLM, llama.cpp, LM Studio, ChatGPT...), `gemini` or `ollama`
   - **API URL**: for `openai`, your server's chat endpoint, e.g.
     `http://192.168.1.10:8000/v1/chat/completions`. Leave it empty for `gemini` and `ollama`.
   - **API key**: your key (leave empty if the server has none)
   - **Model**: the model name, e.g. as listed at `http://YOUR_SERVER:8000/v1/models`

   Press **Save**; the script reloads and a green **H** icon appears in the system tray.
   You can reopen Settings any time from the tray icon, or edit `config.ini` directly.

`config.ini` is in `.gitignore`, so your real key is never uploaded.

## Usage

1. Select text in any app (email, Word, browser, chat…).
2. Hold **Ctrl** and **left-click** the selection to rewrite it in your **default tone**,
   **Ctrl+right-click** to pick any tone from a menu at the cursor,
   **Ctrl+Shift+left-click** to see every tone's result in a box next to the cursor (one tab each) and pick
   one, **Ctrl+Shift+right-click** to see every tone in one list at the cursor (hover for the full text),
   **Ctrl+Shift+Space** for a popup with a "describe your change" box and a button per tone,
   or press a tone hotkey:

   | Hotkey | Tone         | What it does                                              |
   |--------|--------------|-----------------------------------------------------------|
   | Ctrl+1 | Casual       | Relaxed, conversational (**default** for Ctrl+Left click) |
   | Ctrl+2 | Professional | Polite business tone for work email                       |
   | Ctrl+3 | Sarcastic    | Dry, witty, playful sarcasm                               |
   | Ctrl+4 | Diplomatic   | Softens blunt or negative wording, stays clear            |
   | Ctrl+5 | Confident    | Direct and assertive, removes "just", "sorry to bother"…  |
   | Ctrl+6 | Summary      | Shows a summary in a result window (follow-up chat)        |
   | Ctrl+7 | Key Points   | Shows the key points in a result window                    |
   | Ctrl+8 | Table        | Shows the text as a table in a result window               |

   Tones 1-5 also fix spelling and grammar. Tones 6-8 open the result window instead of
   replacing your text.

3. Wait for the tooltip to disappear. The selection is replaced with the result. If the model
   decides the text can't be processed (for example random gibberish), nothing is pasted and a
   tooltip says so.

**No text selected?** The key or click is passed straight through to the app, so normal shortcuts
keep working: Ctrl+1–5 in Outlook, Teams and browser tabs, and Ctrl+click to open links,
multi-select or Ctrl+drag. Because TextFixer first checks for a selection, these take about 0.3 s
longer than usual.

Your clipboard is restored afterwards. Right-click the tray icon → **Show hotkeys** to see the
current list. The tray menu also has **Chat window**, **Settings...**, **Pause hotkeys** (turns all
hotkeys off and on) and **Start with Windows**.

## Popup, result window and chat

- **Popup** (`POPUP_HOTKEY`, default `^+Space`, Ctrl+Shift+Space): opens next to the cursor. Type
  what you want changed ("translate to French", "add code comments", "make it shorter") and press
  Enter, or click one of the tone buttons. Click elsewhere or press Esc to close it.
- **Result window**: tones with `MODE=window` (Summary, Key Points, Table by default) show the answer
  here, formatted as Markdown (headings, lists, tables, code). Type a follow-up question in the box
  at the bottom and press Enter; the whole conversation is sent each time. **Copy last answer**
  copies the Markdown text. If the embedded browser can't be used on your PC, the same content is
  shown as plain text.
- **Chat window** (`CHAT_HOTKEY`, default `^!Space`, Ctrl+Alt+Space, or the tray menu): the same
  window with no selection needed, for a general chat. The history is dropped when you close it.

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

## Explaining a word

Select a word, phrase or sentence you don't understand and **Ctrl+middle-click** it
(`EXPLAIN_HOTKEY`, default `^MButton`). TextFixer asks the LLM to explain it and shows the answer
in a tooltip next to the cursor. Nothing in your document is changed. Click anywhere, press Esc, or
wait `EXPLAIN_SECONDS` (default 30) to dismiss it. To change what the LLM is asked, set
`EXPLAIN_PROMPT` in `[Settings]`. If nothing is selected, the middle click goes to the app as normal.

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
- `PROVIDER`, `API_URL`, `API_KEY`, `MODEL`, `TEMPERATURE`, `TIMEOUT`: connection settings (the
  Settings window edits these). For `gemini` and `ollama` an empty `API_URL` uses the standard
  address (`https://generativelanguage.googleapis.com/...` and `http://localhost:11434/api/chat`).
- Per tone, `MODE=window` shows the answer in the result window instead of replacing the text.

## Make a standalone .exe (optional)

So you can run it on PCs without AutoHotkey:

1. Right-click `TextFixer.ahk` → **Compile Script** (or open *Ahk2Exe* from the AutoHotkey Dash).
   The files in `lib` are included automatically.
2. Put `config.example.ini` in the same folder as `TextFixer.exe` (the first run creates `config.ini`
   from it), or put your own `config.ini` there.
3. Double-click `TextFixer.exe`.

To start it automatically with Windows, use the tray menu → **Start with Windows**.

## Troubleshooting

- **"config.ini not found"**: `config.example.ini` is missing next to the script/exe. Put it back,
  or create `config.ini` yourself.
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
