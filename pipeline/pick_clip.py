"""从一条长音频里挑出可用的参考片段（零样本克隆用），并转写做逐字稿候选。

用法：
  .venv\\Scripts\\python.exe pipeline/pick_clip.py speaker_b 说话人B [--win 10] [--top 5] [--asr]

输出：
  work/<slug>.clips.json   候选片段表（时间、覆盖、平坦度、能量）
  refs/<slug>_refN_<start>-<end>s.wav  切好的参考音频（32 kHz 单声道，已做轻降噪）
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
REFS = ROOT / "refs"
FRAME_SEC = 0.025
HOP_SEC = 0.010


def load(slug):
    p = WORK / f"{slug}.src.wav"
    if not p.exists():
        raise SystemExit(f"missing {p}; 先跑 ingest_voice.py")
    x, sr = sf.read(str(p), dtype="float32", always_2d=True)
    return x[:, 0], sr


def frame_stats(x, sr):
    frame = int(FRAME_SEC * sr)
    hop = int(HOP_SEC * sr)
    n = 1 + max(0, (len(x) - frame) // hop)
    rms = np.empty(n, dtype=np.float32)
    flat = np.empty(n, dtype=np.float32)
    win = np.hanning(frame).astype(np.float32)
    for i in range(n):
        seg = x[i * hop:i * hop + frame]
        rms[i] = np.sqrt(np.mean(seg ** 2) + 1e-12)
        spec = np.abs(np.fft.rfft(seg * win)) + 1e-12
        flat[i] = np.exp(np.mean(np.log(spec))) / np.mean(spec)
    db = 20 * np.log10(rms + 1e-12)
    # 自适应阈值：取 95 分位往下 20 dB 作为语音线
    thr = float(np.percentile(db, 95)) - 20.0
    speech = db > thr
    return db, flat, speech, hop


def rolling(speech, flat, win_frames):
    c = np.concatenate([[0], np.cumsum(speech.astype(np.float32))])
    cov = (c[win_frames:] - c[:-win_frames]) / win_frames
    fc = np.concatenate([[0], np.cumsum(flat)])
    fmean = (fc[win_frames:] - fc[:-win_frames]) / win_frames
    # 覆盖率权重高，平坦度高（气声/混响）扣分
    score = cov - 0.6 * np.clip(fmean - 0.25, 0, None)
    return cov, fmean, score


def pick(score, cov, fmean, win_frames, top, min_gap_frames):
    order = np.argsort(-score)
    chosen = []
    for idx in order:
        if cov[idx] < 0.55:
            continue
        if all(abs(int(idx) - int(c)) >= min_gap_frames for c in chosen):
            chosen.append(int(idx))
        if len(chosen) >= top:
            break
    return chosen


def cut(x, sr, start_sec, dur_sec, out):
    a = int(start_sec * sr)
    b = min(len(x), a + int(dur_sec * sr))
    seg = x[a:b].copy()
    # 轻处理：去 60 Hz 以下、去直流、归一化到 -20 dBFS 峰值 -2
    np.save(out.with_suffix(".npy"), seg)
    sf.write(str(out.with_suffix(".raw.wav")), seg, sr, subtype="PCM_16")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(out.with_suffix(".raw.wav")),
           "-af", "highpass=f=70,afftdn=nr=10:nf=-45,loudnorm=I=-19:TP=-2:LRA=6",
           "-ar", "32000", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out.with_suffix(".raw.wav").unlink(missing_ok=True)
    out.with_suffix(".npy").unlink(missing_ok=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg: {r.stderr[:400]}")
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    slug, label = argv[0], argv[1]
    win_sec = float(argv[argv.index("--win") + 1]) if "--win" in argv else 10.0
    top = int(argv[argv.index("--top") + 1]) if "--top" in argv else 5
    x, sr = load(slug)
    db, flat, speech, hop = frame_stats(x, sr)
    win_frames = int(win_sec / HOP_SEC)
    if len(speech) <= win_frames:
        raise SystemExit("audio too short for this window")
    cov, fmean, score = rolling(speech, flat, win_frames)
    idx = pick(score, cov, fmean, win_frames, top, int(1.5 / HOP_SEC))
    REFS.mkdir(exist_ok=True)
    rows = []
    for k, i in enumerate(idx, 1):
        start = round(i * HOP_SEC, 2)
        name = f"{slug}_ref{k}_{start}-{round(start + win_sec, 2)}s.wav"
        out = REFS / name
        cut(x, sr, start, win_sec, out)
        info = sf.info(str(out))
        seg_db = db[i:i + win_frames]
        rows.append({
            "n": k, "start": start, "end": round(start + win_sec, 2),
            "coverage": round(float(cov[i]), 3),
            "flatness": round(float(fmean[i]), 3),
            "score": round(float(score[i]), 3),
            "mean_db": round(float(seg_db.mean()), 1),
            "min_db": round(float(seg_db.min()), 1),
            "file": name, "sec": round(info.duration, 2), "bytes": out.stat().st_size,
        })
    report = {"slug": slug, "label": label, "src_sec": round(len(x) / sr, 2),
              "win_sec": win_sec, "thr_db": round(float(np.percentile(db, 95)) - 20, 1),
              "candidates": rows}
    (WORK / f"{slug}.clips.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        print(f"[{r['n']}] {r['start']:>7.2f}-{r['end']:<7.2f}s cov={r['coverage']:.2f} "
              f"flat={r['flatness']:.2f} db={r['mean_db']:.0f} -> {r['file']} ({r['bytes']}B)")
    print("json:", WORK / f"{slug}.clips.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
