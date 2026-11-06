#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_llm_translator.py —— 用 lupa 在真实 Lua 解释器里单元测试 llm_translator.lua

为什么需要这个：librime-lua 是懒加载，服务启动时不挂载 lua 模块。
靠"部署时看日志有没有报错"是**无效的验证**（实测自带模块写错也不报错）。
所以直接把 lua 文件塞进真 Lua 解释器，mock 掉 rime 的全局（yield / Candidate / rime_api），
就能确定性地验证语法和逻辑。

跑法：C:\\Python313\\python.exe test_llm_translator.py
"""

import sys
import time
from pathlib import Path

from lupa import LuaRuntime

LUA_FILE = Path(r"E:\APPs\小狼毫\lua\llm_translator.lua")
DATA_DIR = Path(r"E:\APPs\rime-llm")

PASS, FAIL = [], []

def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {detail}")

def main() -> int:
    print("=" * 60)
    print("llm_translator.lua 单元测试")
    print("=" * 60)

    if not LUA_FILE.exists():
        print(f"文件不存在: {LUA_FILE}")
        return 1

    src = LUA_FILE.read_text(encoding="utf-8")

    # ── 1. 语法检查 ──────────────────────────────
    print("\n[1] 语法检查")
    L = LuaRuntime(unpack_returned_tuples=True)
    try:
        L.execute(src)
        check("编译通过", True)
    except Exception as e:
        check("编译通过", False, str(e))
        return 1

    # ── 2. 重新加载并 mock 环境 ───────────────────
    print("\n[2] 逻辑测试（mock rime 全局）")
    L2 = LuaRuntime(unpack_returned_tuples=True)
    # mock rime_api：让 data_dir() 走确定路径
    L2.execute(f'''
        rime_api = {{
            get_user_data_dir = function() return [[E:/APPs/rime-llm]] end
        }}
    ''')

    yielded = []
    def py_yield(cand):
        # cand 是 lua table
        yielded.append({
            "type": cand["type"],
            "start": cand["start"],
            "end": cand["_end"],
            "text": cand["text"],
            "comment": cand["comment"],
        })

    L2.globals().yield_ = py_yield

    # Candidate 构造器：把参数塞进 table
    L2.execute('''
        function Candidate(ctype, start, endpos, text, comment)
            return { type = ctype, start = start, _end = endpos,
                     text = text, comment = comment }
        end
    ''')
    # lua 里的 yield 是关键字，得用 _G["yield"] 覆盖不了；
    # 但 translator 里调用的是普通函数名 yield，实际在 rime 中是注入的全局。
    # 在 Lua 5.x 里 yield 是保留字，不能当全局变量用。
    # 所以这里改写源码里的 yield( → _yield( 来测试。
    patched = src.replace("yield(", "_yield(")
    L2.execute("function _yield(c) yield_(c) end")
    # 但函数体内 _yield 需可见；重新执行打过补丁的源码
    L2.execute(patched)

    M = L2.globals().M if L2.globals().M is not None else None
    # 模块 return M，用 eval 拿
    try:
        M = L2.eval("(function() " + patched.split("local M = {}")[0] + " end)()")
    except Exception:
        pass

    # 直接调 loadstring 拿返回值
    try:
        mod = L2.eval(f"load([==[{patched}]==])()")
        check("模块返回 table", mod is not None)
        check("有 func 入口", mod["func"] is not None,
              "librime-lua 要求入口叫 func，不是 translator")
        check("有 init 入口", mod["init"] is not None)
    except Exception as e:
        check("模块加载", False, str(e))
        return 1

    # ── 3. 缓存读取测试 ──────────────────────────
    print("\n[3] 缓存读取")
    ts = int(time.time())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "llm_cache.txt"
    cache.write_text(
        f"我今天\t去公园|去吃饭|回家\t{ts}\n"
        f"这个问题\t很复杂|很重要\t{ts}\n",
        encoding="utf-8",
    )
    check("测试缓存已写入", cache.exists())

    # 调 func，上文 = "我今天"
    env = L2.eval('''{
        engine = {
            context = {
                commit_history = {
                    latest_text = function() return "我今天" end
                }
            }
        }
    }''')
    seg = L2.eval('{ start = 0, _end = 3 }')

    yielded.clear()
    try:
        mod["func"]("", seg, env)
        check("func 调用不报错", True)
    except Exception as e:
        check("func 调用不报错", False, str(e))

    check("命中缓存产出候选", len(yielded) > 0, f"实际 {len(yielded)} 条")
    if yielded:
        texts = [y["text"] for y in yielded]
        print(f"        候选: {texts}")
        check("候选里有「去公园」", "去公园" in texts)
        check("候选不超过 2 条", len(yielded) <= 2, f"实际 {len(yielded)}")
        check("标记是「联」", yielded[0]["comment"] == "联")

    # ── 4. 未命中时写请求 ────────────────────────
    print("\n[4] 未命中 → 写请求队列")
    req = DATA_DIR / "llm_req.txt"
    if req.exists():
        req.unlink()
    env2 = L2.eval('''{
        engine = {
            context = {
                commit_history = {
                    latest_text = function() return "全新的上文内容" end
                }
            }
        }
    }''')
    yielded.clear()
    try:
        mod["func"]("", seg, env2)
        check("func 调用不报错", True)
    except Exception as e:
        check("func 调用不报错", False, str(e))

    check("未命中不出候选", len(yielded) == 0)
    ok = req.exists() and "全新的上文内容" in req.read_text(encoding="utf-8")
    check("写入了请求", ok, "llm_req.txt 里应有上文")

    # ── 5. 边界：上文太短 ────────────────────────
    print("\n[5] 边界情况")
    env3 = L2.eval('''{
        engine = {
            context = {
                commit_history = {
                    latest_text = function() return "我" end
                }
            }
        }
    }''')
    if req.exists():
        req.unlink()
    yielded.clear()
    mod["func"]("", seg, env3)
    check("上文太短不产出也不请求", len(yielded) == 0 and not req.exists())

    # ── 汇总 ────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print("全部通过 ✅")
    return 0

if __name__ == "__main__":
    sys.exit(main())
