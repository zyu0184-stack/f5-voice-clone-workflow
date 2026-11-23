# -*- coding: utf-8 -*-
"""扫描音频里的人声段落，输出可用于音色克隆的干净片段候选。"""
import json
import sys
import wave

import numpy as np
from faster_whisper import WhisperModel


def main(wav_path, out_json):
    dev, ct = ("cuda", "float16") if "--gpu" in sys.argv else ("cpu", "int8")
    model = WhisperModel("small", device=dev, compute_type=ct)
    segments, info = model.transcribe(
        wav_path,
        language="zh",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=300, threshold=0.5),
        beam_size=1,
    )
    rows = []
    for s in segments:
        rows.append(
            {
                "start": round(s.start, 2),
                "end": round(s.end, 2),
                "dur": round(s.end - s.start, 2),
                "text": s.text.strip(),
                "no_speech": round(getattr(s, "no_speech_prob", 0.0), 3),
                "avg_logprob": round(getattr(s, "avg_logprob", 0.0), 3),
            }
        )
    with wave.open(wav_path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    meta = {"duration": round(n / sr, 2), "sr": sr, "segments": rows}
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    print(f"duration={meta['duration']}s  segs={len(rows)}")
    for r in rows[:60]:
        print(f"[{r['start']:>7.2f}-{r['end']:>7.2f}] {r['dur']:>5.2f}s ns={r['no_speech']} {r['text'][:40]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
