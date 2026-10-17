"""Check the real local service without changing proxies, trust stores, or account data."""
from pathlib import Path
import os
import subprocess
import sys
import time

workspace = Path(__file__).resolve().parents[1]
confdir = workspace / ".setup" / "listener-check"
addon = workspace / "Easy_Cidaren" / "get token" / "fetch_token" / "addon.py"
command = [str(Path(sys.executable).with_name("python.exe")), "-c",
           "from mitmproxy.tools.main import mitmdump; mitmdump()",
           "-s", str(addon), "--listen-host", "127.0.0.1", "--listen-port", "0",
           "--quiet", "--set", "confdir=" + str(confdir),
           "--set", r"allow_hosts=^app\.vocabgo\.com(:443)?$", "--set", "flow_detail=0"]
process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=subprocess.CREATE_NO_WINDOW)
try:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output, errors = process.communicate()
            raise RuntimeError(errors.decode("utf-8", errors="replace"))
        if (confdir / "mitmproxy-ca-cert.cer").exists():
            time.sleep(1)
            if process.poll() is None:
                print("Local service starts with the reviewed options and addon; no system settings changed.")
                break
        time.sleep(0.2)
    else:
        raise RuntimeError("Local service did not initialize before timeout")
finally:
    if process.poll() is None:
        process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)
