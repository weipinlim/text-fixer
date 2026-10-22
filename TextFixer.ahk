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

; Tone presets: [Preset1] .. [Preset9], each with NAME, HOTKEY and PROMPT
; (an empty HOTKEY means the tone is only used via the default hotkey).
; DEFAULT_HOTKEY (Ctrl+Left click) runs the tone chosen by DEFAULT_PRESET.
; MENU_HOTKEY (Ctrl+Right click) shows a menu to pick any tone.
global FALLBACK_PROMPT := "Fix spelling, grammar and punctuation in the user's text. Keep the meaning, tone and language. Return only the corrected text."
global PRESETS := []
Loop MAX_PRESETS {
    section := "Preset" A_Index
    name := IniRead(CONFIG_FILE, section, "NAME", "")
    prompt := IniRead(CONFIG_FILE, section, "PROMPT", "")
    if (name = "" && prompt = "")
        continue
    ; Allow line breaks in prompts via \n
    PRESETS.Push({
        index:  A_Index,
        name:   name != "" ? name : section,
        hotkey: IniRead(CONFIG_FILE, section, "HOTKEY", ""),
        prompt: StrReplace(prompt != "" ? prompt : FALLBACK_PROMPT, "\n", "`n")
    })
}
if (PRESETS.Length = 0) {
    MsgBox("No presets found in config.ini. Copy the [Preset1] .. [Preset5] sections from config.example.ini.", "TextFixer", "Icon!")
    ExitApp
}

global DEFAULT_HOTKEY := IniRead(CONFIG_FILE, "Settings", "DEFAULT_HOTKEY", "^LButton")
global DEFAULT_INDEX  := IniRead(CONFIG_FILE, "Settings", "DEFAULT_PRESET", "1")
global MENU_HOTKEY    := IniRead(CONFIG_FILE, "Settings", "MENU_HOTKEY", "^RButton")
global DEFAULT_HK     := ""
global MENU_HK        := ""
global BUSY := false
global MENU_OPEN := false
global PENDING := ""  ; selection waiting for a pick from the tone menu

for preset in PRESETS
    if (preset.hotkey != "")
        preset.hk := BindHotkey(preset.hotkey, RunPreset.Bind(preset), "[Preset" preset.index "] HOTKEY")
if (DEFAULT_HOTKEY != "")
    DEFAULT_HK := BindHotkey(DEFAULT_HOTKEY, (hk, *) => RunPreset(DefaultPreset(), hk), "[Settings] DEFAULT_HOTKEY")

; Tone menu: MENU_HOTKEY (Ctrl+Right click) pops up a list of tones at the cursor
global ToneMenu := Menu()
for preset in PRESETS
    ToneMenu.Add(preset.index ". " preset.name, PickTone.Bind(preset))
if (MENU_HOTKEY != "")
    MENU_HK := BindHotkey(MENU_HOTKEY, RunMenu, "[Settings] MENU_HOTKEY")

; Tray menu: pick the default tone (saved to config.ini)
global DefaultMenu := Menu()
for preset in PRESETS
    DefaultMenu.Add(preset.index ". " preset.name, SetDefault.Bind(preset))
UpdateDefaultMenu()

A_IconTip := "TextFixer"
A_TrayMenu.Add()
A_TrayMenu.Add("Default tone" (DEFAULT_HK ? " (" ReadableHotkey(DEFAULT_HK) ")" : ""), DefaultMenu)
A_TrayMenu.Add("Show hotkeys", (*) => MsgBox(HotkeySummary(), "TextFixer hotkeys"))
A_TrayMenu.Add("Edit config.ini", (*) => Run('notepad.exe "' CONFIG_FILE '"'))
A_TrayMenu.Add("Reload config", (*) => Reload())
TrayTip("Running. Select text and press a hotkey:`n" HotkeySummary(), "TextFixer")

DefaultPreset() {
    for preset in PRESETS
        if (preset.index = DEFAULT_INDEX)
            return preset
    return PRESETS[1]
}

SetDefault(preset, *) {
    global DEFAULT_INDEX := preset.index
    IniWrite(preset.index, CONFIG_FILE, "Settings", "DEFAULT_PRESET")
    UpdateDefaultMenu()
}

UpdateDefaultMenu() {
    current := DefaultPreset()
    for preset in PRESETS {
        item := preset.index ". " preset.name
        (preset.index = current.index) ? DefaultMenu.Check(item) : DefaultMenu.Uncheck(item)
    }
}

