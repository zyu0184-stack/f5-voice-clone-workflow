# -*- coding: utf-8 -*-
"""用本机 F5-TTS 做零样本音色克隆：给定参考音频 + 参考文本 + 新文本，输出同音色 wav。

用法：
  .venv/Scripts/python.exe tools/clone_say.py \
      --ref refs/t1_ref1_49.66-59.7s.wav \
      --ref-text "参考音频里说的原话" \
      --text "要合成的新内容" \
      --out out/demo.wav
"""
import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import soundfile as sf
import torch
import torchaudio

# torchaudio 2.11 走 torchcodec 解码（Windows 无 wheel），这里改回 soundfile 后端
if not getattr(torchaudio, "_sf_patched", False):
    def _load(path, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(np.ascontiguousarray(data.T)), sr

    torchaudio.load = _load
    torchaudio._sf_patched = True

from f5_tts.api import F5TTS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--ref-text", required=True)
    ap.add_argument("--text", required=True, nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--nfe", type=int, default=32)
    ap.add_argument("--cfg", type=float, default=2.0)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    ckpt = ROOT / "models" / "F5TTS_v1_Base" / "model_1250000.safetensors"
    vocab = ROOT / "models" / "F5TTS_v1_Base" / "vocab.txt"
    vocoder = ROOT / "models" / "vocos-mel-24khz"
    wav_dir = ROOT / "models" / "vocos-mel-24khz" / "wavs"
    if not wav_dir.exists():
        wav_dir.mkdir(parents=True, exist_ok=True)
        (wav_dir / ".keep").write_text("")

    tts = F5TTS(
        model="F5TTS_v1_Base",
        ckpt_file=str(ckpt),
        vocab_file=str(vocab),
        vocoder_local_path=str(vocoder),
        device="cuda",
    )

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    wav, sr, _ = tts.infer(
        ref_file=a.ref,
        ref_text=a.ref_text,
        gen_text=" ".join(a.text),
        nfe_step=a.nfe,
        cfg_strength=a.cfg,
        speed=a.speed,
        seed=a.seed,
        file_wave=a.out,
        show_info=print,
    )
    print(f"OK {a.out} sr={sr} dur={len(wav)/sr:.2f}s seed={tts.seed}")


if __name__ == "__main__":
    main()
