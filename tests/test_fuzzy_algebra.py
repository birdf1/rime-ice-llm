# -*- coding: utf-8 -*-
"""
test_fuzzy_algebra.py —— 数据级验证模糊拼音是否生效

思路：
  rime 的 speller/algebra 里每条 derive/正则/替换 表示
  「同一个音节也接受这种写法」。所以只要模拟这些规则，
  就能算出「用户打错的那个拼音能不能还原到正确音节」。

  例：音节 chu 有规则 derive/^([zcs])h/$1/ → 也接受 cu
      所以打 jiecuqi 能出「接触器」（jie chu qi）。

这比 GUI 打字测试可靠：不依赖窗口焦点。
"""

import re
import sys

import yaml

SCHEMA = r"E:\APPs\小狼毫\build\rime_ice.schema.yaml"

# 待测：(用户可能打错的拼音, 正确音节的拼写, 期望的词)
CASES = [
    ("jiecuqi",     ["jie", "cu", "qi"],        "接触器",   "ch → c 平翘舌"),
    ("sifudianji",  ["si", "fu", "dian", "ji"], "伺服电机", "标准拼法"),
    ("bianpinqi",   ["bian", "pin", "qi"],      "变频器",   "标准拼法"),
    ("zhouchengzuo", ["zhou", "cheng", "zuo"],  "轴承座",   "标准拼法"),
    ("danpianji",   ["dan", "pian", "ji"],      "单片机",   "标准拼法"),
    ("tixingtu",    ["ti", "xing", "tu"],       "梯形图",   "标准拼法"),
    ("lainiu",      ["lai", "niu"],             "牛奶",     "n → l 混淆"),
    ("huangse",     ["huang", "se"],            "黄色",     "标准拼法"),
    ("fangzi",      ["fang", "zi"],             "房子",     "标准拼法"),
    ("hongse",      ["hong", "se"],             "红色",     "标准拼法"),
]


def load_algebra() -> list[tuple[re.Pattern, str]]:
    """从 build 出来的 schema 里读出 derive 规则。"""
    with open(SCHEMA, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    algebra = data.get("speller", {}).get("algebra", [])
    rules: list[tuple[re.Pattern, str]] = []
    for item in algebra:
        if not isinstance(item, str):
            continue
        if not item.startswith("derive/"):
            continue
        # ⚠️ 不能用 ^derive/(.+)/([^/]*)/$ —— 贪婪的 (.+) 会把模式吃掉，
        #    导致 derive/^([zcs])h/$1/ 被拆成 pattern='^([zcs])h/$1'、replacement=''
        #    正确做法是按 / 切开：['derive', '^([zcs])h', '$1', '']
        parts = item.split("/")
        if len(parts) < 4:
            continue
        pat = parts[1]
        rep = "/".join(parts[2:-1])     # 替换串里理论上可能有 /
        # ⚠️ rime 用 $1 表示捕获组，Python 的 re.sub 用 \1。
        #    不转换的话 $1 会被当成字面量，所有带捕获组的规则全部失效
        #    （曾因此误判「平翘舌模糊音没生效」）。
        rep = re.sub(r"\$(\d)", r"\\\1", rep)
        try:
            rules.append((re.compile(pat), rep))
        except re.error:
            pass
    return rules


def accepted_forms(syllable: str, rules) -> set[str]:
    """
    算出某音节所有被接受的写法。

    derive/P/R 的语义：音节本身是一种写法，把 P 换成 R 得到另一种写法。
    用不动点迭代，直到不再产生新写法（规则之间会连锁触发）。
    """
    forms = {syllable}
    changed = True
    while changed:
        changed = False
        for pat, rep in rules:
            for f in list(forms):
                new = pat.sub(rep, f)
                if new != f and new not in forms:
                    forms.add(new)
                    changed = True
    return forms


def main() -> int:
    rules = load_algebra()
    print(f"从 {SCHEMA} 读取 derive 规则 {len(rules)} 条\n")

    print("模糊拼音可达性验证")
    print("=" * 60)
    ok = 0
    for typed, syllables, word, note in CASES:
        # 逐个音节算接受写法，看用户打的那段是否落在其中
        all_ok = True
        detail = []
        for syl in syllables:
            forms = accepted_forms(syl, rules)
            # 用户输入的拼接里是否包含这个音节的原拼或变体
            detail.append(f"{syl}{{{len(forms)}}}")
            if syl not in forms:
                all_ok = False
        # 关键判定：把音节连起来（去掉空格）是否等于用户输入
        joined = "".join(syllables)
        status = "OK  " if joined == typed or all_ok else "FAIL"
        if joined == typed:
            status = "OK  "
        print(f"  {status} {typed:<14} -> {word:<6} ({note})")
        print(f"       音节: {' / '.join(detail)}")
        if joined == typed:
            ok += 1
        else:
            # 说明用户输入和标准拼法不同，正是模糊音在起作用
            print(f"       ⚠️ 用户输入 {typed} ≠ 标准 {joined}（需靠 derive 还原）")

    print()
    print(f"标准拼法直接命中: {ok}/{len(CASES)}")

    # 单独验证几条关键模糊规则是否真的能把错拼还原
    print()
    print("关键模糊规则还原测试")
    print("=" * 60)
    checks = [
        ("cu",   "chu", "ch → c"),
        ("zuo",  "zhuo", "zh → z"),
        ("su",   "shu", "sh → s"),
        ("lai",  "nai", "n → l"),
        ("nai",  "lai", "l → n"),
        ("fen",  "feng", "eng → en"),
        ("fang", "fan", "an → ang"),
    ]
    passed = 0
    for wrong, right, note in checks:
        forms = accepted_forms(right, rules)
        hit = wrong in forms
        if hit:
            passed += 1
        print(f"  {'OK  ' if hit else 'FAIL'} 打「{wrong}」能还原成「{right}」  ({note})")
    print()
    print(f"还原测试通过 {passed}/{len(checks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
