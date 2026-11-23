# -*- coding: utf-8 -*-
"""命令行客户端：调本地 F5 服务合成，验证 HTTP 链路。

用法：python scripts/tts_client.py "要合成的话" [voice] [out.wav]
环境变量：F5_TTS_URL（默认 http://127.0.0.1:18231）
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("F5_TTS_URL", "http://127.0.0.1:18231").rstrip("/")


def post(path, body, timeout=180):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                headers={"Content-Type": "application/json; charset=utf-8"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return raw, r.headers, time.time() - t0


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "宝贝，测试一下本地克隆音色行不行。"
    voice = sys.argv[2] if len(sys.argv) > 2 else "speaker_a"
    out = sys.argv[3] if len(sys.argv) > 3 else "out/srv_test.wav"
    raw, h, dt = post("/tts", {"text": text, "voice": voice})
    open(out, "wb").write(raw)
    print(f"OK {out} bytes={len(raw)} sr={h.get('X-TTS-Sr')} ms={h.get('X-TTS-Ms')} "
          f"voice={h.get('X-TTS-Voice')} wall={dt:.2f}s")


if __name__ == "__main__":
    main()
