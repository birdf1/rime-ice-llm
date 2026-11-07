"""
clip_watcher.py —— 剪切板历史监控

用 ctypes 直调 Win32 API，不依赖第三方库。
作为后台线程挂在 llm_daemon.py 里跑，不额外起进程。

工作原理：
  GetClipboardSequenceNumber() 每次复制都会变，这个调用极轻（不加锁、不开剪切板），
  所以先比序号，只有变了才真正 OpenClipboard 读内容。
  这样轮询 0.4 秒一次的开销可以忽略，也不会跟别的程序抢剪切板。

输出：<RIME_LLM_DIR>/clip_cache.txt，每行一条，Lua 侧直接读
  <序号>\t<时间>\t<转义后的正文>
  转义：\\ -> \\\\，换行 -> \\n，制表 -> \\t
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
import time
from pathlib import Path

CF_UNICODETEXT = 13
CF_HDROP = 15

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetClipboardSequenceNumber.restype = wt.DWORD
user32.OpenClipboard.argtypes = [wt.HWND]
user32.OpenClipboard.restype = wt.BOOL
user32.CloseClipboard.restype = wt.BOOL
user32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
user32.IsClipboardFormatAvailable.restype = wt.BOOL
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE

kernel32.GlobalLock.argtypes = [wt.HANDLE]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HANDLE]
kernel32.GlobalUnlock.restype = wt.BOOL


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def _read_unicode_text() -> str | None:
    """读剪切板里的 Unicode 文本。剪切板可能被别的程序占用，重试几次。"""
    for _ in range(6):
        if user32.OpenClipboard(None):
            try:
                if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    h = user32.GetClipboardData(CF_UNICODETEXT)
                    if h:
                        p = kernel32.GlobalLock(h)
                        if p:
                            try:
                                s = ctypes.wstring_at(p)
                            finally:
                                kernel32.GlobalUnlock(h)
                            s = s.rstrip("\x00")
                            if s.strip():
                                return s
                return None
            finally:
                user32.CloseClipboard()
        time.sleep(0.05)
    return None


def _read_file_list() -> str | None:
    """复制文件时给出一行一个路径，方便粘贴。"""
    if not user32.OpenClipboard(None):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_HDROP):
            return None
        h = user32.GetClipboardData(CF_HDROP)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.DragQueryFileW.argtypes = [wt.HANDLE, wt.UINT, wt.LPWSTR, wt.UINT]
            shell32.DragQueryFileW.restype = wt.UINT
            n = shell32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
            if n <= 0:
                return None
            paths = []
            for i in range(min(n, 20)):
                buf = ctypes.create_unicode_buffer(1024)
                if shell32.DragQueryFileW(h, i, buf, 1024):
                    paths.append(buf.value)
            return "\n".join(paths) if paths else None
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


class ClipboardWatcher(threading.Thread):
    """后台线程：盯剪切板，变化就记一条历史，写进 rime 能读的文件。"""

    daemon = True

    def __init__(self, out_file: Path, poll: float = 0.4,
                 max_items: int = 40, max_len: int = 4000) -> None:
        super().__init__(name="ClipboardWatcher", daemon=True)
        self.out_file = Path(out_file)
        self.poll = poll
        self.max_items = max_items
        self.max_len = max_len
        self._items: list[tuple[str, str]] = []      # (时间, 正文)
        self._stop = threading.Event()
        self._last_seq = 0
        self._dirty = False

    # ── 历史维护 ────────────────────────────────────────────
    def _add(self, text: str) -> None:
        text = text[: self.max_len]
        if self._items and self._items[0][1] == text:
            return                                    # 和最新一条重复
        # 去重：挪到最前
        self._items = [(t, s) for (t, s) in self._items if s != text]
        self._items.insert(0, (time.strftime("%H:%M"), text))
        del self._items[self.max_items :]
        self._dirty = True

    def _flush(self) -> None:
        if not self._dirty:
            return
        lines = [
            f"{i}\t{tm}\t{_escape(s)}"
            for i, (tm, s) in enumerate(self._items, 1)
        ]
        body = "\n".join(lines) + ("\n" if lines else "")
        tmp = self.out_file.with_suffix(".tmp")
        try:
            self.out_file.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(self.out_file)                # 原子替换，Lua 不会读到半个文件
            self._dirty = False
        except OSError:
            pass                                      # 写不了就算了，不能影响主循环

    # ── 线程主体 ────────────────────────────────────────────
    def run(self) -> None:
        self._flush()
        while not self._stop.is_set():
            try:
                seq = user32.GetClipboardSequenceNumber()
                if seq and seq != self._last_seq:
                    self._last_seq = seq
                    text = _read_unicode_text() or _read_file_list()
                    if text:
                        self._add(text)
                        self._flush()
            except Exception:
                pass                                  # 任何异常都吞掉，守护线程不能死
            self._stop.wait(self.poll)

    def stop(self) -> None:
        self._stop.set()

    # 供 --status 用
    def stats(self) -> dict:
        return {"count": len(self._items), "file": str(self.out_file)}
