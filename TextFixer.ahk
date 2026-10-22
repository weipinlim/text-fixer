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
; PREVIEW_HOTKEY (Ctrl+Shift+Left click) runs every tone at once and shows the results
; in a box next to the cursor (one tab per tone); pick one to replace the selection.
; RESULTS_MENU_HOTKEY (Ctrl+Shift+Right click) runs every tone at once and pops up the
; results as a menu at the cursor.
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
global PREVIEW_HOTKEY := IniRead(CONFIG_FILE, "Settings", "PREVIEW_HOTKEY", "^+LButton")
global RESULTS_HOTKEY := IniRead(CONFIG_FILE, "Settings", "RESULTS_MENU_HOTKEY", "^+RButton")
global MENU_HK        := ""
global RESULTS_HK     := ""
global PREVIEW_HK     := ""
global PREVIEW := ""  ; state of the open "pick a version" window, if any
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

if (PREVIEW_HOTKEY != "")
    PREVIEW_HK := BindHotkey(PREVIEW_HOTKEY, RunPreview, "[Settings] PREVIEW_HOTKEY")
if (RESULTS_HOTKEY != "")
    RESULTS_HK := BindHotkey(RESULTS_HOTKEY, RunResultsMenu, "[Settings] RESULTS_MENU_HOTKEY")

; While the preview box is the active window, 1-9 switch tabs
HotIf(PreviewActive)
Loop Min(PRESETS.Length, 9)
    Hotkey(String(A_Index), PreviewSelect.Bind(A_Index))
HotIf()

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
    if PREVIEW_HK
        text .= ReadableHotkey(PREVIEW_HK) " = show every tone in a box, then pick one`n"
    if RESULTS_HK
        text .= ReadableHotkey(RESULTS_HK) " = show every tone as a menu, then pick one`n"
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

; Send the selection to every tone at once; PollJob collects the answers
StartAll(original) {
    jobs := []
    for preset in PRESETS {
        job := {preset: preset, text: "", error: "", done: false, start: A_TickCount}
        try {
            job.http := StartRequest(original, preset.prompt, true)
        } catch as err {
            job.done := true
            job.error := err.Message
        }
        jobs.Push(job)
    }
    return jobs
}

; Check whether a job's answer has arrived; returns true once it is finished
PollJob(job) {
    if job.done
        return true
    try ready := job.http.WaitForResponse(0.01)
    catch
        ready := false
    if ready {
        job.done := true
        try job.text := Trim(FinishRequest(job.http), " `t`r`n")
        catch as err
            job.error := err.Message
    } else if (A_TickCount - job.start > TIMEOUT_SEC * 1000) {
        job.done := true
        job.error := "timed out"
    }
    return job.done
}

; Run every tone and pop the results up as a menu at the cursor
RunResultsMenu(hk, *) {
    global BUSY, MENU_OPEN, PENDING
    if (BUSY || MENU_OPEN || PREVIEW || IsExcludedApp()) {
        PassThrough(hk)
        return
    }
    original := CopySelection(&savedClip)
    if (original = "") {
        PassThrough(hk)
        return
    }

    BUSY := true
    ToolTip("Running all tones...")
    jobs := StartAll(original)
    Loop {
        waiting := false
        for job in jobs
            if !PollJob(job)
                waiting := true
        if !waiting
            break
        Sleep(100)
    }
    ToolTip()
    BUSY := false

    m := Menu()
    for job in jobs {
        label := job.preset.index ". " job.preset.name ":  "
        if (job.error != "") {
            m.Add(label "(failed: " Snippet(job.error) ")", (*) => 0)
            m.Disable(label "(failed: " Snippet(job.error) ")")
        } else
            m.Add(label Snippet(job.text), PickResult.Bind(job))
    }
    m.Add()
    m.Add("Cancel", (*) => 0)

    PENDING := {original: original, savedClip: savedClip}
    if hk.isMouse
        KeyWait(hk.key, "T1")
    MENU_OPEN := true
    m.Show()
    MENU_OPEN := false
    Sleep(100)
    if PENDING {  ; dismissed without choosing
        A_Clipboard := PENDING.savedClip
        PENDING := ""
    }
}

PickResult(job, *) {
    global PENDING
    if !PENDING
        return
    state := PENDING
    PENDING := ""
    PasteText(MatchWhitespace(job.text, state.original), state.savedClip)
}

; One line, at most 60 characters; & is doubled because menus treat it as a shortcut marker
Snippet(text) {
    text := Trim(RegExReplace(text, "\s+", " "))
    if (StrLen(text) > 60)
        text := SubStr(text, 1, 57) "..."
    return StrReplace(text, "&", "&&")
}

