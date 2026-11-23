"""按时间精确切参考片段。用法：
  python tools/cut_span.py speaker_b 39.4 50.5 refs/speaker_b_refA.wav [--denoise]
"""
import subprocess
import sys
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    slug, start, end, out = argv[0], float(argv[1]), float(argv[2]), ROOT / argv[3]
    denoise = "--denoise" in argv
    src = WORK / f"{slug}.src.wav"
    x, sr = sf.read(str(src), dtype="float32", always_2d=True)
    a, b = int(start * sr), min(len(x), int(end * sr))
    seg = x[a:b, 0].copy()
    tmp = WORK / "_cut_tmp.wav"
    sf.write(str(tmp), seg, sr, subtype="PCM_16")
    af = "highpass=f=70,afftdn=nr=10:nf=-45,loudnorm=I=-19:TP=-2:LRA=6" if denoise else \
         "highpass=f=70,loudnorm=I=-19:TP=-2:LRA=6"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp),
           "-af", af, "-ar", "32000", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tmp.unlink(missing_ok=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr[:500])
    i = sf.info(str(out))
    print(f"{out.name}: {i.duration:.2f}s sr={i.samplerate} {out.stat().st_size}B")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
