#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_daemon.py —— 小狼毫「前文联写」后台守护

═══════════════════════════════════════════════════════════════════
设计定位（2026-11-06 实测后确定，别再改回拼音转汉字）
═══════════════════════════════════════════════════════════════════

❌ 不做「拼音 → 汉字」：1.5b/3b 小模型干这个是灾难。
   实测 zhegegongnengbucuo → 「这个功能出错」（错，是不错）
        womenzai         → 「女人在」（错，是我们）
        duibuqi          → 「不对质」（错，是对不起）
   rime 自己 57MB 的词库 + 用户词典比小模型准得多。

✅ 做「已输入的文字 → 预测下一个词」：这是语言建模任务，小模型擅长。
   实测「我刚吃完饭，准备去」→ 散步 / 看电影 / 购物 / 看书（40-200ms）
        「这个问题比较复杂，需要」→ 深入分析
        「这个功能的设计思路是」→ 用户体验优化
   这才是微信输入法"感觉聪明"的真正来源，也是它比开源强的核心。

Lua 侧只做文件读写（微秒级），本进程负责调 Ollama。
主线程永不等待网络 → 模型再慢也不会卡打字。

用法：
  python llm_daemon.py              # 前台跑
  python llm_daemon.py --once       # 处理一遍就退出
  python llm_daemon.py --status     # 看状态
  python llm_daemon.py --install    # 装开机自启
  python llm_daemon.py --uninstall  # 移除自启
