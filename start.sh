#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# The Space currently runs a Gradio 5.x build where css/js/theme belong to
# gr.Blocks(), while Blocks.launch() does not accept those keyword arguments.
# Normalize the generated V2.5 app at startup without changing its source
# features or Qwen mapper.
python - "$ROOT/app.py" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
old_blocks = "with gr.Blocks(title='English Learning Lab V2.5') as demo:"
new_blocks = "with gr.Blocks(title='English Learning Lab V2.5',css=CSS,js=JS,theme=gr.themes.Soft()) as demo:"
s = s.replace(old_blocks, new_blocks, 1)
old_launch = "demo.launch(server_name='0.0.0.0',server_port=int(os.getenv('PORT','7860')),css=CSS,js=JS,theme=gr.themes.Soft())"
new_launch = "demo.launch(server_name='0.0.0.0',server_port=int(os.getenv('PORT','7860')))"
s = s.replace(old_launch, new_launch, 1)
p.write_text(s, encoding="utf-8")
PY

exec python app.py
