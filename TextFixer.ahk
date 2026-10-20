#Requires AutoHotkey v2.0
#SingleInstance Force

; TextFixer - select text anywhere, press a preset hotkey, and the text is replaced
; with a rewritten version from your OpenAI-compatible (vLLM) server.
; If nothing is selected, the hotkey is passed through to the app unchanged.
; All settings live in config.ini next to this script (or the compiled .exe).

global CONFIG_FILE := A_ScriptDir "\config.ini"
global MAX_PRESETS := 9

if !FileExist(CONFIG_FILE) {
    MsgBox("config.ini not found in:`n" A_ScriptDir "`n`nCopy config.example.ini to config.ini and fill in your settings.", "TextFixer", "Icon!")
    ExitApp
}

global API_URL       := IniRead(CONFIG_FILE, "Settings", "API_URL", "")
global API_KEY       := IniRead(CONFIG_FILE, "Settings", "API_KEY", "")
global MODEL         := IniRead(CONFIG_FILE, "Settings", "MODEL", "")
global TEMPERATURE   := IniRead(CONFIG_FILE, "Settings", "TEMPERATURE", "0.2")
global TIMEOUT_SEC   := IniRead(CONFIG_FILE, "Settings", "TIMEOUT", "60")
global SELECTION_MS  := IniRead(CONFIG_FILE, "Settings", "SELECTION_WAIT_MS", "300")
global EXCLUDE_APPS  := IniRead(CONFIG_FILE, "Settings", "EXCLUDE_APPS", "")

if !IsNumber(TEMPERATURE)
    TEMPERATURE := "0.2"
if !IsInteger(TIMEOUT_SEC)
    TIMEOUT_SEC := 60
if !IsInteger(SELECTION_MS)
    SELECTION_MS := 300

if (API_URL = "" || MODEL = "") {
    MsgBox("API_URL and MODEL must be set in config.ini.", "TextFixer", "Icon!")
    ExitApp
}

; [Default] is the plain fix (Ctrl+click unless changed); [Preset1] .. [Preset9]
; are tones. Each has NAME, HOTKEY and PROMPT; an empty HOTKEY disables it.
; (SYSTEM_PROMPT in [Settings] is still read so older config.ini files keep working)
global DEFAULT_PROMPT := IniRead(CONFIG_FILE, "Default", "PROMPT"
    , IniRead(CONFIG_FILE, "Settings", "SYSTEM_PROMPT"
    , "Fix spelling, grammar and punctuation in the user's text. Keep the meaning, tone and language. Return only the corrected text."))
global PRESETS := [{
    name:   IniRead(CONFIG_FILE, "Default", "NAME", "Fix grammar"),
    hotkey: IniRead(CONFIG_FILE, "Default", "HOTKEY", "^LButton"),
    prompt: DEFAULT_PROMPT
}]
Loop MAX_PRESETS {
    section := "Preset" A_Index
    PRESETS.Push({
        name:   IniRead(CONFIG_FILE, section, "NAME", section),
        hotkey: IniRead(CONFIG_FILE, section, "HOTKEY", ""),
        prompt: IniRead(CONFIG_FILE, section, "PROMPT", DEFAULT_PROMPT)
    })
}

global BUSY := false
summary := ""
for preset in PRESETS {
    if (preset.hotkey = "")
        continue
    ; Allow line breaks in prompts via \n
    preset.prompt := StrReplace(preset.prompt, "\n", "`n")
    RegExMatch(preset.hotkey, "^([~$*<>^!+#]*)(.+)$", &m)
    preset.mods := RegExReplace(m[1], "[~$*<>]")
    preset.key := m[2]
    preset.isMouse := RegExMatch(preset.key, "i)^(LButton|RButton|MButton|XButton1|XButton2)$")
    ; $ = keyboard hook, so passing the key through doesn't re-trigger the hotkey
    ; (mouse hotkeys always use the hook)
    key := (preset.isMouse || InStr(preset.hotkey, "$")) ? preset.hotkey : "$" preset.hotkey
    try Hotkey(key, RunPreset.Bind(preset))
    catch {
        MsgBox("Invalid HOTKEY in config.ini: " preset.hotkey, "TextFixer", "Icon!")
        ExitApp
    }
    summary .= ReadableHotkey(preset) " = " preset.name "`n"
}

A_IconTip := "TextFixer"
A_TrayMenu.Add()
A_TrayMenu.Add("Show hotkeys", (*) => MsgBox(summary, "TextFixer hotkeys"))
A_TrayMenu.Add("Edit config.ini", (*) => Run('notepad.exe "' CONFIG_FILE '"'))
A_TrayMenu.Add("Reload config", (*) => Reload())
TrayTip("Running. Select text and press a hotkey:`n" summary, "TextFixer")

; "^LButton" -> "Ctrl+Left click", "^1" -> "Ctrl+1"
ReadableHotkey(preset) {
    static names := Map("^", "Ctrl+", "!", "Alt+", "+", "Shift+", "#", "Win+")
    static buttons := Map("LButton", "Left click", "RButton", "Right click", "MButton", "Middle click")
    text := ""
    Loop Parse, preset.mods
        text .= names[A_LoopField]
    return text (buttons.Has(preset.key) ? buttons[preset.key] : StrUpper(preset.key))
}

