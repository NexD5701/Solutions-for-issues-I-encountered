# Local modifications: NexD5701 with AI assistance, 2026-10-18.
# Upstream: ularch/Easy_Cidaren; see the distribution NOTICE.md and LICENSE.
"""Launch the reviewed source copy using its project-local Python runtime."""
import ctypes
import os
from pathlib import Path
import runpy
import sys
import traceback

root = Path(__file__).resolve().parent
runtime = root.parent / ".setup" / "python"
os.chdir(root)
os.environ["PATH"] = str(runtime / "Scripts") + os.pathsep + os.environ.get("PATH", "")
os.environ["CIDAREN_SKIP_UPDATE"] = "1"


def show_error(exception_type, exception, tb):
    state_dir = root / ".local-state"
    state_dir.mkdir(exist_ok=True)
    error_file = state_dir / "startup-error.txt"
    error_file.write_text("".join(traceback.format_exception(exception_type, exception, tb)),
                          encoding="utf-8")
    ctypes.windll.user32.MessageBoxW(
        None, "启动遇到问题。错误记录位于：\n" + str(error_file),
        "词达人助手", 0x10,
    )


sys.excepthook = show_error
try:
    runpy.run_path(str(root / "main.py"), run_name="__main__")
except Exception:
    show_error(*sys.exc_info())
