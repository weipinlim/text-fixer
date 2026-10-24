#Requires AutoHotkey v2.0
#SingleInstance Force
;@Ahk2Exe-SetName TextFixer
;@Ahk2Exe-SetDescription TextFixer
;@Ahk2Exe-SetCompanyName TextFixer
;@Ahk2Exe-SetCopyright TextFixer
;@Ahk2Exe-SetOrigFilename TextFixer.exe
;@Ahk2Exe-SetVersion 0.1.0

; TextFixer - select text anywhere, press a preset hotkey, and the text is replaced
; with a rewritten version from your LLM (OpenAI-compatible/vLLM, Gemini or Ollama).
; If nothing is selected, the hotkey is passed through to the app unchanged.
; All settings live in config.ini next to this script (or the compiled .exe).

#Include lib\Llm.ahk
#Include lib\Markdown.ahk
#Include lib\Windows.ahk

global CONFIG_FILE := A_ScriptDir "\config.ini"
global MAX_PRESETS := 9
global SETTINGS := ""  ; the open settings window, if any
global RESULT   := ""  ; the open result/chat window, if any
global POPUP    := ""  ; the open popup at the cursor, if any

; First run: create config.ini from the example and open the settings window
if !FileExist(CONFIG_FILE) {
    example := A_ScriptDir "\config.example.ini"
    if !FileExist(example) {
        MsgBox("config.ini not found in:`n" A_ScriptDir "`n`nCopy config.example.ini to config.ini and fill in your settings.", "TextFixer", "Icon!")
        ExitApp
    }
    FileCopy(example, CONFIG_FILE)
    ShowSettings(true)
    return
}

global API_URL       := IniRead(CONFIG_FILE, "Settings", "API_URL", "")
global API_KEY       := IniRead(CONFIG_FILE, "Settings", "API_KEY", "")
global MODEL         := IniRead(CONFIG_FILE, "Settings", "MODEL", "")
global TEMPERATURE   := IniRead(CONFIG_FILE, "Settings", "TEMPERATURE", "0.2")
global TIMEOUT_SEC   := IniRead(CONFIG_FILE, "Settings", "TIMEOUT", "60")
global SELECTION_MS  := IniRead(CONFIG_FILE, "Settings", "SELECTION_WAIT_MS", "300")
global EXCLUDE_APPS  := IniRead(CONFIG_FILE, "Settings", "EXCLUDE_APPS", "")
global PROVIDER      := StrLower(IniRead(CONFIG_FILE, "Settings", "PROVIDER", "ollama"))

if !IsNumber(TEMPERATURE)
    TEMPERATURE := "0.2"
if !IsInteger(TIMEOUT_SEC)
    TIMEOUT_SEC := 60
if !IsInteger(SELECTION_MS)
    SELECTION_MS := 300
global EXPLAIN_SECONDS := IniRead(CONFIG_FILE, "Settings", "EXPLAIN_SECONDS", "30")
if !IsInteger(EXPLAIN_SECONDS)
    EXPLAIN_SECONDS := 30
global EXPLAIN_PROMPT := IniRead(CONFIG_FILE, "Settings", "EXPLAIN_PROMPT", "")
if (EXPLAIN_PROMPT = "")
    EXPLAIN_PROMPT := "Explain the selected word, phrase or text briefly and simply, in the same language as the text. For a word, give its meaning and one short example sentence. Keep it under 80 words. Return only the explanation."
EXPLAIN_PROMPT := StrReplace(EXPLAIN_PROMPT, "\n", "`n")

if !InStr("|openai|gemini|ollama|", "|" PROVIDER "|") {
    MsgBox("PROVIDER in config.ini must be openai, gemini or ollama (it is '" PROVIDER "').", "TextFixer", "Icon!")
    ExitApp
}
if (MODEL = "" || (PROVIDER = "openai" && API_URL = "")) {
    MsgBox("MODEL (and API_URL for the openai provider) must be set in config.ini.`n`nRight-click the tray icon > Settings.", "TextFixer", "Icon!")
    ExitApp
}