"""

import argparse
import bisect
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.request
import zlib
from array import array
from datetime import datetime
from pathlib import Path

# ─────────────────────────── 配置 ───────────────────────────
RIME_DIR   = Path(r"E:\APPs\小狼毫")
# ⚠️ 数据目录必须纯 ASCII：Lua 的 io.open 在 Windows 上打不开中文路径
DATA_DIR   = Path(r"E:\APPs\rime-llm")
REQ_FILE   = DATA_DIR / "llm_req.txt"
CACHE_FILE = DATA_DIR / "llm_cache.txt"
LOG_FILE   = DATA_DIR / "llm_daemon.log"
CLIP_FILE  = DATA_DIR / "clip_cache.txt"   # 剪切板历史（供 lua 读）

OLLAMA     = "http://127.0.0.1:11434"
# 模型选择（2026-11-06 横评实测后定，别再迷信大模型）
#
#  模型            有效   热平均   冷启动   体积
#  qwen2.5:0.5b    8/8    51 ms    14.4s   397 MB   ← 只复述你打过的词，无用
#  qwen3:0.6b      0/8  2196 ms    37.7s   522 MB   ← 思考模式污染输出，废
#  qwen2.5:3b      8/8   111 ms     2.0s   1.9 GB   ← ★ 默认
#  qwen2.5:7b      8/8   376 ms    14.6s   4.7 GB   ← 质量最好但太重
#
# 为什么不用 0.5b：它倾向于把上文里的词原样吐回来。
#   「这个功能的设计思路是」→ 开发/功能/设计（抄）
#   「今天下午的会议改到了三点半，我们」→ 会议/时间/安排（抄）
#   而 7b 给的是「用户体验/优先考虑/简化操作」「需要/提前/出发」。
#   输入法的联想如果只是复述，用户要它干什么？
#
# 为什么默认 3b 不是 7b：3b 冷启动只要 2 秒、显存 4.7G→1.9G，
#   质量虽不如 7b 但可用（「请大家」→ 到场/准时/参加）。
#   7b 冷启动 14.6 秒，配上短 keep_alive 每次回来都要等半天。
MODEL      = os.environ.get("RIME_LLM_MODEL", "hf.co/openbmb/MiniCPM4-0.5B-QAT-Int4-GGUF")
TIMEOUT    = 60         # 单次请求超时（秒）—— CPU 模式首次要 3 秒，放宽
POLL       = 0.35       # 轮询间隔（秒）
CACHE_TTL  = 900        # 缓存有效期（秒）
MAX_CACHE  = 5000       # 缓存行数上限
MAX_WORDS  = 3          # 每个上文最多给几个候选
SAMPLES    = 3          # base 模型采样次数（多次采样提升小模型的候选覆盖面）
CTX_KEEP   = 30         # 取上文最后多少字

# ★★ 决定跑 GPU 还是 CPU —— 资源占用的关键开关
#
#   NUM_GPU = 0   → 纯 CPU：显存占用 0，内存约 2 GB，约 500 ms/次
#   NUM_GPU = -1  → 全部塞 GPU：显存约 2 GB，约 110 ms/次
#   NUM_GPU = 12  → 前 12 层放 GPU，其余 CPU（折中）
#
# 为什么默认选 CPU（0）：
#   1. 联想是**异步**的。lua 只写个请求文件立刻返回，主线程从不等待模型。
#      所以 500ms 完全无感 —— 你多打一两个字母，候选就出来了。
#   2. 显存是这台机器最稀缺的资源（6 GB，还要给桌面/浏览器/游戏留）。
#      内存有 31.7 GB，平时空着 18 GB。
#   3. 跑 CPU 时显存占用**恒为 0**，输入法对显卡完全零侵入。
#
# 想换回显卡：设环境变量 RIME_LLM_NUM_GPU=-1
NUM_GPU    = int(os.environ.get("RIME_LLM_NUM_GPU", "0"))

# 模型多久不活动就从内存/显存卸载
#   CPU 模式内存便宜，给 10 分钟，减少反复加载
#   GPU 模式显存金贵，给 2 分钟
KEEP_ALIVE = os.environ.get(
    "RIME_LLM_KEEPALIVE",
    "600s" if NUM_GPU == 0 else "120s",
)

TASK_NAME  = "RimeLLMDaemon"

# ─────────────────────────── 日志 ───────────────────────────
def log(msg: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass

# ─────────────────────────── Ollama ───────────────────────────
OLLAMA_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
_ollama_fail = 0          # 连续失败次数
_ollama_restart_at = 0.0  # 下次允许重启的时间戳

def ollama_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False

def ensure_ollama() -> bool:
    """
    Ollama 挂了就自动拉起来。
    实测：Ollama 自己会莫名其妙退出（20:57 就挂过一次），
    不自动恢复的话联想功能就静默失效了。
    """
    global _ollama_fail, _ollama_restart_at
    if ollama_alive():
        _ollama_fail = 0
        return True

    _ollama_fail += 1
    now = time.time()
    # 最多每 60 秒尝试拉起一次，避免疯狂重启
    if now < _ollama_restart_at:
        return False
    _ollama_restart_at = now + 60

    if not OLLAMA_EXE.exists():
        log(f"Ollama 未运行且找不到 {OLLAMA_EXE}")
        return False

    log(f"Ollama 未响应（连续 {_ollama_fail} 次），尝试自动拉起")
    try:
        subprocess.Popen(
            [str(OLLAMA_EXE), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        log(f"拉起失败: {e}")
        return False

    for _ in range(15):          # 最多等 15 秒
        time.sleep(1)
        if ollama_alive():
            log("Ollama 已恢复")
            _ollama_fail = 0
            return True
    log("Ollama 拉起后仍未就绪")
    return False

def ollama_models() -> list[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as r:
            data = json.load(r)
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []

def ollama_loaded() -> dict[str, str]:
    """
    查当前有哪些模型真的在显存里。
    /api/tags 只列磁盘上的模型，不反映显存占用，必须用 /api/ps。

    ⚠️ 注意 size_vram 可能是 0（纯 CPU 推理）。这时**不能用 `or` 回退到 size**，
       否则会把「内存占用」误报成「显存占用」——
       我上一版就犯了这个错，显示「2,068 MiB VRAM」，实际是 0 显存 + 2GB 内存。
    """
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=3) as r:
            data = json.load(r)
        out = {}
        for m in data.get("models", []):
            name = m.get("name", "?")
            vram = m.get("size_vram", 0) or 0
            ram = m.get("size", 0) or 0
            if vram > 0:
                out[name] = f"{vram / 1024 / 1024:,.0f} MiB 显存"
            else:
                out[name] = f"0 显存（纯 CPU，占 {ram / 1024 / 1024:,.0f} MiB 内存）"
        return out
    except Exception:
        return {}

def _generate_once(context: str, seed: int, temperature: float) -> str:
    """
    一次裸补全。raw=true 表示**不加对话模板** ——
    这是关键：base 模型会老老实实接着往下写，
    而 instruct 模型会回你「好的，接下来最可能的3个词是：…」这种废话。
    """
    payload = json.dumps({
        "model": MODEL,
        "prompt": context,
        "raw": True,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {
            "temperature": temperature,
            "num_predict": 12,
            "top_p": 0.92,
            "num_gpu": NUM_GPU,
            "seed": seed,
            # ⚠️ 只按换行停，**不要按标点停**。
            #    踩过的坑：模型对「哦今天天气很好」的续写是「，好到可以骑驴去山」，
            #    第一个字符就是逗号，若把「，」写进 stop，服务端立刻截断 → 返回空串，
            #    整个上文就永远拿不到候选。改为本地切分，见 candidates_from()。
            "stop": ["\n"],
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = json.load(r)
    return body.get("response", "")

def predict_next(context: str) -> list[str]:
    """
    根据上文预测接下来的词。

    做法：让 base 模型补全 3 次（不同 seed），每次取前 2~4 个字当候选。
    为什么要采 3 次：0.5B 的小模型单次输出不稳定，多次采样能覆盖更多合理答案，
    而且它只要 ~50ms，采 3 次也才 150ms，完全在异步可接受范围内。
    """
    out: list[str] = []
    seen: set[str] = set()
    last_err = None

    for i in range(SAMPLES):
        try:
            raw = _generate_once(context, seed=(i + 1) * 7919,
                                 temperature=0.5 + i * 0.18)
        except Exception as e:
            last_err = e
            continue

        for w in candidates_from(raw, context):
            if w in seen:
                continue
            seen.add(w)
            out.append(w)
            if len(out) >= MAX_WORDS:
                return out

    if not out and last_err:
        log(f"模型调用失败: {last_err}")
    return out

# 不能作为候选开头的虚词/介词/连词。
# 模型的续写是整个从句（「从多个角度进行分析」），直接截前 2 字会得到「从多」这种废话。
# 一条候选词不可能以介词开头，所以直接丢弃。
_NO_START = set("从对把被在和与的地得着了着过再又还也都就才而且或但 是之以于为给让使向往由经除连跟同按据")

# 结尾是这些助词时剪掉，让「进一步的」变成可用的「进一步」
_TRIM_TAIL = set("的了着过地得们呢吧啊")

# ─────────────────── 词表校验（过滤半截词）───────────────────
# 用 rime 自己那 189 万条词库做校验。切出来的候选不在词表里就丢掉，
# 这样「进一」「今天的工」「将用户输」都会被拦下，「准时」「公园散步」会留下。
# 存的是 crc32 哈希（4 字节/词），全表 1.4M 词只占 5.35 MB。
_WORDS: dict[int, array] = {2: array("I"), 3: array("I"), 4: array("I")}
_words_loaded = False


def load_wordlist() -> None:
    global _words_loaded
    if _words_loaded:
        return
    _words_loaded = True
    p = DATA_DIR / "wordlist.bin"
    if not p.exists():
        log("词表不存在（wordlist.bin），跳过候选校验")
        return
    try:
        with open(p, "rb") as f:
            n2, n3, n4 = struct.unpack("<3I", f.read(12))
            for n, cnt in ((2, n2), (3, n3), (4, n4)):
                arr = array("I")
                arr.frombytes(f.read(cnt * 4))
                _WORDS[n] = arr
        log(f"词表已加载: 2字{len(_WORDS[2]):,} 3字{len(_WORDS[3]):,} 4字{len(_WORDS[4]):,}")
    except Exception as e:
        log(f"词表加载失败: {e}")


def is_word(w: str) -> bool:
    """查这个词是不是真词。词表没加载成功时一律放行（fail-open）。"""
    arr = _WORDS.get(len(w))
    if arr is None:
        return True
    if len(arr) == 0:
        return True
    h = zlib.crc32(w.encode("utf-8")) & 0xFFFFFFFF
    i = bisect.bisect_left(arr, h)
    return i < len(arr) and arr[i] == h


def candidates_from(raw: str, context: str) -> list[str]:
    """
    把一个续写结果切成候选词。

    例：「准时参加」        → 准时 / 准时参加
        「，好到可以骑驴去」 → 好到 / 好到可以   （开头逗号先剥掉）
        「从多个角度进行分析」→ （丢弃，「从」不能开头）

    分三步：
      1. 剥掉开头标点，再在第一个停顿处截断（服务端不截，本地截）
      2. 不能以虚词开头 —— 避免「从多」「对多」这种半截词
      3. 结尾助词剪掉  —— 「进一步的」→「进一步」
    """
    # 剥掉开头的标点/空白（模型常以逗号起头），然后在第一个停顿处切断
    raw = raw.lstrip("。，、！？：；\n\r\t （）《》\"'“”‘’.,!?:;")
    raw = re.split(r"[。，、！？：；\n\r（）《》\"'“”‘’]", raw, maxsplit=1)[0]

    w = re.sub(r"[^\u4e00-\u9fff]", "", raw)   # 只留汉字
    # 结尾助词剪掉（但别剪空）
    while len(w) > 2 and w[-1] in _TRIM_TAIL:
        w = w[:-1]
    if len(w) < 2:
        return []
    # 以虚词开头 → 整条没法当候选
    if w[0] in _NO_START:
        return []

    picks: list[str] = [w[:2]]                 # 最常见：双字词
    if 3 <= len(w) <= 4:
        picks.append(w)                        # 完整词
    elif len(w) > 4:
        picks.append(w[:4])                    # 太长就截到 4 字

    out: list[str] = []
    for cand in picks:
        while len(cand) > 2 and cand[-1] in _TRIM_TAIL:
            cand = cand[:-1]
        if len(cand) < 2:
            continue
        if cand in context:                    # 别把上文原样吐回来
            continue
        if not is_word(cand):                  # 词表里没有 → 半截词，丢掉
            continue
        if cand not in out:
            out.append(cand)
    return out

# ─────────────────────────── 缓存读写 ───────────────────────────
def load_cache() -> dict[str, tuple[str, int]]:
    if not CACHE_FILE.exists():
        return {}
    out: dict[str, tuple[str, int]] = {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2:
                    ts = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
                    out[parts[0]] = (parts[1], ts)
    except OSError:
        pass
    return out

def write_cache(cache: dict[str, tuple[str, int]]) -> None:
    """原子写，避免 lua 读到半个文件。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    items = [(k, v) for k, v in cache.items() if now - v[1] < CACHE_TTL]
    if len(items) > MAX_CACHE:
        items.sort(key=lambda kv: kv[1][1], reverse=True)
        items = items[:MAX_CACHE]
    tmp = CACHE_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for k, (w, ts) in items:
                f.write(f"{k}\t{w}\t{ts}\n")
        os.replace(tmp, CACHE_FILE)
    except OSError as e:
        log(f"写缓存失败: {e}")

