#Requires AutoHotkey v2.0
#SingleInstance Force

; TextFixer - select text anywhere, press the hotkey, and the text is replaced
; with a corrected version from your OpenAI-compatible (vLLM) server.
; All settings live in config.ini next to this script (or the compiled .exe).

global CONFIG_FILE := A_ScriptDir "\config.ini"

if !FileExist(CONFIG_FILE) {
    MsgBox("config.ini not found in:`n" A_ScriptDir "`n`nCopy config.example.ini to config.ini and fill in your settings.", "TextFixer", "Icon!")
    ExitApp
}

global API_URL       := IniRead(CONFIG_FILE, "Settings", "API_URL", "")
global API_KEY       := IniRead(CONFIG_FILE, "Settings", "API_KEY", "")
global MODEL         := IniRead(CONFIG_FILE, "Settings", "MODEL", "")
global SYSTEM_PROMPT := IniRead(CONFIG_FILE, "Settings", "SYSTEM_PROMPT", "Fix spelling, grammar and punctuation. Return only the corrected text.")
global TEMPERATURE   := IniRead(CONFIG_FILE, "Settings", "TEMPERATURE", "0.2")
global TIMEOUT_SEC   := IniRead(CONFIG_FILE, "Settings", "TIMEOUT", "60")
global HOTKEY_KEY    := IniRead(CONFIG_FILE, "Settings", "HOTKEY", "^!f")

; Allow line breaks in the prompt via \n
SYSTEM_PROMPT := StrReplace(SYSTEM_PROMPT, "\n", "`n")
if !IsNumber(TEMPERATURE)
    TEMPERATURE := "0.2"
if !IsInteger(TIMEOUT_SEC)
    TIMEOUT_SEC := 60

if (API_URL = "" || MODEL = "") {
    MsgBox("API_URL and MODEL must be set in config.ini.", "TextFixer", "Icon!")
    ExitApp
}

try Hotkey(HOTKEY_KEY, FixSelectedText)
catch {
    MsgBox("Invalid HOTKEY in config.ini: " HOTKEY_KEY, "TextFixer", "Icon!")
    ExitApp
}

A_IconTip := "TextFixer (" HOTKEY_KEY ")"
A_TrayMenu.Add()
A_TrayMenu.Add("Edit config.ini", (*) => Run('notepad.exe "' CONFIG_FILE '"'))
A_TrayMenu.Add("Reload config", (*) => Reload())
TrayTip("Running. Select text and press " HOTKEY_KEY ".", "TextFixer")

FixSelectedText(*) {
    savedClip := ClipboardAll()
    A_Clipboard := ""
    Send("^c")
    if !ClipWait(1) {
        A_Clipboard := savedClip
        TrayTip("No text selected.", "TextFixer")
        return
    }
    original := A_Clipboard

    ToolTip("Fixing text...")
    try {
        fixed := CallLLM(original)
    } catch as err {
        ToolTip()
        A_Clipboard := savedClip
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
}

CallLLM(text) {
    body := '{"model":' JsonEscape(MODEL)
        . ',"messages":[{"role":"system","content":' JsonEscape(SYSTEM_PROMPT) '}'
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
