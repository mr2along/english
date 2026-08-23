import html


def sentence_controls(segment):
    start = float(segment.get("start", 0))
    text = html.escape(str(segment.get("text", "")))
    return f'''<div class="practice-sentence"><div class="practice-text">{text}</div><div class="practice-meta">Start: {start:.2f}s</div><button type="button" onclick="window.englishLab?.seekSentence({start})">▶ Phát câu</button></div>'''


def build_listening_html(segments):
    rows = []
    for s in segments:
        rows.append(sentence_controls(s))
    return "<div class='listening-lab'>" + "".join(rows) + "</div>"
