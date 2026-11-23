"""把 f5_server.py 以完全脱离的方式拉起来（父进程退出也不影响），日志写 work/f5_console.log。

用法：.venv\\Scripts\\python.exe tools\\start_f5.py [--port 18231] [--restart]
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
SERVER = ROOT / "tools" / "f5_server.py"
LOG = ROOT / "work" / "f5_console.log"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def port_of(argv):
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            return int(argv[i + 1])
    return 18231


def healthy(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return b'"loaded": true' in r.read() or b'"ok": true' in r.read()
    except Exception:
        return False


def main(argv):
    port = port_of(argv)
    if healthy(port):
        print(f"already running on {port}")
        return 0
    LOG.parent.mkdir(parents=True, exist_ok=True)
    out = open(LOG, "ab")
    detach = ({"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP}
              if os.name == "nt" else {"start_new_session": True})
    proc = subprocess.Popen(
        [str(PY), str(SERVER), "--port", str(port)],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=subprocess.STDOUT,
        close_fds=True,
        **detach,
    )
    print(f"spawned pid={proc.pid} port={port} log={LOG}")
    deadline = time.time() + 180
    while time.time() < deadline:
        if healthy(port):
            print(f"ready on {port} after {round(time.time() - (deadline - 180), 1)}s")
            return 0
        if proc.poll() is not None:
            print(f"exited early with code {proc.returncode}; see {LOG}")
            return 1
        time.sleep(1.5)
    print(f"timeout waiting for {port}; see {LOG}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