HotkeySummary() {
    text := DEFAULT_HK ? ReadableHotkey(DEFAULT_HK) " = " DefaultPreset().name " (default)`n" : ""
    if MENU_HK
        text .= ReadableHotkey(MENU_HK) " = choose a tone from a menu`n"
    for preset in PRESETS
        if preset.HasOwnProp("hk")
            text .= ReadableHotkey(preset.hk) " = " preset.name "`n"
    return text
}

; Register a hotkey; returns its parsed form (modifiers + key) for pass-through
BindHotkey(spec, callback, where) {
    RegExMatch(spec, "^([~$*<>^!+#]*)(.+)$", &m)
    hk := {mods: RegExReplace(m[1], "[~$*<>]"), key: m[2]}
    hk.isMouse := RegExMatch(hk.key, "i)^(LButton|RButton|MButton|XButton1|XButton2)$")
    ; $ = keyboard hook, so passing the key through doesn't re-trigger the hotkey
    ; (mouse hotkeys always use the hook)
    key := (hk.isMouse || InStr(spec, "$")) ? spec : "$" spec
    try Hotkey(key, callback.Bind(hk))
    catch as err {
        MsgBox("Invalid hotkey in config.ini`n`n" where "=" spec "`n`n" err.Message, "TextFixer", "Icon!")
        ExitApp
    }
    return hk
}

; "^LButton" -> "Ctrl+Left click", "^1" -> "Ctrl+1"
ReadableHotkey(hk) {
    static names := Map("^", "Ctrl+", "!", "Alt+", "+", "Shift+", "#", "Win+")
    static buttons := Map("LButton", "Left click", "RButton", "Right click", "MButton", "Middle click")
    text := ""
    Loop Parse, hk.mods
        text .= names[A_LoopField]
    return text (buttons.Has(hk.key) ? buttons[hk.key] : StrUpper(hk.key))
}

; Give the app the key or click the hotkey intercepted, as if TextFixer wasn't running
PassThrough(hk) {
    if !hk.isMouse {
        Send(hk.mods "{" hk.key "}")
        return
    }
    ; Hold the button for as long as the user does, so Ctrl+drag still works
    Send("{Blind}" hk.mods "{" hk.key " down}")
    KeyWait(hk.key)
    Send("{Blind}{" hk.key " up}")
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

; Copy the selection; if no text gets copied (nothing selected, or files
; selected in Explorer), return "" so the caller lets the app handle the key/click
CopySelection(&savedClip) {
    savedClip := ClipboardAll()
    A_Clipboard := ""
    Send("^c")
    if !ClipWait(SELECTION_MS / 1000) || DllCall("IsClipboardFormatAvailable", "UInt", 15) {  ; 15 = CF_HDROP
        A_Clipboard := savedClip
        return ""
    }
    return A_Clipboard
}

RunPreset(preset, hk, *) {
    if (BUSY || MENU_OPEN || IsExcludedApp()) {
        PassThrough(hk)
        return
    }
    original := CopySelection(&savedClip)
    if (original = "") {
        PassThrough(hk)
        return
    }
    ApplyTone(preset, original, savedClip)
}

; Show the tone menu at the cursor; the chosen tone is applied by PickTone
RunMenu(hk, *) {
    global MENU_OPEN, PENDING
    if (BUSY || MENU_OPEN || IsExcludedApp()) {
        PassThrough(hk)
        return
    }
    original := CopySelection(&savedClip)
    if (original = "") {
        PassThrough(hk)
        return
    }
    PENDING := {original: original, savedClip: savedClip}
    ; Let go of the mouse button first so releasing it doesn't pick a menu item
    if hk.isMouse
        KeyWait(hk.key, "T1")
    MENU_OPEN := true
    ToneMenu.Show()
    MENU_OPEN := false
    ; The menu's callback runs as its own thread; give it a moment to claim PENDING
    Sleep(100)
    if PENDING {  ; dismissed without choosing
        A_Clipboard := PENDING.savedClip
        PENDING := ""
    }
}

PickTone(preset, *) {
    global PENDING
    if !PENDING
        return
    job := PENDING
    PENDING := ""
    ApplyTone(preset, job.original, job.savedClip)
}

ApplyTone(preset, original, savedClip) {
    global BUSY
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
