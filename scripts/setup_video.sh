#!/bin/bash
# One-time setup for video generation (the generate_video tool).
#   scripts/setup_video.sh       Wan 2.1 T2V 1.3B (~17.6 GB download): text to video, 480p
#   scripts/setup_video.sh 5b    Wan 2.2 TI2V 5B (~34 GB download): text or image to video,
#                                720p, 24 fps. Used instead of 1.3B once it's there.
# Installs mlx-video in its own Python, downloads the model from Hugging Face, converts it
# for Apple Silicon (5B: 8-bit, to fit in memory), then deletes the download.
# Needs uv (https://docs.astral.sh/uv/). Safe to run again: finished steps are skipped.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WAN="${JARVIS_WAN_DIR:-$ROOT/backend/storage/wan}"
MLX_VIDEO="git+https://github.com/Blaizzy/mlx-video.git@87db56a51758fefb748a359b90a5283bb8ba4837"
if [ "${1:-}" = 5b ]; then
  NAME="Wan2.2-TI2V-5B"; QUANT=(--quantize --bits 8)
else
  NAME="Wan2.1-T2V-1.3B"; QUANT=()
fi
RAW="$WAN/$NAME"
MODEL="$WAN/$NAME-MLX"
PY="$WAN/.venv/bin/python"

mkdir -p "$WAN"
if [ ! -x "$PY" ]; then
  echo "== Installing mlx-video"
  uv venv --python 3.12 "$WAN/.venv"
  # torch is only needed to convert the weights.
  uv pip install --python "$PY" "$MLX_VIDEO" torch
fi

if [ ! -f "$MODEL/config.json" ]; then
  echo "== Downloading $NAME"
  "$PY" -c "from huggingface_hub import snapshot_download as d; d('Wan-AI/$NAME', local_dir='$RAW')"
  echo "== Converting for MLX"
  "$PY" -m mlx_video.models.wan_2.convert --checkpoint-dir "$RAW" --output-dir "$MODEL" ${QUANT[@]+"${QUANT[@]}"}
  rm -rf "$RAW"
fi

echo "== Video generation is ready. Restart Ultron to use it."
