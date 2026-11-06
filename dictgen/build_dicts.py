# -*- coding: utf-8 -*-
"""
生成小狼毫专业词库 mech.dict.yaml
- 只收「现有 1.9M 词条里没有」的词（不重复塞垃圾）
- 已经存在但权重很低的专业词，用高权重再写一遍，抢排序
- 英文缩写单独给 code（小写，去空格）
"""
import io, os, sys, glob, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wordlists import all_words

RIME = os.environ.get("RIME_USER_DIR", r"E:\APPs\小狼毫")
OUT  = os.path.join(RIME, "mech.dict.yaml")

# 权重：越大越靠前
#
# ⚠️ 核心词的权重不能写死成一个固定值。
#    mech 在 rime_ice.dict.yaml 的 import_tables 里排第 2，位置在 base/ext/tencent 之前，
#    「有重复词条时最上面的权重生效」—— 所以写死 60000 会把原本权重更高的词**降级**。
#    实测被降级的 18 个（base 里的权重）：
#        配合 500,461   传感器 307,125   不锈钢 291,240   保养 283,280
#        轴承 208,670   焊接 172,570     关节 157,895     铝合金 136,620
#        单片机 126,145 变频器 98,595    润滑 98,065      基准 97,020
#    正解：核心词权重取 max(现有权重, W_CORE)，只升不降。
W_CORE  = 60000     # 核心专业词的**保底**权重（低于它才提升）
W_LONG  = 20000     # 长尾专业词
W_DAILY = 30000     # 日常高频词（比长尾专业词高，日常打得多）
W_TOOLS = 25000     # 工程软件
W_STD   = 15000     # 标准规范
W_ABBR  = 80000     # 英文缩写


def load_existing() -> tuple[set[str], dict[str, int]]:
    """
    返回 (已有的词集合, 已有的最高权重表)。

    权重表是给「只升不降」用的：写 mech 之前先看这个词在别的词库里有多重，
    比它低就不动，比它高才用我们的。
    """
    seen: set[str] = set()
    weights: dict[str, int] = {}
    for path in glob.glob(os.path.join(RIME, "cn_dicts", "*.dict.yaml")) + \
                glob.glob(os.path.join(RIME, "en_dicts", "*.dict.yaml")):
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2 or not parts[0].strip():
                    continue
                w = parts[0].strip()
                seen.add(w)
                if len(parts) >= 3 and parts[2].strip().isdigit():
                    n = int(parts[2])
                    if w not in weights or n > weights[w]:
                        weights[w] = n
    return seen, weights

# 多音字人工纠正（pypinyin 按常用读音给，专业词里读法不同）
PINYIN_FIX = {
    # 伺 = sì（伺服），不是 cì
    "伺服":        "si fu",
    "伺服电机":    "si fu dian ji",
    "伺服驱动器":  "si fu qu dong qi",
    "伺服系统":    "si fu xi tong",
    "伺服调试":    "si fu tiao shi",
    "伺服报警":    "si fu bao jing",
    "伺服增益":    "si fu zeng yi",
    "伺服阀":      "si fu fa",
    "伺服与调试":  "si fu yu tiao shi",
    # 调 = tiáo（调节/调整/调试），不是 diào
    "调质":        "tiao zhi",
    "调速阀":      "tiao su fa",
    "调速":        "tiao su",
    "调节":        "tiao jie",
    # 重 = chóng（重绕/重复），不是 zhòng
    "重绕":        "chong rao",
    "电机绕组重绕": "dian ji rao zu chong rao",
    # 校 = jiào（校核）
    "校核":        "jiao he",
    "强度校核":    "qiang du jiao he",
    "刚度校核":    "gang du jiao he",
    # 差 = chā（公差）
    "公差配合":    "gong cha pei he",
    "形位公差":    "xing wei gong cha",
    "形位公差标注": "xing wei gong cha biao zhu",
    # 其它
    "载波频率":    "zai bo pin lv",
    "剖视图":      "pou shi tu",
    "剖视图绘制":  "pou shi tu hui zhi",
    "倒闸操作":    "dao zha cao zuo",
    "夹爪":        "jia zhua",
    "看门狗":      "kan men gou",
    "量具":        "liang ju",
    "惯量匹配":    "guan liang pi pei",
    "惯量比":      "guan liang bi",
}

