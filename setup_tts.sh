#!/usr/bin/env bash
# 为本机拉起一套零样本音色克隆环境（F5-TTS），复用系统已装的 torch 2.11+cu128
set -x
cd "$(dirname "$0")" || exit 1
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY=".venv/Scripts/python.exe"; fi

if [ ! -x "$PY" ]; then
  python -m venv .venv --system-site-packages
fi
"$PY" -m pip install -q -U pip setuptools wheel

"$PY" -m pip install -q --no-deps "f5-tts"
"$PY" -m pip install -q "transformers==4.46.3" accelerate vocos ema-pytorch x-transformers \
  soundfile librosa click hydra-core omegaconf jieba pypinyin numpy tqdm
"$PY" -m pip install -q torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128

export HF_ENDPOINT=https://hf-mirror.com
"$PY" - <<'PYEOF'
from huggingface_hub import snapshot_download
p1 = snapshot_download("SWivid/F5-TTS", allow_patterns=["F5TTS_v1_Base/*"])
print("F5TTS:", p1)
p2 = snapshot_download("charactr/vocos-mel-24khz")
print("vocos:", p2)
PYEOF
"$PY" -c "import torch, torchaudio, f5_tts, transformers; print('torch', torch.__version__, torch.cuda.is_available()); print('tf', transformers.__version__)"
echo "SETUP_DONE"
