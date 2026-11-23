"""Transcribe a wav/mp3 to check a synthesized clip really says what it should.

usage: python tools/verify_wav.py <audio> [--model DIR]
"""
import argparse
import os
import sys

from faster_whisper import WhisperModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL = os.path.join(ROOT, "models", "whisper-turbo")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--beam", type=int, default=1)
    args = ap.parse_args()

    if not os.path.exists(args.audio):
        print(f"missing audio: {args.audio}", file=sys.stderr)
        return 2

    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        args.audio, language="zh", beam_size=args.beam, vad_filter=True
    )
    texts = [s.text.strip() for s in segments if s.text.strip()]
    print(f"duration={info.duration:.2f}s segs={len(texts)}")
    for t in texts:
        print(t)
    print("JOINED:", "".join(texts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