def py_code(word: str) -> str:
    """中文按字转拼音；ASCII 段（PLC / RS485）原样保留为小写。"""
    if word in PINYIN_FIX:
        return PINYIN_FIX[word]
    if re.fullmatch(r"[A-Za-z0-9+#\.\- ]+", word):
        # 纯英文术语：去掉空格和连字符，整体当一个编码（GX Works → gxworks）
        return re.sub(r"[^A-Za-z0-9+#]", "", word).lower()
    from pypinyin import lazy_pinyin
    out = []
    for m in re.finditer(r"[A-Za-z0-9+#\.]+|[\u4e00-\u9fff]+", word):
        tok = m.group(0)
        if re.fullmatch(r"[A-Za-z0-9+#\.]+", tok):
            out.append(tok.lower())
        else:
            out.extend(p.lower() for p in lazy_pinyin(tok))
    code = " ".join(x for x in out if x)
    # 通用纠正：pypinyin 把「伺」读成 ci，专业词里一律是 sì
    # （「伺服刀塔」「伺服刚度」这类新词不用一个个往 PINYIN_FIX 里加）
    if word.startswith("伺服"):
        code = re.sub(r"^ci\b", "si", code)
    return code

def main():
    existing, existing_w = load_existing()
    groups = all_words()
    rows = []
    boosted = []      # 记录被提升的词（现有权重 < 我们的）
    kept = []         # 记录保持原权重的词（现有权重 >= 我们的）

    def add(word, weight, code=None):
        code = code or py_code(word)
        if not code:
            return
        if " " not in code and not re.fullmatch(r"[a-z0-9+#]+", code):
            return
        rows.append((word, code, weight))

    # 1) 核心专业词：只升不降
    #    现有词库里权重更高的话保持原样，否则用 W_CORE 提上来。
    #    写死权重会把「配合 500,461」「传感器 307,125」这类词降级，反而更难打。
    for w in groups["core"]:
        old = existing_w.get(w, 0)
        if old >= W_CORE:
            add(w, old)
            kept.append((w, old))
        else:
            add(w, W_CORE)
            if old:
                boosted.append((w, old, W_CORE))

    # 2) 长尾专业词：只补缺失的
    for w in groups["long"]:
        if w not in existing:
            add(w, W_LONG)

    # 3) 日常高频词：只补缺失的（已有词库里的不动，避免污染基础词频）
    for w in groups.get("daily", []):
        if w not in existing:
            add(w, W_DAILY)

    # 4) 工程软件
    for w in groups.get("tools", []):
        if w not in existing:
            add(w, W_TOOLS)

    # 5) 标准规范
    for w in groups.get("std", []):
        if w not in existing:
            add(w, W_STD)

    # 6) 英文缩写
    for w in groups["abbr"]:
        add(w, W_ABBR)

    # 7) 带空格/连字符的英文术语（显式编码）
    for w, c in groups.get("pairs", []):
        add(w, W_ABBR, code=c)

    # 去重（同词同码只留最高权重）
    best = {}
    for w, c, wt in rows:
        key = (w, c)
        if key not in best or best[key] < wt:
            best[key] = wt

    head = f"""# Rime dictionary
# encoding: utf-8
#
# 专业词库：机电一体化 / 电气自动化 / 工业机器人 / PLC / 单片机
# 生成：dictgen/build_dicts.py（{len(best)} 条）
# 说明：核心专业词用高权重重写，保证打「bianpinqi」时「变频器」排在前面
---
name: mech
version: "2026-11-06"
sort: by_weight
...
"""
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(head)
        for (w, c), wt in sorted(best.items(), key=lambda kv: -kv[1]):
            f.write(f"{w}\t{c}\t{wt}\n")

    print(f"写出 {OUT}")
    print(f"词条数：{len(best)}")
    for label, key in (("核心", "core"), ("长尾", "long"), ("日常", "daily"),
                       ("软件", "tools"), ("标准", "std"), ("缩写", "abbr")):
        n = len([w for w in groups.get(key, []) if (w, py_code(w)) in best])
        print(f"  {label}: {n}")

    print()
    print(f"权重处理：提升 {len(boosted)} 个，保持原样 {len(kept)} 个")
    if boosted[:5]:
        print("  提升示例（原权重 → 新权重）:")
        for w, o, n in boosted[:5]:
            print(f"    {w:<12} {o:>8,} → {n:>8,}")
    if kept[:5]:
        print("  保持原样的高权重词:")
        for w, n in sorted(kept, key=lambda kv: -kv[1])[:5]:
            print(f"    {w:<12} {n:>8,}（本来就比保底值高，不动）")

if __name__ == "__main__":
    main()
