"""整片转写（只要时间戳和文本，用来挑片段、做逐字稿）。

用法：.venv\\Scripts\\python.exe pipeline/full_asr.py speaker_b [--beam 1]
输出：work/<slug>.full.json = [{idx,start,end,text,dur,chars}]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    slug = argv[0]
    beam = int(argv[argv.index("--beam") + 1]) if "--beam" in argv else 1
    src = WORK / f"{slug}.src.wav"
    if not src.exists():
        raise SystemExit(f"missing {src}")
    from faster_whisper import WhisperModel

    model = WhisperModel(str(ROOT / "models" / "whisper-turbo"), device="cpu",
                         compute_type="int8", cpu_threads=8)
    segs, info = model.transcribe(
        str(src), language="zh", beam_size=beam,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
        condition_on_previous_text=False,
    )
    rows = []
    for i, s in enumerate(segs):
        t = s.text.strip()
        rows.append({"idx": i, "start": round(s.start, 2), "end": round(s.end, 2),
                     "dur": round(s.end - s.start, 2), "chars": len(t), "text": t})
        if i % 40 == 0:
            print(f"  ...{i} seg @ {s.start:.0f}s", flush=True)
    out = WORK / f"{slug}.full.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(r["dur"] for r in rows)
    print(f"segments={len(rows)} speech_sec={total:.0f} chars={sum(r['chars'] for r in rows)}")
    print("json:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
