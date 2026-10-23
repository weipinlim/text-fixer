; Small Markdown -> HTML converter for the result window. Handles headings, bold,
; italic, strikethrough, inline code, code blocks, bullet and numbered lists, tables,
; quotes and rules. It is not a full CommonMark implementation.

MdEscape(s) {
    s := StrReplace(s, "&", "&amp;")
    s := StrReplace(s, "<", "&lt;")
    return StrReplace(s, ">", "&gt;")
}

MdInline(s) {
    s := MdEscape(s)
    s := RegExReplace(s, "``([^``]+)``", "<code>$1</code>")
    s := RegExReplace(s, "\*\*(.+?)\*\*", "<b>$1</b>")
    s := RegExReplace(s, "__(.+?)__", "<b>$1</b>")
    s := RegExReplace(s, "(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", "<i>$1</i>")
    s := RegExReplace(s, "~~(.+?)~~", "<s>$1</s>")
    ; Links are shown as text: clicking one would navigate the result view away
    return RegExReplace(s, "\[([^\]]+)\]\((https?://[^)\s]+)\)", "$1 ($2)")
}

; Close the open paragraph and, unless keepList, the open list
MdFlush(st, keepList := false) {
    if (st.para != "") {
        st.out .= "<p>" st.para "</p>"
        st.para := ""
    }
    if (!keepList && st.list != "") {
        st.out .= "</" st.list ">"
        st.list := ""
    }
}

; "| a | b |" -> ["a", "b"]
MdCells(line) {
    line := Trim(line)
    if (SubStr(line, 1, 1) = "|")
        line := SubStr(line, 2)
    if (SubStr(line, -1) = "|")
        line := SubStr(line, 1, -1)
    cells := StrSplit(line, "|")
    for i, cell in cells
        cells[i] := Trim(cell)
    return cells
}

MdToHtml(md) {
    fence := "``````"
    lines := StrSplit(StrReplace(md, "`r`n", "`n"), "`n")
    st := {out: "", para: "", list: ""}
    inCode := false
    code := ""
    i := 1
    while (i <= lines.Length) {
        line := lines[i]
        i++
        if inCode {
            if RegExMatch(line, "^\s*" fence) {
                st.out .= "<pre><code>" MdEscape(RTrim(code, "`n")) "</code></pre>"
                inCode := false
                code := ""
            } else
                code .= line "`n"
            continue
        }
        if RegExMatch(line, "^\s*" fence) {
            MdFlush(st)
            inCode := true
            continue
        }
        if (Trim(line) = "") {
            MdFlush(st, true)
            continue
        }
        if RegExMatch(line, "^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", &m) {
            MdFlush(st)
            lvl := StrLen(m[1])
            st.out .= "<h" lvl ">" MdInline(m[2]) "</h" lvl ">"
            continue
        }
        if RegExMatch(line, "^\s{0,3}([-*_])(\s*\1){2,}\s*$") {
            MdFlush(st)
            st.out .= "<hr>"
            continue
        }
        if (InStr(line, "|") && i <= lines.Length
            && RegExMatch(lines[i], "^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")) {
            MdFlush(st)
            table := "<table><thead><tr>"
            for cell in MdCells(line)
                table .= "<th>" MdInline(cell) "</th>"
            table .= "</tr></thead><tbody>"
            i++
            while (i <= lines.Length && InStr(lines[i], "|") && Trim(lines[i]) != "") {
                table .= "<tr>"
                for cell in MdCells(lines[i])
                    table .= "<td>" MdInline(cell) "</td>"
                table .= "</tr>"
                i++
            }
            st.out .= table "</tbody></table>"
            continue
        }
        if RegExMatch(line, "^\s*([-*+]|\d+[.)])\s+(.*)$", &m) {
            type := RegExMatch(m[1], "^\d") ? "ol" : "ul"
            if (st.list != type) {
                MdFlush(st)
                st.out .= "<" type ">"
                st.list := type
            } else
                MdFlush(st, true)
            st.out .= "<li>" MdInline(m[2]) "</li>"
            continue
        }
        if RegExMatch(line, "^\s*>\s?(.*)$", &m) {
            MdFlush(st)
            st.out .= "<blockquote>" MdInline(m[1]) "</blockquote>"
            continue
        }
        if (st.list != "")
            MdFlush(st)
        st.para .= (st.para != "" ? "<br>" : "") MdInline(line)
    }
    if inCode
        st.out .= "<pre><code>" MdEscape(RTrim(code, "`n")) "</code></pre>"
    MdFlush(st)
    return st.out
}
