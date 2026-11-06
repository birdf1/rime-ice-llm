import os
import sys

sys.path.insert(0, os.environ.get("RIME_USER_DIR", r"E:\APPs\小狼毫"))
sys.stdout.reconfigure(encoding="utf-8")

import importlib.util

spec = importlib.util.spec_from_file_location("d", r"E:\APPs\小狼毫\llm_daemon.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
d.load_wordlist()

PRO = ["变频器", "伺服电机", "可编程控制器", "工业机器人", "单片机", "继电器",
       "液压缸", "梯形图", "示教器", "编码器", "光电开关", "接触器",
       "断路器", "伺服刀塔", "轴承座", "滚珠丝杠", "减速机", "伺服刚度"]
DAILY = ["外卖", "快递", "加班", "开会", "报销", "火锅", "奶茶"]
BAD = ["进一", "吃一", "今天的工", "将用户输", "与自动化", "安全与运维"]

print("专业词（必须全部通过）")
print("-" * 34)
fails = 0
for t in PRO:
    ok = d.is_word(t)
    if not ok:
        fails += 1
    print(f"  {t:<12} {'✅' if ok else '❌ 被过滤'}")

print("\n日常词")
print("-" * 34)
for t in DAILY:
    print(f"  {t:<12} {'✅' if d.is_word(t) else '⚠️ 不在词表'}")

print("\n碎片（必须全部被拦）")
print("-" * 34)
for t in BAD:
    ok = d.is_word(t)
    print(f"  {t:<12} {'❌ 漏了' if ok else '✅ 已拦'}")

print(f"\n专业词通过 {len(PRO) - fails}/{len(PRO)}")
