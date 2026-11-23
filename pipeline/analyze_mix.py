# -*- coding: utf-8 -*-
"""分析音轨构成：立体声宽度（判断有无 BGM/音效垫底）、底噪、语音间隙。"""
import json
import sys
import wave

import numpy as np


def load(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch == 2:
        x = x.reshape(-1, 2)
    return x, sr, ch


def frame_feats(x, sr, win=0.05):
    n = int(win * sr)
    mono = x.mean(axis=1) if x.ndim == 2 else x
    frames = len(mono) // n
    m = mono[: frames * n].reshape(frames, n)
    rms = np.sqrt((m**2).mean(axis=1))
    fft = np.abs(np.fft.rfft(m * np.hanning(n), axis=1)) + 1e-9
    p = fft / fft.sum(axis=1, keepdims=True)
    flat = np.exp(np.log(p).mean(axis=1)) / p.mean(axis=1)
    out = {"rms": rms, "flat": flat}
    if x.ndim == 2:
        l, r = x[: frames * n, 0].reshape(frames, n), x[: frames * n, 1].reshape(frames, n)
        mid, side = (l + r) / 2, (l - r) / 2
        ms = np.sqrt((mid**2).mean(axis=1))
        ss = np.sqrt((side**2).mean(axis=1))
        out["mid"] = ms
        out["side"] = ss
    return out


def main(stereo_path, seg_json, out_json, block=5.0):
    x, sr, ch = load(stereo_path)
    f = frame_feats(x, sr)
    rms = f["rms"]
    win = int(block / 0.05)
    blocks = []
    for i in range(0, len(rms) - win + 1, win):
        sl = slice(i, i + win)
        b = {
            "t0": round(i * 0.05, 1),
            "t1": round((i + win) * 0.05, 1),
            "rms_db": round(20 * np.log10(rms[sl].mean() + 1e-9), 1),
            "flat": round(float(f["flat"][sl].mean()), 4),
        }
        if ch == 2:
            s = f["side"][sl].mean() + 1e-9
            b["side_db"] = round(20 * np.log10(s), 1)
            b["mid_db"] = round(20 * np.log10(f["mid"][sl].mean() + 1e-9), 1)
        blocks.append(b)

    segs = json.load(open(seg_json, encoding="utf-8"))["segments"]
    # 统计语音间隙的底噪：段与段之间的帧
    speech_mask = np.zeros(len(rms), dtype=bool)
    for s in segs:
        a, b2 = int(s["start"] / 0.05), int(s["end"] / 0.05)
        speech_mask[a:b2] = True
    gap = rms[~speech_mask]
    speech = rms[speech_mask]
    res = {
        "sr": sr,
        "channels": ch,
        "speech_rms_db": round(20 * np.log10(speech.mean() + 1e-9), 1),
        "gap_rms_db": round(20 * np.log10(gap.mean() + 1e-9), 1) if len(gap) else None,
        "gap_p95_db": round(20 * np.log10(np.percentile(gap, 95) + 1e-9), 1) if len(gap) else None,
        "blocks": blocks,
    }
    json.dump(json.loads(json.dumps(res, default=float)), open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "blocks"}, ensure_ascii=False, default=float))
    for b in blocks:
        print(b)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
