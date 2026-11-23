"""新音频入库：探测 → 转工作副本 → 找干净语音段 → 统计。输出 UTF-8 JSON，供后续切参考音频用。

用法：.venv\\Scripts\\python.exe pipeline/ingest_voice.py "long_take.mp3" speaker_b
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
WORK.mkdir(exist_ok=True)


def ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=sample_rate,channels,codec_name,duration,bit_rate", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise SystemExit(f"ffprobe failed: {out.stderr[:500]}")
    return json.loads(out.stdout)


def to_wav(src, dst, sr=32000):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {out.stderr[:800]}")
    return dst


def analyze(wav):
    x, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    x = x[:, 0]
    frame = int(0.025 * sr)
    hop = int(0.010 * sr)
    n = 1 + max(0, (len(x) - frame) // hop)
    rms = np.array([np.sqrt(np.mean(x[i * hop:i * hop + frame] ** 2) + 1e-12) for i in range(n)])
    db = 20 * np.log10(rms + 1e-12)
    # 谱平坦度（每帧）
    win = np.hanning(frame).astype(np.float32)
    flat = []
    for i in range(0, n, 4):
        seg = x[i * hop:i * hop + frame]
        if len(seg) < frame:
            break
        spec = np.abs(np.fft.rfft(seg * win)) + 1e-12
        flat.append(float(np.exp(np.mean(np.log(spec))) / np.mean(spec)))
    flat = np.array(flat)
    speech = db > (np.percentile(db, 95) - 25)
    quiet = db < np.percentile(db, 10)
    return {
        "sr": sr, "sec": round(len(x) / sr, 2),
        "rms_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)), 1),
        "peak_dbfs": round(float(20 * np.log10(np.max(np.abs(x)) + 1e-12)), 1),
        "speech_dbfs": round(float(np.mean(db[speech])), 1) if speech.any() else None,
        "quiet_dbfs": round(float(np.mean(db[quiet])), 1) if quiet.any() else None,
        "flatness_mean": round(float(flat.mean()), 3),
        "flatness_p50": round(float(np.percentile(flat, 50)), 3),
        "frames": int(n), "hop_sec": round(hop / sr, 3), "frame_sec": round(frame / sr, 3),
        "db": [round(float(v), 1) for v in db[::10]],
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = ROOT / argv[0]
    slug = argv[1]
    if not src.exists():
        raise SystemExit(f"missing: {src}")
    info = ffprobe(src)
    wav = WORK / f"{slug}.src.wav"
    t0 = time.time()
    to_wav(src, wav)
    a = analyze(wav)
    report = {"src": src.name, "bytes": src.stat().st_size, "probe": info,
              "wav": str(wav), "convert_sec": round(time.time() - t0, 1), "stats": a}
    out = WORK / f"{slug}.ingest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("src", "bytes", "convert_sec")}, ensure_ascii=False))
    print(json.dumps(a, ensure_ascii=False))
    print("json:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
