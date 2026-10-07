#!/bin/bash
# One-time setup for Ultron's Reel voice and word-synced captions (reel_edit voice/words).
#   scripts/setup_voice.sh
# Installs mlx-audio in its own Python and downloads Kokoro 82M (the voice, ~330 MB) and
# Whisper large-v3-turbo (word timings for captions, ~1.6 GB). Without it, reel_edit speaks
# with macOS `say` and can't do word captions.
# Needs uv (https://docs.astral.sh/uv/). Safe to run again: finished steps are skipped.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VOICE="$ROOT/backend/storage/voice"
PY="$VOICE/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "== Installing mlx-audio"
  uv venv --python 3.12 "$VOICE/.venv"
  uv pip install --python "$PY" "mlx-audio==0.5.8" "misaki[en]"
fi

WHISPER="$VOICE/whisper-large-v3-turbo"
if [ ! -f "$WHISPER/weights.safetensors" ]; then
  echo "== Downloading Whisper large-v3-turbo (~1.6 GB)"
  mkdir -p "$WHISPER"
  for f in config.json weights.safetensors; do
    curl -fL --retry 5 -C - -o "$WHISPER/$f.part" "https://huggingface.co/mlx-community/whisper-large-v3-turbo/resolve/main/$f"
    mv "$WHISPER/$f.part" "$WHISPER/$f"
  done
fi

echo "== Downloading the voice (Kokoro 82M, ~330 MB)"
"$PY" -c "from huggingface_hub import snapshot_download as d; d('mlx-community/Kokoro-82M-bf16')"
# Kokoro fetches a small English language model on first use; do that now, not mid-Reel.
"$PY" -m mlx_audio.tts.generate --model mlx-community/Kokoro-82M-bf16 --voice am_michael --lang_code a \
  --text "Ready." --output_path "$VOICE" --file_prefix check --join_audio > /dev/null
rm -f "$VOICE"/check*.wav

echo "== Voice and captions are ready. Restart Ultron to use them."