; Give the app the key or click the hotkey intercepted, as if TextFixer wasn't running
PassThrough(preset) {
    if !preset.isMouse {
        Send(preset.mods "{" preset.key "}")
        return
    }
    ; Hold the button for as long as the user does, so Ctrl+drag still works
    Send("{Blind}" preset.mods "{" preset.key " down}")
    KeyWait(preset.key)
    Send("{Blind}{" preset.key " up}")
}

IsExcludedApp() {
    if (EXCLUDE_APPS = "")
        return false
    try proc := WinGetProcessName("A")
    catch
        return false
    for app in StrSplit(EXCLUDE_APPS, ",", " `t")
        if (app != "" && app = proc)
            return true
    return false
}

RunPreset(preset, *) {
    global BUSY
    if (BUSY || IsExcludedApp()) {
        PassThrough(preset)
        return
    }

    ; Copy the selection; if no text gets copied (nothing selected, or files
    ; selected in Explorer), let the app handle the key/click normally
    savedClip := ClipboardAll()
    A_Clipboard := ""
    Send("^c")
    if !ClipWait(SELECTION_MS / 1000) || DllCall("IsClipboardFormatAvailable", "UInt", 15) {  ; 15 = CF_HDROP
        A_Clipboard := savedClip
        PassThrough(preset)
        return
    }
    original := A_Clipboard

    BUSY := true
    ToolTip(preset.name "...")
    try {
        fixed := CallLLM(original, preset.prompt)
    } catch as err {
        ToolTip()
        A_Clipboard := savedClip
        BUSY := false
        MsgBox("Request failed:`n`n" err.Message, "TextFixer", "Iconx")
        return
    }
    ToolTip()

    ; Keep the original trailing whitespace/newline and use Windows line endings
    fixed := Trim(fixed, " `t`r`n")
    if RegExMatch(original, "\s+$", &tail)
        fixed .= tail[0]
    fixed := StrReplace(StrReplace(fixed, "`r`n", "`n"), "`n", "`r`n")

    A_Clipboard := fixed
    ClipWait(1)
    Send("^v")
    Sleep(500)
    A_Clipboard := savedClip
    BUSY := false
}

CallLLM(text, prompt) {
    body := '{"model":' JsonEscape(MODEL)
        . ',"messages":[{"role":"system","content":' JsonEscape(prompt) '}'
        . ',{"role":"user","content":' JsonEscape(text) '}]'
        . ',"temperature":' TEMPERATURE ',"stream":false}'

    http := ComObject("WinHttp.WinHttpRequest.5.1")
    http.SetTimeouts(5000, 5000, 30000, TIMEOUT_SEC * 1000)
    http.Open("POST", API_URL, false)
    http.SetRequestHeader("Content-Type", "application/json")
    if (API_KEY != "")
        http.SetRequestHeader("Authorization", "Bearer " API_KEY)
    http.Send(body)

    response := ReadUtf8Body(http)
    if (http.Status != 200)
        throw Error("HTTP " http.Status "`n" SubStr(response, 1, 500))

    content := ExtractContent(response)
    ; Drop reasoning blocks some models emit before the answer
    return RegExReplace(content, "s)^\s*<think>.*?</think>\s*")
}

; Decode the raw response bytes as UTF-8 (ResponseText may guess the wrong charset)
ReadUtf8Body(http) {
    bytes := http.ResponseBody
    size := bytes.MaxIndex() + 1
    if (size <= 0)
        return ""
    pData := NumGet(ComObjValue(bytes), 8 + A_PtrSize, "Ptr")
    return StrGet(pData, size, "UTF-8")
}

; Build a JSON string literal; non-ASCII is sent as \uXXXX so the body is plain ASCII
JsonEscape(str) {
    out := '"'
    p := StrPtr(str)
    Loop StrLen(str) {
        c := NumGet(p, (A_Index - 1) * 2, "UShort")
        if (c = 0x22)
            out .= '\"'
        else if (c = 0x5C)
            out .= '\\'
        else if (c >= 0x20 && c < 0x7F)
            out .= Chr(c)
        else
            out .= Format("\u{:04X}", c)
    }
    return out '"'
}

; Pull choices[0].message.content out of the chat completion response
ExtractContent(json) {
    pos := InStr(json, '"message"')
    if !pos || !RegExMatch(json, '"content"\s*:\s*"', &m, pos)
        throw Error("Unexpected response:`n" SubStr(json, 1, 500))

    out := ""
    i := m.Pos + m.Len
    len := StrLen(json)
    while (i <= len) {
        ch := SubStr(json, i, 1)
        if (ch = '"')
            return out
        if (ch != "\") {
            out .= ch
            i++
            continue
        }
        esc := SubStr(json, i + 1, 1)
        switch esc {
            case "n": out .= "`n"
            case "r": out .= "`r"
            case "t": out .= "`t"
            case "b": out .= "`b"
            case "f": out .= "`f"
            case "u":
                code := Integer("0x" SubStr(json, i + 2, 4))
                i += 4
                ; Combine a UTF-16 surrogate pair into one character
                if (code >= 0xD800 && code <= 0xDBFF && SubStr(json, i + 2, 2) = "\u") {
                    low := Integer("0x" SubStr(json, i + 4, 4))
                    code := 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                    i += 6
                }
                out .= Chr(code)
            default: out .= esc  ; \" \\ \/
        }
        i += 2
    }
    throw Error("Malformed response:`n" SubStr(json, 1, 500))
}
