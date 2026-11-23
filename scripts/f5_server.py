# -*- coding: utf-8 -*-
"""F5-TTS 常驻 HTTP 服务：给 dsh-voice-mini / dsh-duet 提供本地音色克隆。

启动（模型只加载一次，之后每句只推理）：
  .venv/Scripts/python.exe tools/f5_server.py --port 18231

接口：
  GET  /health          -> {"ok":true,"loaded":true,"device":"cuda","voices":[...]}
  GET  /voices          -> 注册表 voices.json 的内容
  POST /tts             body: {"text":"...","voice":"speaker_a","speed":1.0,"nfe":32,"cfg":2.0}
                        -> audio/wav (24 kHz mono int16)
  POST /tts.json        body 同上 -> {"ok":true,"path": "...", "dur": 3.2}（调试用，写文件）

单进程串行推理（一把锁），因为同一张卡上并发只会互相拖慢。
"""
import argparse
import io
import json
import traceback
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import soundfile as sf
import torch
import torchaudio

# torchaudio 2.11 走 torchcodec 解码（Windows 无 wheel），改回 soundfile
if not getattr(torchaudio, "_sf_patched", False):
    def _load(path, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(np.ascontiguousarray(data.T)), sr

    torchaudio.load = _load
    torchaudio._sf_patched = True

from f5_tts.api import F5TTS  # noqa: E402

STATE = {
    "tts": None,
    "lock": threading.Lock(),
    "voices": {},
    "voices_path": ROOT / "voices.json",
    "loaded_at": None,
    "calls": 0,
    "request_log": False,
}
MODELS = ROOT / "models"


def load_voices():
    p = STATE["voices_path"]
    if not p.exists():
        STATE["voices"] = {}
        return
    raw = json.loads(p.read_text(encoding="utf-8"))
    voices = {}
    for key, v in raw.items():
        ref = (ROOT / v["ref"]).resolve()
        if not ref.exists():
            print(f"[voices] skip {key}: missing {ref}", flush=True)
            continue
        voices[key] = {
            "name": v.get("name", key),
            "ref": str(ref),
            "ref_text": v.get("ref_text", ""),
            "speed": float(v.get("speed", 1.0)),
            "nfe": int(v.get("nfe", 32)),
            "cfg": float(v.get("cfg", 2.0)),
        }
    STATE["voices"] = voices
    try:
        STATE["voices_mtime"] = p.stat().st_mtime
    except OSError:
        STATE["voices_mtime"] = None
    print(f"[voices] {len(voices)} loaded: {', '.join(voices)}", flush=True)


def reload_if_changed():
    """voices.json 改了就用新的，不用重启服务。"""
    p = STATE["voices_path"]
    try:
        m = p.stat().st_mtime
    except OSError:
        return
    if m != STATE.get("voices_mtime"):
        load_voices()



def load_model(device="cuda"):
    t0 = time.time()
    tts = F5TTS(
        model="F5TTS_v1_Base",
        ckpt_file=str(MODELS / "F5TTS_v1_Base" / "model_1250000.safetensors"),
        vocab_file=str(MODELS / "F5TTS_v1_Base" / "vocab.txt"),
        vocoder_local_path=str(MODELS / "vocos-mel-24khz"),
        device=device,
    )
    wav_dir = MODELS / "vocos-mel-24khz" / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)
    STATE["tts"] = tts
    STATE["device"] = device
    STATE["loaded_at"] = time.time()
    print(f"[model] loaded on {device} in {time.time() - t0:.1f}s", flush=True)
    return tts