; Appended to every tone's prompt: lets the model refuse nonsense instead of pasting it
global INCOMPATIBLE_MARK := "ERROR_TEXT_INCOMPATIBLE_WITH_REQUEST"
global INCOMPATIBLE_RULE := "If the text is absolutely incompatible with this request (for example random gibberish), output exactly " INCOMPATIBLE_MARK " and nothing else."
global CUSTOM_PROMPT := "You are a writing and coding assistant. Make the change the user describes to the text or code they give you. Output ONLY the modified text or code, without any extra comments. Respond in the same language as the input."
global FOLLOWUP_SYSTEM := "You are a helpful AI assistant. Answer clearly and directly, keep the same style as your earlier answers, and use Markdown where it helps readability."

; Tone presets: [Preset1] .. [Preset9], each with NAME, HOTKEY and PROMPT
; (an empty HOTKEY means the tone is only used via the default hotkey).
; DEFAULT_HOTKEY (Ctrl+Left click) runs the tone chosen by DEFAULT_PRESET.
; MENU_HOTKEY (Ctrl+Right click) shows a menu to pick any tone.
; PREVIEW_HOTKEY (Ctrl+Shift+Left click) runs every tone at once and shows the results
; in a box next to the cursor (one tab per tone); pick one to replace the selection.
; POPUP_HOTKEY (Ctrl+Shift+Space) opens a popup at the cursor: type a change or click a tone.
; CHAT_HOTKEY (Ctrl+Alt+Space) opens a chat window.
; EXPLAIN_HOTKEY (Ctrl+Middle click) explains the selected word or text in a tooltip
; (nothing is replaced).
; RESULTS_MENU_HOTKEY (Ctrl+Shift+Right click) runs every tone at once and lists the
; results in one window at the cursor (hover for the full text, click to use).
global FALLBACK_PROMPT := "Fix spelling, grammar and punctuation in the user's text. Keep the meaning, tone and language. Return only the corrected text."
global PRESETS := []  ; every [PresetN] section
global TONES   := []  ; the ones that replace your text (MODE=replace, the default)
Loop MAX_PRESETS {
    section := "Preset" A_Index
    name := IniRead(CONFIG_FILE, section, "NAME", "")
    prompt := IniRead(CONFIG_FILE, section, "PROMPT", "")
    if (name = "" && prompt = "")
        continue
    ; Allow line breaks in prompts via \n
    ; MODE=window shows the answer in the result window (with follow-up chat) instead
    ; of replacing the selection
    preset := {
        index:  A_Index,
        name:   name != "" ? name : section,
        hotkey: IniRead(CONFIG_FILE, section, "HOTKEY", ""),
        mode:   StrLower(IniRead(CONFIG_FILE, section, "MODE", "replace")),
        prompt: StrReplace(prompt != "" ? prompt : FALLBACK_PROMPT, "\n", "`n")
    }
    PRESETS.Push(preset)
    if (preset.mode != "window")
        TONES.Push(preset)
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
global EXPLAIN_HOTKEY := IniRead(CONFIG_FILE, "Settings", "EXPLAIN_HOTKEY", "^MButton")
global EXPLAIN_HK     := ""
global EXPLAIN_START  := 0  ; tick count while an explanation tooltip is showing
global RESULTS_HOTKEY := IniRead(CONFIG_FILE, "Settings", "RESULTS_MENU_HOTKEY", "^+RButton")
global POPUP_HOTKEY   := IniRead(CONFIG_FILE, "Settings", "POPUP_HOTKEY", "^+Space")
global CHAT_HOTKEY    := IniRead(CONFIG_FILE, "Settings", "CHAT_HOTKEY", "^!Space")
global POPUP_HK       := ""
global CHAT_HK        := ""
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

if (EXPLAIN_HOTKEY != "")
    EXPLAIN_HK := BindHotkey(EXPLAIN_HOTKEY, RunExplain, "[Settings] EXPLAIN_HOTKEY")
if (POPUP_HOTKEY != "")
    POPUP_HK := BindHotkey(POPUP_HOTKEY, RunPopup, "[Settings] POPUP_HOTKEY")
if (CHAT_HOTKEY != "")
    CHAT_HK := BindHotkey(CHAT_HOTKEY, RunChat, "[Settings] CHAT_HOTKEY")

; While the preview box is the active window, 1-9 switch tabs
HotIf(PreviewActive)
Loop Min(PRESETS.Length, 9)
    Hotkey(String(A_Index), PreviewSelect.Bind(A_Index))
HotIf()

; Tray menu: pick the default tone (saved to config.ini)
global DefaultMenu := Menu()
for preset in TONES
    DefaultMenu.Add(preset.index ". " preset.name, SetDefault.Bind(preset))
UpdateDefaultMenu()

A_IconTip := "TextFixer"
A_TrayMenu.Add()
A_TrayMenu.Add("Default tone" (DEFAULT_HK ? " (" ReadableHotkey(DEFAULT_HK) ")" : ""), DefaultMenu)
A_TrayMenu.Add("Chat window" (CHAT_HK ? " (" ReadableHotkey(CHAT_HK) ")" : ""), (*) => OpenResultWindow("Chat", "", ""))
A_TrayMenu.Add("Show hotkeys", (*) => MsgBox(HotkeySummary(), "TextFixer hotkeys"))
A_TrayMenu.Add("Settings...", (*) => ShowSettings())
A_TrayMenu.Add("Edit config.ini", (*) => Run('notepad.exe "' CONFIG_FILE '"'))
A_TrayMenu.Add("Reload config", (*) => Reload())
A_TrayMenu.Add("Pause hotkeys", TogglePause)
A_TrayMenu.Add("Start with Windows", ToggleStartup)
if FileExist(StartupLink())
    A_TrayMenu.Check("Start with Windows")
TrayTip("Running. Select text and press a hotkey:`n" HotkeySummary(), "TextFixer")
if (PROVIDER = "ollama")
    SetTimer(CheckOllama, -1000)

; Ollama: say so if it isn't running, and offer to download the model if it's missing
CheckOllama() {
    try models := OllamaModels(OllamaBase(API_URL))
    catch {
        TrayTip("Ollama isn't running. Start Ollama (or install it from ollama.com), then reload TextFixer.", "TextFixer", "Iconx")
        return
    }
    if HasModel(models, MODEL)
        return
    if (MsgBox("The model " MODEL " isn't downloaded yet.`n`nDownload it now? (a few GB, a window shows the progress)", "TextFixer", "YesNo Icon?") = "Yes")
        PullModel(MODEL)
}

; Tray: turn all hotkeys off and on (Suspend), and start with Windows (Startup shortcut)
TogglePause(*) {
    Suspend(-1)
    A_IsSuspended ? A_TrayMenu.Check("Pause hotkeys") : A_TrayMenu.Uncheck("Pause hotkeys")
}

StartupLink() {
    return A_Startup "\TextFixer.lnk"
}

ToggleStartup(*) {
    link := StartupLink()
    if FileExist(link) {
        FileDelete(link)
        A_TrayMenu.Uncheck("Start with Windows")
    } else {
        FileCreateShortcut(A_ScriptFullPath, link, A_ScriptDir)
        A_TrayMenu.Check("Start with Windows")
    }
}

DefaultPreset() {
    for preset in PRESETS
        if (preset.index = DEFAULT_INDEX)
            return preset
    return TONES.Length ? TONES[1] : PRESETS[1]
}

SetDefault(preset, *) {
    global DEFAULT_INDEX := preset.index
    IniWrite(preset.index, CONFIG_FILE, "Settings", "DEFAULT_PRESET")
    UpdateDefaultMenu()
}

UpdateDefaultMenu() {
    current := DefaultPreset()
    for preset in TONES {
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
    if EXPLAIN_HK
        text .= ReadableHotkey(EXPLAIN_HK) " = explain the selected word in a tooltip`n"
    if POPUP_HK
        text .= ReadableHotkey(POPUP_HK) " = popup: describe a change or pick a tone`n"
    if CHAT_HK
        text .= ReadableHotkey(CHAT_HK) " = open the chat window`n"
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

; Send the selection to every tone; PollJob collects the answers. A local Ollama
; answers one request at a time anyway, so there the tones run one after another
; (StartNextJob) and each result shows up as soon as it is ready.
StartAll(original) {
    jobs := []
    for preset in TONES {
        job := {preset: preset, original: original, http: "", text: "", error: "", done: false, start: 0}
        jobs.Push(job)
        if (PROVIDER != "ollama" || A_Index = 1)
            StartJob(job)
    }
    return jobs
}

StartJob(job) {
    job.start := A_TickCount
    try {
        job.http := StartRequest(job.original, job.preset.prompt " " INCOMPATIBLE_RULE, true)
    } catch as err {
        job.done := true
        job.error := err.Message
    }
}

; Start the next waiting tone once nothing is running (Ollama only)
StartNextJob(jobs) {
    for job in jobs
        if (job.start && !job.done)
            return
    for job in jobs
        if !job.start {
            StartJob(job)
            return
        }
}

; What a job shows while it has no result yet
JobStatus(job) {
    return job.start ? "Working..." : "Waiting for its turn..."
}

JobsReady(jobs) {
    n := 0
    for job in jobs
        n += job.done
    return n
}

; Check whether a job's answer has arrived; returns true once it is finished
PollJob(job) {
    if job.done
        return true
    if !job.start
        return false
    if HttpReady(job.http) {
        job.done := true
        try job.text := Trim(FinishRequest(job.http), " `t`r`n")
        catch as err
            job.error := err.Message
        if (job.text = INCOMPATIBLE_MARK) {
            job.text := ""
            job.error := "the text isn't compatible with this request"
        }
    } else if (A_TickCount - job.start > TIMEOUT_SEC * 1000) {
        job.done := true
        job.error := "timed out"
    }
    return job.done
}

; Run every tone and list the results in one small window at the cursor: each row
; shows the start of a result, hovering shows the full text, clicking uses it
RunResultsMenu(hk, *) {
    if (BUSY || MENU_OPEN || PREVIEW || IsExcludedApp()) {
        PassThrough(hk)
        return
    }
    original := CopySelection(&savedClip)
    if (original = "") {
        PassThrough(hk)
        return
    }
    OpenResultsList(original, savedClip)
}

OpenResultsList(original, savedClip) {
    global PREVIEW
    winId := WinExist("A")
    CoordMode("Mouse", "Screen")
    MouseGetPos(&mx, &my)
    g := Gui("+AlwaysOnTop +ToolWindow", "TextFixer - click one to use it (hover for the full text)")
    g.SetFont("s10")
    jobs := StartAll(original)
    rows := []
    for job in jobs {
        g.AddText("xm w120 h24 0x200", job.preset.index ". " job.preset.name)
        row := g.AddText("x+8 w520 h24 0x200 +0x100 +Border", JobStatus(job))
        row.OnEvent("Click", PreviewUseTone.Bind(A_Index))
        rows.Push(row)
    }
    g.AddButton("xm w90", "Cancel").OnEvent("Click", PreviewClose)
    g.OnEvent("Close", PreviewClose)
    g.OnEvent("Escape", PreviewClose)

    PREVIEW := {kind: "list", gui: g, jobs: jobs, rows: rows, tip: "", title: g.Title
        , original: original, savedClip: savedClip, winId: winId}
    PreviewRefreshRows()
    ShowNearCursor(g, mx, my)
    SetTimer(PreviewPoll, 200)
    SetTimer(PreviewHover, 100)
}

; Fill each row with the start of its result (or its error)
PreviewRefreshRows() {
    for i, job in PREVIEW.jobs {
        if (job.error != "")
            PREVIEW.rows[i].Text := "Error: " Snippet(job.error)
        else if job.done
            PREVIEW.rows[i].Text := Snippet(job.text)
        else
            PREVIEW.rows[i].Text := JobStatus(job)
    }
}

; Show the full text of the row under the mouse as a tooltip
PreviewHover() {
    if (!PREVIEW || PREVIEW.kind != "list") {
        SetTimer(PreviewHover, 0)
        return
    }
    MouseGetPos(, , , &hwnd, 2)
    full := ""
    for i, row in PREVIEW.rows {
        if (row.Hwnd = hwnd) {
            job := PREVIEW.jobs[i]
            full := job.error != "" ? "Error: " job.error : job.text
            break
        }
    }
    if (full = PREVIEW.tip)
        return
    PREVIEW.tip := full
    ToolTip(full = "" ? "" : WrapText(full, 80))
}

; Break long text into lines of about `width` characters (tooltips don't wrap by themselves)
WrapText(text, width) {
    out := ""
    for para in StrSplit(StrReplace(text, "`r`n", "`n"), "`n") {
        line := ""
        for word in StrSplit(para, " ") {
            if (line != "" && StrLen(line) + 1 + StrLen(word) > width) {
                out .= line "`n"
                line := word
            } else
                line := (line = "") ? word : line " " word
        }
        out .= line "`n"
    }
    return RTrim(out, "`n")
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
    if (BUSY || MENU_OPEN || PREVIEW || IsExcludedApp()) {
        PassThrough(hk)
        return
    }
    original := CopySelection(&savedClip)
    if (original = "") {
        PassThrough(hk)
        return
    }
    OpenPreview(original, savedClip)
}

OpenPreview(original, savedClip) {
    global PREVIEW
    winId := WinExist("A")
    CoordMode("Mouse", "Screen")
    MouseGetPos(&mx, &my)
    width := 660
    g := Gui("+AlwaysOnTop +ToolWindow", "TextFixer - 1-" TONES.Length " or click a tab, Enter to use")
    g.SetFont("s10")
    jobs := StartAll(original)
    tabs := []
    btnWidth := Min(130, (width - 4 * (jobs.Length - 1)) // jobs.Length)
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

    PREVIEW := {kind: "tabs", gui: g, jobs: jobs, tabs: tabs, edit: edit, use: use, sel: 1
        , picked: false, title: g.Title, original: original, savedClip: savedClip, winId: winId}
    PreviewShow(1)
    ShowNearCursor(g, mx, my)
    SetTimer(PreviewPoll, 200)
}

PreviewActive(*) {
    return PREVIEW && WinActive("ahk_id " PREVIEW.gui.Hwnd)
}

; You picked tab i (click or 1-9); the window stops switching tabs by itself
PreviewSelect(i, *) {
    if !PREVIEW || i > PREVIEW.jobs.Length
        return
    if (PREVIEW.kind = "list") {  ; the list window has no tabs: the number picks that tone
        PreviewUseTone(i)
        return
    }
    PREVIEW.picked := true
    PreviewShow(i)
}

; Show tab i: its text (or error / "Working...") and mark it as the selected one
PreviewShow(i) {
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
        text := JobStatus(job)
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
    first := 0  ; the first tab that just finished
    for i, job in PREVIEW.jobs {
        was := job.done
        if !PollJob(job)
            pending := true
        else if !was {
            changed := true
            first := first ? first : i
        }
    }
    if (changed && PROVIDER = "ollama")
        StartNextJob(PREVIEW.jobs)
    if changed {
        if (PREVIEW.kind = "list")
            PreviewRefreshRows()
        else {
            ; Until you pick a tab yourself, show the first result that is ready
            sel := PREVIEW.sel
            if (!PREVIEW.picked && first && !PREVIEW.jobs[sel].done)
                sel := first
            PreviewShow(sel)
        }
        ready := JobsReady(PREVIEW.jobs)
        PREVIEW.gui.Title := pending ? PREVIEW.title " (" ready " of " PREVIEW.jobs.Length " ready)" : PREVIEW.title
    }
    if !pending
        SetTimer(PreviewPoll, 0)
}

PreviewUse(*) {
    PreviewUseTone(PREVIEW.sel)
}

; Paste the result of tone i over the selection and close the window
PreviewUseTone(i, *) {
    global PREVIEW
    state := PREVIEW
    job := state.jobs[i]
    if (!job.done || job.error != "")
        return
    PREVIEW := ""
    ToolTip()
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
    ToolTip()
    state.gui.Destroy()
    A_Clipboard := state.savedClip
}

; Open a blank chat window (no selection needed)
RunChat(hk, *) {
    OpenResultWindow("Chat", "", "")
}

; Ask the LLM to explain the selected word or text and show the answer in a tooltip
; (nothing is replaced); the tooltip goes away on a click, Esc or after EXPLAIN_SECONDS
RunExplain(hk, *) {
    if (BUSY || MENU_OPEN || PREVIEW || IsExcludedApp()) {
        PassThrough(hk)
        return
    }
    original := CopySelection(&savedClip)
    if (original = "") {
        PassThrough(hk)
        return
    }
    A_Clipboard := savedClip
    if hk.isMouse
        KeyWait(hk.key, "T2")
    Explain(original)
}

; Show an explanation of the text in a tooltip at the cursor
Explain(original) {
    global BUSY, EXPLAIN_START
    SetTimer(ExplainWatch, 0)
    BUSY := true
    ToolTip("Explaining...")
    try {
        answer := CallLLM(original, EXPLAIN_PROMPT)
    } catch as err {
        ToolTip()
        BUSY := false
        MsgBox("Request failed:`n`n" err.Message, "TextFixer", "Iconx")
        return
    }
    BUSY := false
    ToolTip(WrapText(Trim(answer, " `t`r`n"), 70))
    EXPLAIN_START := A_TickCount
    SetTimer(ExplainWatch, 100)
}

ExplainWatch() {
    global EXPLAIN_START
    if (A_TickCount - EXPLAIN_START > EXPLAIN_SECONDS * 1000
        || GetKeyState("Escape", "P") || GetKeyState("LButton", "P")
        || GetKeyState("RButton", "P") || GetKeyState("MButton", "P")) {
        ToolTip()
        SetTimer(ExplainWatch, 0)
    }
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
    RunTone(preset, original, savedClip)
}

; Run a tone on the text: replace the selection, or open the result window (MODE=window)
RunTone(preset, original, savedClip) {
    if (preset.mode = "window") {
        A_Clipboard := savedClip
        OpenResultWindow(preset.name, preset.prompt, original)
    } else
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
    RunTone(preset, job.original, job.savedClip)
}

; userText replaces the text sent to the LLM (used by the popup's custom instruction);
; the selection's trailing whitespace is still taken from `original`
ApplyTone(preset, original, savedClip, userText := "") {
    global BUSY
    BUSY := true
    ToolTip(preset.name "...")
    try {
        fixed := CallLLM(userText != "" ? userText : original, preset.prompt " " INCOMPATIBLE_RULE)
    } catch as err {
        ToolTip()
        A_Clipboard := savedClip
        BUSY := false
        MsgBox("Request failed:`n`n" err.Message, "TextFixer", "Iconx")
        return
    }
    if (Trim(fixed, " `t`r`n") = INCOMPATIBLE_MARK) {
        A_Clipboard := savedClip
        BUSY := false
        ToolTip("The text isn't compatible with this request.")
        SetTimer(() => ToolTip(), -2500)
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
