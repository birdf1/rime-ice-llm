"""
test_clip_lua.py —— 剪切板 Lua 模块单测（用 lupa 真解释器）

不需要部署、不需要打字，直接验证：
  1. 三个 lua 文件的语法
  2. clip_common 的转义/预览/截断
  3. clip_translator 对 "v" 和 "vv"/"v1" 的行为
  4. clip_processor 只对 "v"+数字 生效

两个 lupa 注意点：
  - lua 里 yield 是保留字，加载时要把 yield( 换成 _yield(
  - 不要用 unpack_returned_tuples，否则 lua table 会被拆成 tuple
"""

import os
import sys
from pathlib import Path

import lupa

RIME = Path(os.environ.get("RIME_USER_DIR", r"E:\APPs\小狼毫"))
LUA_DIR = RIME / "lua"

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def s(x):
    """lua 字符串在 lupa 里可能是 bytes"""
    return x.decode("utf-8") if isinstance(x, bytes) else x


def make_lua():
    rt = lupa.LuaRuntime()
    for name in ("clip_common", "clip_translator", "clip_processor"):
        src = (LUA_DIR / f"{name}.lua").read_text(encoding="utf-8").replace("yield(", "_yield(")
        rt.execute(f'package.preload["{name}"] = function()\n{src}\nend')

    rt.execute('''
        function _len(t) if not t then return 0 end return #t end

        _CAND = {}
        function Candidate(ctype, start, endpos, text, comment)
            local c = { type = ctype, start = start, ["end"] = endpos,
                        text = text, comment = comment }
            table.insert(_CAND, c)
            return c
        end

        _YIELD = {}
        function _yield(c) table.insert(_YIELD, c) end

        function _ytext(i) return _YIELD[i].text end
        function _ysize() return #_YIELD end
        function _reset() _YIELD = {} end
    ''')
    return rt


def main():
    print("=== 1. Lua 语法 ===")
    try:
        rt = make_lua()
        check("三个文件语法正确", True)
    except Exception as e:
        check("三个文件语法正确", False, str(e))
        return 1

    g = rt.globals()

    print("\n=== 2. clip_common 工具函数 ===")
    rt.execute('COMMON = require("clip_common")')
    common = g.COMMON
    cache = Path(s(common.CACHE))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        "1\t21:05\t变频器参数设置：P0.01=50Hz\\n联系我 13800138000\n"
        "2\t21:04\t短内容\n"
        "3\t21:03\t" + "很长的内容" * 20 + "\n",
        encoding="utf-8",
    )

    items = common.load(6)
    n_items = g._len(items)
    check(f"load 返回 3 条（实际 {n_items}）", n_items == 3)

    first_text = s(items[1]["text"])
    check("反转义把 \\n 还原成真换行", "\n" in first_text, repr(first_text)[:60])
    check("时间字段正确", s(items[1]["time"]) == "21:05", s(items[1]["time"]))

    pv = s(common.preview(items[1]["text"], 44))
    check("preview 压成单行", "\n" not in pv, repr(pv)[:60])
    check(f"preview 不超长（{g.COMMON.utf8_len(pv)} 字）", g.COMMON.utf8_len(pv) <= 45)

    long_pv = s(common.preview(items[3]["text"], 20))
    check("超长文本被截断并加省略号", long_pv.endswith("…"), repr(long_pv)[:60])
    check("截断没切坏 UTF-8", long_pv.encode("utf-8").decode("utf-8") == long_pv)

    print("\n=== 3. clip_translator ===")
    rt.execute('TR = require("clip_translator")')
    tr = g.TR
    tr.init(rt.table())

    def run_translator(inp):
        rt.execute("_reset()")
        seg = rt.eval(f'{{ start = 0, _end = {len(inp)} }}')
        tr.func(inp, seg, rt.table())
        return g._ysize()

    n = run_translator("v")
    check(f"输入 v 产生候选（{n} 个）", n == 3, f"实际 {n}")

    for other in ("vv", "v1", "nv", "hao", ""):
        n = run_translator(other)
        check(f"输入 {other!r} 不产生候选", n == 0, f"实际 {n}")

    rt.execute("_reset()")
    tr.func("v", rt.eval('{ start = 0, _end = 1 }'), rt.table())
    texts = [s(g._ytext(i)) for i in range(1, g._ysize() + 1)]
    check(f"候选文本互不相同（{len(texts)} 个）", len(texts) == len(set(texts)))

    print("\n=== 4. clip_processor ===")
    rt.execute('PR = require("clip_processor")')
    pr = g.PR
    pr.init(rt.table())

    class FakeKey:
        def __init__(self, repr_, ctrl=False, alt=False, sup=False, rel=False):
            self._r, self._c, self._a, self._s, self._rel = repr_, ctrl, alt, sup, rel

        def repr(self): return self._r

        def release(self): return self._rel

        def ctrl(self): return self._c

        def alt(self): return self._a

        def super(self): return self._s

    class FakeCtx:
        def __init__(self, inp):
            self.input = inp
            self.cleared = False

        def clear(self): self.cleared = True

    class FakeEngine:
        def __init__(self):
            self.context = FakeCtx("")
            self.committed = None

        def commit_text(self, t): self.committed = t

    def run_proc(inp, key):
        ctx = FakeCtx(inp)
        eng = FakeEngine()
        eng.context = ctx
        env = rt.table()
        env.engine = eng
        ret = pr.func(key, env)
        return ret, eng.committed, ctx.cleared

    ret, committed, cleared = run_proc("v", FakeKey("1"))
    check("v + 1 → 接受（返回 1）", ret == 1, f"返回值 {ret}")
    c = s(committed)
    check("上屏的是全文（含换行）", c is not None and "\n" in c, repr(c)[:50])
    check("composition 已清空", cleared)

    ret, committed, _ = run_proc("v1", FakeKey("1"))
    check("input='v1' 时不接管", ret == 2 and committed is None, f"返回值 {ret}")

    ret, _, _ = run_proc("v", FakeKey("1", ctrl=True))
    check("Ctrl+1 不接管", ret == 2, f"返回值 {ret}")

    ret, _, _ = run_proc("v", FakeKey("1", rel=True))
    check("按键抬起不接管", ret == 2, f"返回值 {ret}")

    ret, _, _ = run_proc("v", FakeKey("9"))
    check("v + 9（无第 9 条）不接管", ret == 2, f"返回值 {ret}")

    ret, _, _ = run_proc("v", FakeKey("a"))
    check("v + 字母不接管（留给 symbols）", ret == 2, f"返回值 {ret}")

    print(f"\n通过 {PASS} / {PASS + FAIL}")
    if FAIL == 0:
        print("全部通过 ✅")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