; Run every tone and show the results in a box next to the cursor, one tab
; per tone; "Use this" pastes the shown version over the selection
RunPreview(hk, *) {
    global PREVIEW
    if (BUSY || MENU_OPEN || PREVIEW || IsExcludedApp()) {
        PassThrough(hk)
        return
    }
    original := CopySelection(&savedClip)
    if (original = "") {
        PassThrough(hk)
        return
    }

    winId := WinExist("A")
    CoordMode("Mouse", "Screen")
    MouseGetPos(&mx, &my)
    width := 660
    g := Gui("+AlwaysOnTop +ToolWindow", "TextFixer - 1-" PRESETS.Length " or click a tab, Enter to use")
    g.SetFont("s10")
    jobs := StartAll(original)
    tabs := []
    btnWidth := Min(130, (width - 4 * (PRESETS.Length - 1)) // PRESETS.Length)
    for job in jobs {
        btn := g.AddButton((A_Index = 1 ? "xm" : "x+4") " w" btnWidth, "")
        btn.OnEvent("Click", PreviewSelect.Bind(A_Index))
        tabs.Push(btn)
    }
    edit := g.AddEdit("xm w" width " r4 ReadOnly +VScroll", "")
    use := g.AddButton("xm w110 Default", "Use this")
    use.OnEvent("Click", PreviewUse)
    g.AddButton("x+8 w90", "Cancel").OnEvent("Click", PreviewClose)
    g.OnEvent("Close", PreviewClose)
    g.OnEvent("Escape", PreviewClose)

    PREVIEW := {gui: g, jobs: jobs, tabs: tabs, edit: edit, use: use, sel: 1
        , original: original, savedClip: savedClip, winId: winId}
    PreviewSelect(1)
    ShowNearCursor(g, mx, my)
    SetTimer(PreviewPoll, 200)
}

; Show a window just below-right of the cursor, kept inside the screen it is on
; (above the cursor if there is no room below)
ShowNearCursor(g, mx, my) {
    g.Show("Hide")
    g.GetPos(, , &w, &h)
    left := 0, top := 0, right := A_ScreenWidth, bottom := A_ScreenHeight
    Loop MonitorGetCount() {
        MonitorGetWorkArea(A_Index, &l, &t, &r, &b)
        if (mx >= l && mx < r && my >= t && my < b) {
            left := l, top := t, right := r, bottom := b
            break
        }
    }
    x := Max(left, Min(mx + 10, right - w))
    y := (my + 20 + h <= bottom) ? my + 20 : Max(top, my - 10 - h)
    g.Show("x" x " y" y)
}

PreviewActive(*) {
    return PREVIEW && WinActive("ahk_id " PREVIEW.gui.Hwnd)
}

; Show tab i: its text (or error / "Working...") and mark it as the selected one
PreviewSelect(i, *) {
    if !PREVIEW || i > PREVIEW.jobs.Length
        return
    PREVIEW.sel := i
    for j, btn in PREVIEW.tabs {
        name := PREVIEW.jobs[j].preset.index " " PREVIEW.jobs[j].preset.name
        btn.Text := (j = i) ? "[" name "]" : name
    }
    job := PREVIEW.jobs[i]
    if (job.error != "")
        text := "Error: " job.error
    else if job.done
        text := job.text
    else
        text := "Working..."
    PREVIEW.edit.Value := StrReplace(StrReplace(text, "`r`n", "`n"), "`n", "`r`n")  ; Edit controls need CRLF
    PREVIEW.use.Enabled := job.done && job.error = ""
}

PreviewPoll() {
    if !PREVIEW {
        SetTimer(PreviewPoll, 0)
        return
    }
    pending := false
    changed := false
    for job in PREVIEW.jobs {
        was := job.done
        if !PollJob(job)
            pending := true
        else if !was
            changed := true
    }
    if changed
        PreviewSelect(PREVIEW.sel)
    if !pending
        SetTimer(PreviewPoll, 0)
}

PreviewUse(*) {
    global PREVIEW
    state := PREVIEW
    job := state.jobs[state.sel]
    if (!job.done || job.error != "")
        return
    PREVIEW := ""
    state.gui.Destroy()
    ; Back to the app the text was selected in, then paste over the selection
    WinActivate(state.winId)
    WinWaitActive(state.winId, , 2)
    PasteText(MatchWhitespace(job.text, state.original), state.savedClip)
}

PreviewClose(*) {
    global PREVIEW
    if !PREVIEW
        return
    state := PREVIEW
    PREVIEW := ""
    state.gui.Destroy()
    A_Clipboard := state.savedClip
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
    if (BUSY || MENU_OPEN || PREVIEW || IsExcludedApp()) {
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
    if (BUSY || MENU_OPEN || PREVIEW || IsExcludedApp()) {
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

    PasteText(MatchWhitespace(fixed, original), savedClip)
    BUSY := false
}

; Keep the original trailing whitespace/newline and use Windows line endings
MatchWhitespace(fixed, original) {
    fixed := Trim(fixed, " `t`r`n")
    if RegExMatch(original, "\s+$", &tail)
        fixed .= tail[0]
    return StrReplace(StrReplace(fixed, "`r`n", "`n"), "`n", "`r`n")
}

; Paste text over the selection, then put the user's clipboard back
PasteText(text, savedClip) {
    A_Clipboard := text
    ClipWait(1)
    Send("^v")
    Sleep(500)
    A_Clipboard := savedClip
}

CallLLM(text, prompt) {
    return FinishRequest(StartRequest(text, prompt, false))
}

; Send the chat request; with async=true it returns at once and FinishRequest
; reads the answer after http.WaitForResponse() reports it has arrived
StartRequest(text, prompt, async) {
    body := '{"model":' JsonEscape(MODEL)
        . ',"messages":[{"role":"system","content":' JsonEscape(prompt) '}'
        . ',{"role":"user","content":' JsonEscape(text) '}]'
        . ',"temperature":' TEMPERATURE ',"stream":false}'

    http := ComObject("WinHttp.WinHttpRequest.5.1")
    http.SetTimeouts(5000, 5000, 30000, TIMEOUT_SEC * 1000)
    http.Open("POST", API_URL, async)
    http.SetRequestHeader("Content-Type", "application/json")
    if (API_KEY != "")
        http.SetRequestHeader("Authorization", "Bearer " API_KEY)
    http.Send(body)
    return http
}

FinishRequest(http) {
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
