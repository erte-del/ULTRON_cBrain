"""Makes Ultron's local model: ollama pull qwen3:14b, then  python scripts/make_ollama_model.py

Same as `ollama create ultron-qwen3-14b -f scripts/Modelfile.ultron`, plus two things a plain
Modelfile can't do:
  - answers straight away. Qwen3 "thinks" for ~300 tokens before every reply (20+ seconds on a
    Mac), and Claude Code can't switch that off through Ollama, so the model's own template is
    patched to always start the reply with an empty thinking block.
  - the 32k window Ultron's prompt needs (Ollama's default is 4k).
Works on Mac and Windows. Usage: make_ollama_model.py [base model] [new name]
"""

import subprocess
import sys
import tempfile
from pathlib import Path

base = sys.argv[1] if len(sys.argv) > 1 else "qwen3:14b"
name = sys.argv[2] if len(sys.argv) > 2 else "ultron-" + base.replace(":", "-")
NO_THINK = "{{ if and $.IsThinkSet (not $.Think) -}}"

shown = subprocess.run(["ollama", "show", base, "--modelfile"], capture_output=True, text=True,
                       encoding="utf-8", check=True).stdout
if NO_THINK not in shown:
    sys.exit(f"{base}'s template has no thinking switch to patch (is it a Qwen3 model? run: ollama pull {base})")
lines = [ln for ln in shown.replace(NO_THINK, "{{ if true -}}").splitlines() if not ln.startswith("PARAMETER num_ctx")]
text = "\n".join(lines) + "\nPARAMETER num_ctx 32768\n"
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "Modelfile"
    path.write_text(text, encoding="utf-8")
    subprocess.run(["ollama", "create", name, "-f", str(path)], check=True)
print(f"Made {name}. Put JARVIS_OLLAMA_MODEL={name} in .env.")
