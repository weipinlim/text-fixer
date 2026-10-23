; Windows of TextFixer: result/chat window, the popup at the cursor and the settings
; window. Uses the globals RESULT, POPUP, SETTINGS (one open window of each kind).

; ---------------------------------------------------------------------------
; Helpers
; ---------------------------------------------------------------------------

IsDarkMode() {
    try return RegRead("HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme") = 0
    return false
}

; Make the embedded browser (used for the result window) render in IE11 mode. Takes
; effect the next time TextFixer starts; the first run just uses a simpler layout.
EnsureIeMode() {
    static done := false
    if done
        return
    done := true
    try {
        SplitPath(A_AhkPath, &exe)
        if A_IsCompiled
            exe := A_ScriptName
        RegWrite(11001, "REG_DWORD", "HKCU\Software\Microsoft\Internet Explorer\Main\FeatureControl\FEATURE_BROWSER_EMULATION", exe)
    }
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

; Bring the app the text was selected in back to the front before pasting
ActivateApp(winId) {
    try {
        WinActivate("ahk_id " winId)
        WinWaitActive("ahk_id " winId, , 2)
    }
}

; ---------------------------------------------------------------------------
; Result / chat window: shows an answer (Markdown) and lets you ask follow-ups
; ---------------------------------------------------------------------------

; With original = "" this is a blank chat; otherwise the text is sent with `system`
; straight away and the answer is shown (Summary, Key Points, Table...)
OpenResultWindow(title, system, original) {
    global RESULT
    CloseResultWindow()
    EnsureIeMode()
    g := Gui(, "TextFixer - " title)
    g.SetFont("s10")
    ; Answers are shown as HTML in an embedded browser; if that is not available (or
    ; shows nothing) a plain text box is used instead
    view := ""
    ctrl := ""
    try {
        ctrl := g.AddActiveX("xm ym w780 h430", "Shell.Explorer")
        view := ctrl.Value
        view.Silent := true
        view.Navigate("about:blank")
        Loop 100 {
            if (view.ReadyState = 4)
                break
            Sleep(20)
        }
    } catch {
        view := ""
        if ctrl
            ctrl.Visible := false
    }
    plain := g.AddEdit("xm ym w780 h430 ReadOnly +VScroll" (view ? " Hidden" : ""))
    input := g.AddEdit("xm w680")
    send := g.AddButton("x+8 w92 Default", "Send")
    send.OnEvent("Click", ResultSend)
    g.AddButton("xm w150", "Copy last answer").OnEvent("Click", ResultCopy)
    g.AddButton("x+8 w90", "Close").OnEvent("Click", (*) => CloseResultWindow())
    g.OnEvent("Close", (*) => CloseResultWindow())
    g.OnEvent("Escape", (*) => CloseResultWindow())

    RESULT := {gui: g, view: view, ctrl: ctrl, plain: plain, input: input, send: send
        , items: [], history: [], http: "", start: 0}
    g.Show()
    if (original != "") {
        RESULT.history.Push({role: "user", content: original})
        ResultAsk(system)
    } else
        ResultRender()
    input.Focus()
}

CloseResultWindow() {
    global RESULT
    if !RESULT
        return
    g := RESULT.gui
    RESULT := ""
    g.Destroy()
}

; Send the conversation so far; the answer is collected by ResultPoll
ResultAsk(system) {
    try RESULT.http := StartChat(RESULT.history, system, true)
    catch as err {
        RESULT.items.Push({role: "error", text: err.Message})
        ResultRender()
        return
    }
    RESULT.start := A_TickCount
    RESULT.send.Enabled := false
    ResultRender()
    SetTimer(ResultPoll, 200)
}

ResultPoll() {
    if (!RESULT || !RESULT.http) {
        SetTimer(ResultPoll, 0)
        return
    }
    if HttpReady(RESULT.http) {
        http := RESULT.http
        RESULT.http := ""
        try {
            answer := Trim(FinishRequest(http), " `t`r`n")
            RESULT.history.Push({role: "assistant", content: answer})
            RESULT.items.Push({role: "assistant", text: answer})
        } catch as err
            RESULT.items.Push({role: "error", text: err.Message})
    } else if (A_TickCount - RESULT.start > TIMEOUT_SEC * 1000) {
        RESULT.http := ""
        RESULT.items.Push({role: "error", text: "Timed out"})
    } else
        return
    SetTimer(ResultPoll, 0)
    RESULT.send.Enabled := true
    ResultRender()
}

ResultSend(*) {
    if (!RESULT || RESULT.http)
        return
    question := Trim(RESULT.input.Value)
    if (question = "")
        return
    RESULT.input.Value := ""
    RESULT.history.Push({role: "user", content: question})
    RESULT.items.Push({role: "user", text: question})
    ResultAsk(FOLLOWUP_SYSTEM)
}

ResultCopy(*) {
    if !RESULT
        return
    Loop RESULT.items.Length {
        item := RESULT.items[RESULT.items.Length - A_Index + 1]
        if (item.role = "assistant") {
            A_Clipboard := item.text
            ToolTip("Copied")
            SetTimer(() => ToolTip(), -1000)
            return
        }
    }
}

ResultRender() {
    if !RESULT
        return
    body := ""
    for item in RESULT.items {
        if (item.role = "user")
            body .= '<div class="user">' MdEscape(item.text) '</div>'
        else if (item.role = "error")
            body .= '<div class="error">' MdEscape(item.text) '</div>'
        else
            body .= '<div class="ai">' MdToHtml(item.text) '</div>'
    }
    if RESULT.http
        body .= '<div class="wait">Thinking...</div>'

    if RESULT.view {
        shown := false
        try {
            doc := RESULT.view.document
            doc.open()
            doc.write(ResultPage(body))
            doc.close()
            RESULT.view.document.parentWindow.scrollTo(0, 99999999)
            shown := (body = "" || Trim(RESULT.view.document.body.innerText) != "")
        }
        if shown
            return
        ; The browser view does not work here: switch to the plain text box for good
        RESULT.view := ""
        RESULT.ctrl.Visible := false
        RESULT.plain.Visible := true
    }
    text := ""
    for item in RESULT.items
        text .= (item.role = "user" ? "> " : item.role = "error" ? "Error: " : "") item.text "`n`n"
    if RESULT.http
        text .= "Thinking..."
    RESULT.plain.Value := StrReplace(StrReplace(text, "`r`n", "`n"), "`n", "`r`n")
}

ResultPage(body) {
    dark := IsDarkMode()
    bg := dark ? "#1e1e1e" : "#ffffff"
    fg := dark ? "#e6e6e6" : "#202020"
    userBg := dark ? "#2d3b55" : "#e3ecfb"
    codeBg := dark ? "#2b2b2b" : "#f1f1f1"
    line := dark ? "#666666" : "#aaaaaa"
    css := "body{font-family:'Segoe UI',Arial,sans-serif;font-size:14px;margin:12px;background:" bg ";color:" fg "}"
        . ".user{background:" userBg ";padding:6px 10px;margin:10px 0 10px 80px}"
        . ".error{color:#d33;margin:10px 0}.wait{color:" line ";margin:10px 0}"
        . "h1,h2,h3{margin:12px 0 6px}p{margin:6px 0}ul,ol{margin:6px 0 6px 22px;padding:0}"
        . "code{background:" codeBg ";padding:1px 4px}pre{background:" codeBg ";padding:8px;overflow:auto}"
        . "pre code{padding:0}blockquote{margin:6px 0;padding-left:10px;border-left:3px solid " line "}"
        . "table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid " line ";padding:4px 8px;text-align:left}"
        . "th{background:" codeBg "}"
    return '<!DOCTYPE html><html><head><meta http-equiv="X-UA-Compatible" content="IE=edge">'
        . '<meta charset="utf-8"><style>' css '</style></head><body>' body '</body></html>'
}

; ---------------------------------------------------------------------------
; Popup at the cursor: "describe your change" box plus a button per tone
; ---------------------------------------------------------------------------

RunPopup(hk, *) {
    global POPUP, MENU_OPEN
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
    g := Gui("+AlwaysOnTop -Caption +ToolWindow +Border")
    g.SetFont("s10")
    input := g.AddEdit("xm w440")
    ; Grey hint text shown while the box is empty (EM_SETCUEBANNER)
    DllCall("SendMessage", "Ptr", input.Hwnd, "UInt", 0x1501, "Ptr", 1, "WStr", "Describe your change, then press Enter...")
    g.AddButton("x+6 w70 Default", "Send").OnEvent("Click", PopupSend)
    for preset in PRESETS {
        btn := g.AddButton((Mod(A_Index - 1, 3) = 0 ? "xm" : "x+6") " w168", preset.index " " preset.name)
        btn.OnEvent("Click", PopupTone.Bind(preset))
    }
    g.OnEvent("Escape", (*) => PopupClose(true))

    POPUP := {gui: g, input: input, original: original, savedClip: savedClip, winId: winId, shown: A_TickCount}
    MENU_OPEN := true
    ShowNearCursor(g, mx, my)
    input.Focus()
    SetTimer(PopupWatch, 150)
}

; Close the popup when you click somewhere else
PopupWatch() {
    if !POPUP {
        SetTimer(PopupWatch, 0)
        return
    }
    if (A_TickCount - POPUP.shown > 500 && !WinActive("ahk_id " POPUP.gui.Hwnd))
        PopupClose(true)
}

PopupClose(restoreClipboard) {
    global POPUP, MENU_OPEN
    if !POPUP
        return
    state := POPUP
    POPUP := ""
    MENU_OPEN := false
    SetTimer(PopupWatch, 0)
    state.gui.Destroy()
    if restoreClipboard
        A_Clipboard := state.savedClip
}

PopupTone(preset, *) {
    state := POPUP
    PopupClose(false)
    ActivateApp(state.winId)
    RunTone(preset, state.original, state.savedClip)
}

PopupSend(*) {
    state := POPUP
    instruction := Trim(state.input.Value)
    if (instruction = "")
        return
    PopupClose(false)
    ActivateApp(state.winId)
    custom := {index: 0, name: "Custom", mode: "replace", hotkey: "", prompt: CUSTOM_PROMPT}
    ApplyTone(custom, state.original, state.savedClip
        , "Make this change to the text below.`nDescribed change: " instruction "`n`nText:`n" state.original)
}

; ---------------------------------------------------------------------------
; Settings window: writes config.ini and reloads
; ---------------------------------------------------------------------------

ShowSettings(firstRun := false) {
    global SETTINGS
    if SETTINGS {
        SETTINGS.gui.Show()
        return
    }
    g := Gui(, "TextFixer - Settings")
    g.SetFont("s10")
    fields := [
        ["API_URL", "API URL", "", ""],
        ["API_KEY", "API key", "", "Password"],
        ["MODEL", "Model", "", ""],
        ["TEMPERATURE", "Temperature", "0.2", ""],
        ["TIMEOUT", "Timeout (s)", "60", ""],
        ["EXCLUDE_APPS", "Hotkeys off in", "EXCEL.EXE", ""],
        ["DEFAULT_HOTKEY", "Default tone", "^LButton", ""],
        ["POPUP_HOTKEY", "Popup", "^+Space", ""],
        ["MENU_HOTKEY", "Tone menu", "^RButton", ""],
        ["PREVIEW_HOTKEY", "All tones (tabs)", "^+LButton", ""],
        ["RESULTS_MENU_HOTKEY", "All tones (list)", "^+RButton", ""],
        ["EXPLAIN_HOTKEY", "Explain word", "^MButton", ""],
        ["CHAT_HOTKEY", "Chat window", "^!Space", ""]
    ]
    g.AddText("xm w150", "Provider")
    provider := g.AddDropDownList("x+8 w360", ["openai", "gemini", "ollama"])
    try provider.Choose(StrLower(IniRead(CONFIG_FILE, "Settings", "PROVIDER", "openai")))
    if !provider.Value
        provider.Choose(1)
    edits := []
    for f in fields {
        g.AddText("xm w150", f[2])
        edits.Push(g.AddEdit("x+8 w360 " f[4], IniRead(CONFIG_FILE, "Settings", f[1], f[3])))
    }
    g.AddText("xm w520 r6", "Provider: openai = vLLM, llama.cpp, ChatGPT and other OpenAI-compatible servers; "
        . "gemini = Google (leave API URL empty); ollama = local Ollama (API URL empty = localhost).`n"
        . "Hotkeys: ^ Ctrl, ! Alt, + Shift, # Win. Leave empty to turn one off. Tones and their prompts are edited in config.ini.")
    g.AddButton("xm w100 Default", "Save").OnEvent("Click", SettingsSave)
    g.AddButton("x+8 w140", "Edit config.ini").OnEvent("Click", (*) => Run('notepad.exe "' CONFIG_FILE '"'))
    g.AddButton("x+8 w100", "Cancel").OnEvent("Click", SettingsClose)
    g.OnEvent("Close", SettingsClose)
    g.OnEvent("Escape", SettingsClose)

    SETTINGS := {gui: g, fields: fields, edits: edits, provider: provider, firstRun: firstRun}
    g.Show()
}

SettingsSave(*) {
    IniWrite(SETTINGS.provider.Text, CONFIG_FILE, "Settings", "PROVIDER")
    for i, f in SETTINGS.fields
        IniWrite(Trim(SETTINGS.edits[i].Value), CONFIG_FILE, "Settings", f[1])
    Reload()
}

SettingsClose(*) {
    global SETTINGS
    state := SETTINGS
    SETTINGS := ""
    state.gui.Destroy()
    if state.firstRun
        ExitApp
}
