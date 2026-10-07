#!/bin/bash
# One-time setup for Ultron's Reel voice and word-synced captions (reel_edit voice/words).
#   scripts/setup_voice.sh
# Installs mlx-audio and Piper in their own Python and downloads Kokoro 82M (the English
# voices, ~330 MB), Piper's Turkish voice (~63 MB) and Whisper large-v3-turbo (word timings
# for captions, ~1.6 GB). Without it, reel_edit speaks with macOS `say`, has no Turkish voice
# and can't do word captions.
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
"$PY" -c "import piper" 2>/dev/null || uv pip install --python "$PY" "piper-tts==1.3.0"

PIPER="$VOICE/piper"
for f in tr_TR-dfki-medium.onnx tr_TR-dfki-medium.onnx.json; do
  if [ ! -f "$PIPER/$f" ]; then
    [ "$f" = "${f%.json}" ] && echo "== Downloading the Turkish voice (Piper dfki, ~63 MB)"
    mkdir -p "$PIPER"
    curl -fL --retry 5 -C - -o "$PIPER/$f.part" "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/$f"
    mv "$PIPER/$f.part" "$PIPER/$f"
  fi
done

WHISPER="$VOICE/whisper-large-v3-turbo"
if [ ! -f "$WHISPER/weights.safetensors" ]; then
  echo "== Downloading Whisper large-v3-turbo (~1.6 GB)"
  mkdir -p "$WHISPER"
  for f in config.json weights.safetensors; do
    curl -fL --retry 5 -C - -o "$WHISPER/$f.part" "https://huggingface.co/mlx-community/whisper-large-v3-turbo/resolve/main/$f"
    mv "$WHISPER/$f.part" "$WHISPER/$f"
  done
fi
# mlx-community's copy has no tokenizer; mlx-audio loads it from the same folder.
for f in preprocessor_config.json tokenizer.json tokenizer_config.json vocab.json merges.txt \
         added_tokens.json special_tokens_map.json normalizer.json; do
  [ -f "$WHISPER/$f" ] || curl -fL --retry 5 -o "$WHISPER/$f" "https://huggingface.co/openai/whisper-large-v3-turbo/resolve/main/$f"
done

echo "== Downloading the voice (Kokoro 82M, ~330 MB)"
"$PY" -c "from huggingface_hub import snapshot_download as d; d('mlx-community/Kokoro-82M-bf16')
d('prince-canuma/Kokoro-82M', allow_patterns=['voices/a*', 'voices/b*'])  # the English voices, fetched here not mid-Reel"
# Kokoro fetches a small English language model on first use; do that now, not mid-Reel.
"$PY" -m mlx_audio.tts.generate --model mlx-community/Kokoro-82M-bf16 --voice am_michael --lang_code a \
  --text "Ready." --output_path "$VOICE" --file_prefix check --join_audio > /dev/null
rm -f "$VOICE"/check*.wav

echo "== Voice and captions are ready. Restart Ultron to use them."