def drain_requests() -> list[str]:
    """读走所有待处理上文（读后清空）。"""
    if not REQ_FILE.exists():
        return []
    try:
        raw = REQ_FILE.read_text(encoding="utf-8")
        REQ_FILE.write_text("", encoding="utf-8")
    except OSError:
        return []
    out: list[str] = []
    for line in raw.splitlines():
        ctx = line.strip()[:CTX_KEEP]
        # 至少 3 个汉字才值得预测
        if len(re.findall(r"[\u4e00-\u9fff]", ctx)) >= 3:
            out.append(ctx)
    return out

# ─────────────────────────── 主逻辑 ───────────────────────────
def run_once() -> int:
    ctxs = drain_requests()
    if not ctxs:
        return 0
    cache = load_cache()
    now = int(time.time())
    done = 0
    seen: set[str] = set()
    for ctx in ctxs:
        if ctx in seen:
            continue
        seen.add(ctx)
        old = cache.get(ctx)
        if old and now - old[1] < CACHE_TTL:
            continue

        words = predict_next(ctx)
        if not words:
            # 可能是 Ollama 掉了：先确保它在，再重试一次
            if ensure_ollama():
                words = predict_next(ctx)
        if words:
            cache[ctx] = ("|".join(words), int(time.time()))
            done += 1
            log(f"[{ctx}] -> {'/'.join(words)}")
        # 失败不写缓存：下次按键会重新入队重试
    write_cache(cache)
    return done

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--unload", action="store_true", help="把模型从显存卸载")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.status:
        alive = ollama_alive()
        print(f"Ollama : {'运行中' if alive else '未运行'} ({OLLAMA})")
        if alive:
            ms = ollama_models()
            print(f"模型   : {', '.join(ms) or '（无）'}")
            print(f"使用中 : {MODEL}")
            # 显存实际占用：区分「模型在显存里」和「已卸载」
            loaded = ollama_loaded()
            if loaded:
                for name, size in loaded.items():
                    print(f"显存中 : {name}  {size}")
            else:
                print("显存中 : （无模型常驻，已释放）")
            print(f"keep_alive: {KEEP_ALIVE}（超过这个时间不活动就卸载）")
        c = load_cache()
        live = sum(1 for v in c.values() if int(time.time()) - v[1] < CACHE_TTL)
        print(f"缓存   : {len(c)} 条（有效 {live}）")
        print(f"待处理 : {len(drain_requests())} 条")
        try:
            n = 0
            if CLIP_FILE.exists():
                n = sum(1 for _ in CLIP_FILE.open(encoding="utf-8"))
            print(f"剪切板 : {n} 条历史（{CLIP_FILE}）")
        except OSError:
            pass
        return 0

    if args.unload:
        # 手动把模型踢出显存，立等可用
        try:
            payload = json.dumps({"model": MODEL, "keep_alive": 0}).encode()
            req = urllib.request.Request(
                f"{OLLAMA}/api/generate", data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                pass
            print(f"已把 {MODEL} 从显存卸载")
        except Exception as e:
            print(f"卸载失败: {e}")
            return 1
        return 0

    if args.install:
        py = sys.executable
        script = str(Path(__file__).resolve())
        cmd = (f'schtasks /Create /TN "{TASK_NAME}" '
               f'/TR "\"{py}\" \"{script}\"" /SC ONLOGON /RL LIMITED /F')
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        print(r.stdout or r.stderr)
        return 0 if r.returncode == 0 else 1

    if args.uninstall:
        r = subprocess.run(f'schtasks /Delete /TN "{TASK_NAME}" /F',
                           shell=True, capture_output=True, text=True)
        print(r.stdout or r.stderr)
        return 0

    if args.once:
        ensure_ollama()
        load_wordlist()
        n = run_once()
        print(f"处理 {n} 条")
        return 0

    # 剪切板监控作为后台线程，不额外起进程（省内存）
    try:
        from clip_watcher import ClipboardWatcher
        watcher = ClipboardWatcher(CLIP_FILE)
        watcher.start()
        log(f"剪切板监控已启动 -> {CLIP_FILE}")
    except Exception as e:
        log(f"剪切板监控未启动: {e}（不影响打字和联想）")

    log(f"启动 | 模型={MODEL} | 轮询={POLL}s | 任务=前文联写")
    load_wordlist()
    if not ensure_ollama():
        log("Ollama 未就绪，会持续尝试拉起（不影响打字）")
    idle = 0
    while True:
        try:
            n = run_once()
            if n:
                idle = 0
            else:
                idle += 1
                # 每约 2 分钟体检一次，挂了就拉起来
                if idle % 350 == 0:
                    ensure_ollama()
        except KeyboardInterrupt:
            log("退出")
            break
        except Exception as e:
            log(f"循环异常: {e}")
        time.sleep(POLL)
    return 0

if __name__ == "__main__":
    sys.exit(main())
