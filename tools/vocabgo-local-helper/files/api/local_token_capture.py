# Local modifications: NexD5701 with AI assistance, 2026-10-18.
# Upstream: ularch/Easy_Cidaren; see the distribution NOTICE.md and LICENSE.
"""Local Windows login capture with scoped interception and recoverable settings."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
from importlib.util import find_spec
import socket
import subprocess
import sys
import threading
import time

from log.log import Log

service_logger = Log("token_capture_service").logger
STATE_DIR = Path(__file__).resolve().parents[1] / ".local-state" / "capture"
STATE_FILE = STATE_DIR / "restore.json"
PROXY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
PROXY_NAMES = ("ProxyEnable", "ProxyServer", "ProxyOverride")


def _save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(STATE_FILE)


def _snapshot_proxy():
    import winreg
    values = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_KEY, 0, winreg.KEY_READ) as key:
        for name in PROXY_NAMES:
            try:
                value, kind = winreg.QueryValueEx(key, name)
                values[name] = {"value": value, "kind": kind}
            except FileNotFoundError:
                values[name] = None
    return values


def _notify_proxy():
    for option in (39, 37):
        ctypes.windll.Wininet.InternetSetOptionW(0, option, 0, 0)


def _set_proxy(values):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for name in PROXY_NAMES:
            entry = values[name]
            if entry is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, entry["kind"], entry["value"])
    _notify_proxy()


def _certutil(*arguments):
    return subprocess.run(
        ["certutil", *arguments], capture_output=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _certificate_thumbprint():
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    certificate = (STATE_DIR / "ca" / "mitmproxy-ca-cert.cer").read_bytes()
    if b"BEGIN CERTIFICATE" in certificate:
        parsed = x509.load_pem_x509_certificate(certificate)
    else:
        parsed = x509.load_der_x509_certificate(certificate)
    return hashlib.sha1(parsed.public_bytes(serialization.Encoding.DER)).hexdigest().upper()


def restore_capture_state():
    """Restore only this capture's proxy snapshot and exact newly imported certificate."""
    if not STATE_FILE.exists():
        return False
    if sys.platform != "win32":
        raise RuntimeError("此本机恢复入口仅适用于 Windows。")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if state.get("proxy_applied"):
        _set_proxy(state["proxy_values"])
        state["proxy_applied"] = False
        _save_state(state)
    thumbprint = state.get("new_certificate")
    if thumbprint:
        if not re.fullmatch(r"[A-F0-9]{40}", thumbprint) or thumbprint != _certificate_thumbprint():
            raise RuntimeError("证书记录不匹配，已停止自动移除，请人工检查。")
        if _certutil("-user", "-store", "Root", thumbprint).returncode == 0:
            if _certutil("-user", "-delstore", "Root", thumbprint).returncode != 0:
                raise RuntimeError("临时证书移除失败，请重新运行“恢复网络设置.cmd”。")
    STATE_FILE.unlink()
    (STATE_DIR / "token.txt").unlink(missing_ok=True)
    (STATE_DIR / "token.txt.tmp").unlink(missing_ok=True)
    return True


