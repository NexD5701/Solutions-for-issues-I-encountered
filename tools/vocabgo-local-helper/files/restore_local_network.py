# Local modifications: NexD5701 with AI assistance, 2026-10-18.
# Upstream: ularch/Easy_Cidaren; see the distribution NOTICE.md and LICENSE.
"""User-invoked recovery for this project's login capture only."""
import ctypes
from api.local_token_capture import restore_capture_state

try:
    changed = restore_capture_state()
    message = "已恢复本工具记录的原代理，并移除本次添加的临时证书。" if changed else "没有待恢复的本机接入记录。"
    ctypes.windll.user32.MessageBoxW(None, message, "网络恢复", 0x40)
except Exception as error:
    ctypes.windll.user32.MessageBoxW(None, "恢复尚未完成：\n" + str(error), "网络恢复", 0x10)
