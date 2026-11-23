# -*- coding: utf-8 -*-
"""一次加载模型，按句批量合成（同音色）。用法：
  .venv/Scripts/python.exe scripts/say.py --ref refs/x.wav --ref-text "..." --out-dir out \
      --text "第一句" --text "第二句"
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
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--text", action="append", required=True)
    ap.add_argument("--nfe", type=int, default=32)
    ap.add_argument("--cfg", type=float, default=2.0)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--prefix", default="say")
    a = ap.parse_args()

    tts = F5TTS(
        model="F5TTS_v1_Base",
        ckpt_file=str(ROOT / "models/F5TTS_v1_Base/model_1250000.safetensors"),
        vocab_file=str(ROOT / "models/F5TTS_v1_Base/vocab.txt"),
        vocoder_local_path=str(ROOT / "models/vocos-mel-24khz"),
        device="cuda",
    )
    outdir = Path(a.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    for i, txt in enumerate(a.text, 1):
        out = outdir / f"{a.prefix}_{i:02d}.wav"
        wav, sr, _ = tts.infer(
            ref_file=a.ref, ref_text=a.ref_text, gen_text=txt,
            nfe_step=a.nfe, cfg_strength=a.cfg, speed=a.speed,
            seed=a.seed, file_wave=str(out), show_info=lambda *x: None,
        )
        print(f"[{i}] {out} dur={len(wav)/sr:.2f}s :: {txt[:30]}")


if __name__ == "__main__":
    main()
