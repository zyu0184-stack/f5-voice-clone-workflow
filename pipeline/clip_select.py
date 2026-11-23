# -*- coding: utf-8 -*-
"""从成品混音里挑出适合做音色参考的片段，并导出清洗后的 wav。

判据：窗口内语音覆盖率 >=0.75、窗口均 no_speech 低、窗口首尾不切断语音。
"""
import json
import subprocess
import sys
from pathlib import Path


def pick(seg_json, span=10.0, hop=1.0, min_cov=0.72, min_start=0.8):
    segs = json.load(open(seg_json, encoding="utf-8"))["segments"]
    total = max(s["end"] for s in segs) + 2
    cands = []
    t = min_start
    while t + span <= total:
        a, b = t, t + span
        cov = 0.0
        ns = []
        for s in segs:
            ov = min(b, s["end"]) - max(a, s["start"])
            if ov > 0:
                cov += ov
                ns.append(s["no_speech"])
        inside = [s for s in segs if s["start"] >= a and s["end"] <= b]
        if cov / span >= min_cov and inside:
            # 首尾对齐到语音边界，避免半词
            a2 = inside[0]["start"]
            b2 = inside[-1]["end"]
            cands.append(
                {
                    "start": round(max(0.0, a2 - 0.15), 2),
                    "end": round(b2 + 0.15, 2),
                    "cov": round(cov / span, 3),
                    "ns": round(sum(ns) / len(ns), 3),
                    "chars": sum(len(s["text"]) for s in inside),
                    "text": " ".join(s["text"] for s in inside),
                }
            )
        t += hop
    cands.sort(key=lambda c: (-c["chars"], c["ns"]))
    return cands


def export(src, out, start, end):
    dur = round(end - start, 2)
    af = "highpass=f=60,afftdn=nr=12:nf=-40,loudnorm=I=-20:TP=-2:LRA=7"
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(dur),
        "-i", str(src), "-af", af, "-ac", "1", "-ar", "32000",
        "-c:a", "pcm_s16le", str(out),
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    seg_json, src, outdir, tag = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    noun = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cands = pick(seg_json)
    print(f"# {tag}: {len(cands)} candidates")
    chosen = []
    for c in cands:
        if any(abs(c["start"] - x["start"]) < 12 for x in chosen):
            continue
        chosen.append(c)
        if len(chosen) >= noun:
            break
    for i, c in enumerate(chosen, 1):
        out = outdir / f"{tag}_ref{i}_{c['start']}-{c['end']}s.wav"
        export(src, out, c["start"], c["end"])
        print(f"  -> {out.name} | cov={c['cov']} ns={c['ns']} chars={c['chars']}")
        print(f"     {c['text'][:80]}")
