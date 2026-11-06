#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_wordlist.py —— 从 rime 词库构建「合法词表」，用来过滤模型的半截词

背景：
  0.5B 模型续写的是整个从句（「从多个角度进行分析」），按字数硬切必然出现
  「从多个角」「今天的工」这种不在词典里的碎片。靠虚词规则只能挡掉一部分。

  解决办法：用 rime 自己那 189 万条词库做校验，切出来的候选不在词表里就丢掉。
  这样「进一」「今天的工」「将用户输」都会被拦下，而「准时」「公园散步」会留下。

资源占用：
  用 crc32 哈希 + 排序数组，不存字符串。
  2 字 139k + 3 字 458k + 4 字 809k ≈ 1.4M 个 4 字节整数 = 5.6 MB 文件，
  运行时用 array('I') 加载，内存约 5.6 MB。

跑法：C:\\Python313\\python.exe build_wordlist.py
输出：E:\\APPs\\rime-llm\\wordlist.bin
"""

import glob
import os
import struct
import sys
import zlib

DICT_DIR = os.environ.get("RIME_DICT_DIR", r"E:\APPs\小狼毫\cn_dicts")
RIME_DIR = os.environ.get("RIME_USER_DIR", r"E:\APPs\小狼毫")
OUT_FILE = os.path.join(os.environ.get("RIME_LLM_DIR", r"E:\APPs\rime-llm"), "wordlist.bin")
LENGTHS = (2, 3, 4)


def dict_files() -> list[str]:
    """
    要扫描的词库文件。

    ⚠️ 别只扫 cn_dicts/ —— 专业词库 mech.dict.yaml 放在根目录，
       漏掉它的话「变频器」「伺服电机」这些词会被 AI 联想当成非法词过滤掉。
    """
    files = sorted(glob.glob(os.path.join(DICT_DIR, "*.dict.yaml")))
    for extra in ("mech.dict.yaml",):
        p = os.path.join(RIME_DIR, extra)
        if os.path.exists(p):
            files.append(p)
    return files


def main() -> int:
    files = dict_files()
    if not files:
        print(f"没找到词库文件: {DICT_DIR}")
        return 1

    buckets: dict[int, set[int]] = {n: set() for n in LENGTHS}
    raw_counts: dict[int, int] = {n: 0 for n in LENGTHS}

    for path in files:
        name = os.path.basename(path)
        n_ok = 0
        in_body = False
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not in_body:
                    if line.strip() == "...":
                        in_body = True
                    continue
                if not line or line.startswith("#"):
                    continue
                word = line.split("\t", 1)[0].strip()
                if not word:
                    continue
                # 只要纯汉字、且长度是我们关心的
                if len(word) not in LENGTHS:
                    continue
                if not all("\u4e00" <= ch <= "\u9fff" for ch in word):
                    continue
                # crc32 哈希，4 字节整数
                buckets[len(word)].add(zlib.crc32(word.encode("utf-8")) & 0xFFFFFFFF)
                raw_counts[len(word)] += 1
                n_ok += 1
        print(f"  {name:<24} {n_ok:>8,} 条")

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "wb") as fh:
        # 头部：每个长度的数量
        fh.write(struct.pack("<3I", *(len(buckets[n]) for n in LENGTHS)))
        for n in LENGTHS:
            arr = sorted(buckets[n])
            fh.write(struct.pack(f"<{len(arr)}I", *arr))

    size = os.path.getsize(OUT_FILE)
    print()
    for n in LENGTHS:
        print(f"  {n} 字词: 原始 {raw_counts[n]:>9,} 条 → 去重后 {len(buckets[n]):>9,} 条"
              f"  ({len(buckets[n]) * 4 / 1024 / 1024:.2f} MB)")
    print(f"\n写入 {OUT_FILE}")
    print(f"文件大小 {size:,} 字节 ({size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
