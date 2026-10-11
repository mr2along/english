import html


def sentence_controls(segment, index):
    start = float(segment.get("start", 0))
    text = html.escape(str(segment.get("text", "")))
    return (
        f'<div class="practice-sentence" data-index="{int(index)}">'
        f'<div class="practice-text">{text}</div>'
        f'<div class="practice-meta">Start: {start:.2f}s</div>'
        f'<button type="button" aria-label="Phát câu {int(index) + 1}" '
        f'onclick="window.EL?.playSentence({int(index)})">▶ Phát câu</button></div>'
    )


def build_listening_html(segments):
    rows = []
    for index, segment in enumerate(segments or []):
        rows.append(sentence_controls(segment, index))
    return "<div class='listening-lab'>" + "".join(rows) + "</div>"