def resolve_voice(body):
    """body 可给 voice 键，也可直接给 ref/ref_text 内联。"""
    reload_if_changed()
    key = body.get("voice") or ""
    if key and key in STATE["voices"]:
        v = dict(STATE["voices"][key])
    elif body.get("ref"):
        ref = Path(body["ref"])
        if not ref.is_absolute():
            ref = (ROOT / ref).resolve()
        v = {
            "name": "inline",
            "ref": str(ref),
            "ref_text": body.get("ref_text", ""),
            "speed": 1.0, "nfe": 32, "cfg": 2.0,
        }
    elif STATE["voices"]:
        v = dict(next(iter(STATE["voices"].values())))
    else:
        raise ValueError("no voice: give voice key or ref path")
    if not Path(v["ref"]).exists():
        raise ValueError(f"ref not found: {v['ref']}")
    # 单条请求可覆盖参数
    for k in ("speed", "nfe", "cfg"):
        if body.get(k) is not None:
            v[k] = type(v[k])(body[k])
    if body.get("ref_text"):
        v["ref_text"] = body["ref_text"]
    return v


def synthesize(body):
    text = (body.get("text") or "").strip()
    if not text:
        raise ValueError("empty text")
    v = resolve_voice(body)
    tts = STATE["tts"]
    with STATE["lock"]:
        t0 = time.time()
        wav, sr, _ = tts.infer(
            ref_file=v["ref"],
            ref_text=v["ref_text"],
            gen_text=text,
            nfe_step=v["nfe"],
            cfg_strength=v["cfg"],
            speed=v["speed"],
            seed=body.get("seed"),
            show_info=lambda *a, **k: None,
        )
        STATE["calls"] += 1
        ms = int((time.time() - t0) * 1000)
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr[:, 0]
    return arr, int(sr), ms, v["name"]


def wav_bytes(arr, sr):
    buf = io.BytesIO()
    sf.write(buf, arr, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self):
        if self.path.startswith("/health"):
            if STATE["tts"] is None:
                return self._json(503, {"ok": False, "loaded": False})
            return self._json(200, {
                "ok": True, "loaded": True,
                "device": STATE.get("device", "?"),
                "calls": STATE["calls"],
                "voices": list(STATE["voices"]),
            })
        if self.path.startswith("/voices"):
            return self._json(200, {
                k: {"name": v["name"], "ref": str(Path(v["ref"]).relative_to(ROOT)), "ref_text": v["ref_text"]}
                for k, v in STATE["voices"].items()
            })
        return self._json(404, {"error": "not_found"})

    def do_POST(self):
        try:
            body = self._body()
        except Exception as e:
            return self._json(400, {"error": f"bad_json: {e}"})
        if STATE["tts"] is None:
            return self._json(503, {"error": "model_loading"})

        if STATE["request_log"] and self.path.startswith("/tts"):
            try:
                rec = {"t": round(time.time(), 3), "path": self.path, "voice": body.get("voice"),
                       "speed": body.get("speed"), "nfe": body.get("nfe"),
                       "chars": len(str(body.get("text") or "")), "text": body.get("text")}
                log_path = ROOT / "work" / "f5_requests.jsonl"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                traceback.print_exc()

        if self.path.startswith("/tts.json"):
            try:
                arr, sr, ms, name = synthesize(body)
            except Exception as e:
                traceback.print_exc()
                return self._json(400, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            out = ROOT / "out" / f"srv_{int(time.time() * 1000)}.wav"
            out.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out), arr, sr, subtype="PCM_16")
            return self._json(200, {"ok": True, "path": str(out), "dur": round(len(arr) / sr, 2),
                                    "sr": sr, "ms": ms, "voice": name})

        if self.path.startswith("/tts"):
            try:
                arr, sr, ms, name = synthesize(body)
            except Exception as e:
                traceback.print_exc()
                return self._json(400, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            data = wav_bytes(arr, sr)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-TTS-Sr", str(sr))
            self.send_header("X-TTS-Ms", str(ms))
            self.send_header("X-TTS-Voice", name.encode("ascii", "replace").decode())
            self.end_headers()
            self.wfile.write(data)
            return

        return self._json(404, {"error": "not_found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18231)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--request-log", action="store_true",
                    help="把每次合成请求（含全文）追加到 work/f5_requests.jsonl")
    a = ap.parse_args()
    STATE["request_log"] = a.request_log

    print(f"[boot] root={ROOT}", flush=True)
    load_voices()
    load_model(a.device)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print(f"[boot] listening http://{a.host}:{a.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("[boot] bye", flush=True)


if __name__ == "__main__":
    main()
