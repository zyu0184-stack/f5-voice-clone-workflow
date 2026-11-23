"""调 voice-mini 的 HTTP 接口（带 DSH 本地 token），避免 curl 在 Windows 下把中文按 GBK 发出去。

用法：
  .venv\\Scripts\\python.exe tools\\vm_api.py state
  .venv\\Scripts\\python.exe tools\\vm_api.py config '{"backend":"clone"}'
  .venv\\Scripts\\python.exe tools\\vm_api.py test "宝宝，听得见吗？"
  .venv\\Scripts\\python.exe tools\\vm_api.py raw GET /voice-mini/providers
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

RUNTIME = Path(os.environ.get("VOICE_MINI_RUNTIME")
               or Path.home() / ".dsh" / "voice-mini" / "runtime.json")


def call(method, path, payload=None):
    rt = json.loads(RUNTIME.read_text(encoding="utf-8"))
    url = rt["origin"].rstrip("/") + path
    data = None
    headers = {"authorization": f"Bearer {rt['token']}"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def main(argv):
    cmd = argv[0] if argv else "state"
    if cmd == "state":
        code, body = call("GET", "/voice-mini/state")
    elif cmd == "config":
        code, body = call("POST", "/voice-mini/config", json.loads(argv[1]))
    elif cmd == "test":
        code, body = call("POST", "/voice-mini/test", {"text": argv[1]})
    elif cmd == "toggle":
        code, body = call("POST", "/voice-mini/session-toggle", {})
    elif cmd == "raw":
        method, path = argv[1], argv[2]
        payload = json.loads(argv[3]) if len(argv) > 3 else None
        code, body = call(method, path, payload)
    else:
        print(__doc__)
        return 2
    print(f"[http={code}]")
    try:
        print(json.dumps(json.loads(body), ensure_ascii=False, indent=2)[:4000])
    except Exception:
        print(body[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
