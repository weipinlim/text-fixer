; LLM requests for the supported providers: openai (any OpenAI-compatible server such
; as vLLM, llama.cpp or ChatGPT), gemini (Google) and ollama.
; Uses the globals PROVIDER, API_URL, API_KEY, MODEL, TEMPERATURE and TIMEOUT_SEC.

; Chat endpoint of the chosen provider; API_URL overrides the built-in defaults
EndpointUrl() {
    if (API_URL != "")
        return API_URL
    if (PROVIDER = "gemini")
        return "https://generativelanguage.googleapis.com/v1beta/models/" MODEL ":generateContent"
    if (PROVIDER = "ollama")
        return "http://localhost:11434/api/chat"
    return ""
}

; JSON request body. messages is an array of {role: "user"|"assistant", content: text}
BuildBody(messages, system) {
    if (PROVIDER = "gemini") {
        contents := ""
        for msg in messages
            contents .= (contents != "" ? "," : "") '{"role":"' (msg.role = "assistant" ? "model" : "user")
                . '","parts":[{"text":' JsonEscape(msg.content) '}]}'
        sys := (system != "") ? '"system_instruction":{"parts":[{"text":' JsonEscape(system) '}]},' : ""
        return '{' sys '"contents":[' contents '],"generationConfig":{"temperature":' TEMPERATURE '}}'
    }
    list := (system != "") ? '{"role":"system","content":' JsonEscape(system) '}' : ""
    for msg in messages
        list .= (list != "" ? "," : "") '{"role":"' msg.role '","content":' JsonEscape(msg.content) '}'
    if (PROVIDER = "ollama")
        return '{"model":' JsonEscape(MODEL) ',"messages":[' list '],"stream":false,"options":{"temperature":' TEMPERATURE '}}'
    return '{"model":' JsonEscape(MODEL) ',"messages":[' list '],"temperature":' TEMPERATURE ',"stream":false}'
}

CallLLM(text, prompt) {
    return FinishRequest(StartRequest(text, prompt, false))
}

StartRequest(text, prompt, async) {
    return StartChat([{role: "user", content: text}], prompt, async)
}

; Send a chat request; with async=true it returns at once and FinishRequest reads the
; answer after http.WaitForResponse() reports that it has arrived
StartChat(messages, system, async) {
    url := EndpointUrl()
    if (url = "")
        throw Error("API_URL is not set in config.ini")
    http := ComObject("WinHttp.WinHttpRequest.5.1")
    http.SetTimeouts(5000, 5000, 30000, TIMEOUT_SEC * 1000)
    http.Open("POST", url, async)
    http.SetRequestHeader("Content-Type", "application/json")
    if (API_KEY != "") {
        if (PROVIDER = "gemini")
            http.SetRequestHeader("x-goog-api-key", API_KEY)
        else
            http.SetRequestHeader("Authorization", "Bearer " API_KEY)
    }
    http.Send(BuildBody(messages, system))
    return http
}

; True once an async request has its answer. WaitForResponse alone is not reliable for
; polling, so also check that the status and the body can be read (they raise an error
; while the answer is still on its way).
HttpReady(http) {
    try {
        if http.WaitForResponse(0.01)
            return true
    }
    try {
        http.Status
        http.ResponseBody
        return true
    }
    return false
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

; Pull the answer text out of the response: choices[0].message.content (openai),
; message.content (ollama) or candidates[0].content.parts[0].text (gemini)
ExtractContent(json) {
    anchor := (PROVIDER = "gemini") ? '"candidates"' : '"message"'
    key := (PROVIDER = "gemini") ? "text" : "content"
    pos := InStr(json, anchor)
    if !pos || !RegExMatch(json, '"' key '"\s*:\s*"', &m, pos)
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