class TokenCaptureService:
    def __init__(self, fetch_token_path):
        self.fetch_token_path = fetch_token_path
        self.mitm_process = None
        self._is_running = False
        self._cleanup_lock = threading.Lock()
        self._cleaned_up = False
        self._owns_state = False

    def start_capture(self, status_callback=None, token_callback=None, error_callback=None):
        status = status_callback or (lambda message: None)
        error = error_callback or (lambda message: None)
        token = None
        self._is_running = True
        self._cleaned_up = False
        try:
            if sys.platform != "win32":
                raise RuntimeError("此本机配置仅适用于 Windows。")
            if STATE_FILE.exists():
                raise RuntimeError("上次接入尚未恢复，请先双击“恢复网络设置.cmd”。")
            if find_spec("mitmproxy") is None:
                raise RuntimeError("运行环境不完整，请从项目的“启动词达人助手.cmd”打开。")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 8888))
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            token_file = STATE_DIR / "token.txt"
            token_file.unlink(missing_ok=True)
            state = {"proxy_values": _snapshot_proxy(), "proxy_applied": False,
                     "new_certificate": None}
            _save_state(state)
            self._owns_state = True
            child_env = os.environ.copy()
            child_env["CIDAREN_TOKEN_FILE"] = str(token_file)
            status("正在启动本机接入服务，仅检查 app.vocabgo.com 的登录请求…")
            self.mitm_process = subprocess.Popen(
                [str(Path(sys.executable).with_name("python.exe")), "-c",
                 "from mitmproxy.tools.main import mitmdump; mitmdump()",
                 "-s", str(Path(self.fetch_token_path) / "addon.py"),
                 "--listen-host", "127.0.0.1", "--listen-port", "8888", "--quiet",
                 "--set", "confdir=" + str(STATE_DIR / "ca"),
                 "--set", r"allow_hosts=^app\.vocabgo\.com(:443)?$",
                 "--set", "flow_detail=0"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            certificate_path = STATE_DIR / "ca" / "mitmproxy-ca-cert.cer"
            ready_deadline = time.monotonic() + 20
            while self._is_running and time.monotonic() < ready_deadline:
                if self.mitm_process.poll() is not None:
                    raise RuntimeError("本机接入服务启动失败。")
                if certificate_path.exists() and self._is_port_in_use(8888):
                    break
                time.sleep(0.2)
            else:
                if not self._is_running:
                    return None
                raise RuntimeError("本机接入服务启动超时。")
            thumbprint = _certificate_thumbprint()
            if _certutil("-user", "-store", "Root", thumbprint).returncode != 0:
                state["new_certificate"] = thumbprint
                _save_state(state)
                status("正在临时信任本工具的本地证书；如 Windows 弹出确认，请核对后操作。")
                if _certutil("-addstore", "-f", "-user", "Root", str(certificate_path)).returncode != 0:
                    raise RuntimeError("本地证书未获信任，接入已取消。")
            if not self._is_running:
                return None
            import winreg
            state["proxy_applied"] = True
            _save_state(state)
            _set_proxy({"ProxyEnable": {"kind": winreg.REG_DWORD, "value": 1},
                        "ProxyServer": {"kind": winreg.REG_SZ, "value": "127.0.0.1:8888"},
                        "ProxyOverride": {"kind": winreg.REG_SZ, "value": "<local>"}})
            status("请在电脑版微信打开词达人学生端，进入班级任务。等待时间为 3 分钟。")
            capture_deadline = time.monotonic() + 180
            while self._is_running and time.monotonic() < capture_deadline:
                if self.mitm_process.poll() is not None:
                    raise RuntimeError("本机接入服务已退出。")
                if token_file.exists():
                    candidate = token_file.read_text(encoding="utf-8").strip()
                    if candidate:
                        token = candidate
                        token_file.unlink(missing_ok=True)
                        break
                time.sleep(0.25)
            if self._is_running and not token:
                raise RuntimeError("等待登录超时，请确认在电脑版微信中进入了词达人班级任务。")
        except Exception as exception:
            service_logger.error("本机登录接入失败：%s", exception)
            error(str(exception))
        finally:
            if not self.cleanup(status):
                token = None
                error("网络设置未能完整恢复，请先双击“恢复网络设置.cmd”。")
        if token:
            status("登录授权已获取，原代理和临时证书已恢复。")
            if token_callback:
                token_callback(token)
        return token

    def _is_port_in_use(self, port):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            return False

    def cleanup(self, status_callback=None):
        with self._cleanup_lock:
            if self._cleaned_up:
                return True
            success = True
            try:
                if self._owns_state:
                    restore_capture_state()
                    if status_callback:
                        status_callback("网络设置已恢复。")
            except Exception:
                service_logger.exception("恢复设置失败；本机恢复记录已保留。")
                success = False
            finally:
                if self.mitm_process and self.mitm_process.poll() is None:
                    self.mitm_process.terminate()
                    try:
                        self.mitm_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.mitm_process.kill()
                        self.mitm_process.wait(timeout=5)
                if self._owns_state:
                    (STATE_DIR / "token.txt").unlink(missing_ok=True)
                    (STATE_DIR / "token.txt.tmp").unlink(missing_ok=True)
                self._is_running = False
                self._cleaned_up = success
            return success

    def stop(self):
        self._is_running = False
