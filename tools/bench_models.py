#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bench_models.py —— 输入法联写任务的模型横评

测的是**真实任务**：已输入文字 → 预测下一个词。
不是测拼音转汉字（那个小模型必败，已废弃）。

指标：
  质量 —— 人工可判（输出是否会话式废话、词是否通顺）
  速度 —— 首次（含加载）+ 热身后
  显存 —— nvidia-smi 实测

跑法：C:\\Python313\\python.exe bench_models.py
"""

import json
import re
import subprocess
import sys
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"

SYSTEM_PROMPT = """你是中文输入法联想引擎。给一段话，预测接下来最可能出现的 3 个词。
严格按格式输出，每行一个词，共 3 行，不要编号、不要解释、不要标点。

示例输入：今天天气真好，我想去
示例输出：
公园
散步
郊游"""

CASES = [
    "我刚吃完饭，准备去",
    "这个问题比较复杂，需要",
    "今天天气真不错，我们一起去",
    "会议定在明天下午三点，请大家",
    "这个功能的设计思路是",
    "这界面",
    "大模型",
    "今天下午的会议改到了三点半，我们",
]

MODELS = ["qwen2.5:0.5b", "qwen3:0.6b", "qwen2.5:3b", "qwen2.5:7b"]


def vram() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        used, total = out.split(",")
        return f"{int(used)}/{int(total)} MiB"
    except Exception:
        return "?"


def call(model: str, ctx: str) -> tuple[str, float]:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": ctx},
        ],
        "stream": False,
        # 关键：让模型用完就卸载，别长期占显存
        "keep_alive": "5m",
        "options": {"temperature": 0.6, "num_predict": 60, "top_p": 0.9},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.load(r)
    dt = (time.time() - t0) * 1000
    return body.get("message", {}).get("content", ""), dt


def parse(raw: str) -> list[str]:
    """和 daemon 里同样的清洗逻辑，保证公平对比。"""
    out, seen = [], set()
    for line in raw.splitlines():
        w = re.sub(r"^[\d\.\)、\-\*•\s]+", "", line.strip())
        w = re.sub(r"[^\u4e00-\u9fff]", "", w)
        if 2 <= len(w) <= 8 and w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= 3:
            break
    return out


def main() -> int:
    results: dict[str, dict] = {}

    for model in MODELS:
        print(f"\n{'='*66}")
        print(f"模型：{model}")
        print("=" * 66)

        # 冷启动（含加载）
        try:
            _, cold = call(model, "你好")
        except Exception as e:
            print(f"  跳过：{e}")
            continue
        print(f"  冷启动加载+推理: {cold:,.0f} ms")

        # 热身后逐条测
        rows = []
        times = []
        for ctx in CASES:
            try:
                raw, dt = call(model, ctx)
                words = parse(raw)
                times.append(dt)
                rows.append((ctx, words, dt, raw))
                shown = "/".join(words) if words else "（无有效输出）"
                print(f"  {dt:6,.0f}ms  [{ctx}] -> {shown}")
            except Exception as e:
                print(f"      -  [{ctx}] 失败: {e}")
                rows.append((ctx, [], 0, str(e)))

        ok = sum(1 for r in rows if r[1])
        avg = sum(times) / len(times) if times else 0
        results[model] = {"rows": rows, "ok": ok, "avg": avg,
                          "cold": cold, "vram": vram()}
        print(f"  → 有效输出 {ok}/{len(CASES)}  平均 {avg:,.0f} ms  显存 {vram()}")

    # ── 汇总 ──
    print(f"\n{'='*66}")
    print("汇总")
    print("=" * 66)
    print(f"{'模型':<16}{'有效':<8}{'热平均':<12}{'冷启动':<12}{'显存'}")
    print("-" * 66)
    for m, r in results.items():
        print(f"{m:<16}{r['ok']}/{len(CASES):<6}{r['avg']:>8,.0f} ms  "
              f"{r['cold']:>8,.0f} ms  {r['vram']}")

    # ── 逐条对比（看质量差异）──
    print(f"\n{'='*66}")
    print("逐条对比")
    print("=" * 66)
    for i, ctx in enumerate(CASES):
        print(f"\n[{ctx}]")
        for m, r in results.items():
            words = r["rows"][i][1] if i < len(r["rows"]) else []
            print(f"  {m:<16} {'/'.join(words) if words else '（无）'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
