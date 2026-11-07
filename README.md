# rime-ice-llm

给 [雾凇拼音](https://github.com/iDvel/rime-ice)（小狼毫 / Rime）加一个**本地运行的 AI 联想**：
打完一句，它猜你下一个词。全程离线，**0 显存**，磁盘只多 253 MB。

基于 [MiniCPM4-0.5B](https://huggingface.co/openbmb/MiniCPM4-0.5B-QAT-Int4-GGUF)（面壁智能端侧模型），
纯 CPU 推理，打字时耗 330 MiB 内存，停手 10 分钟自动释放。

```
[会议定在明天下午三点，请大家]  -> 准时 / 准时参加 / 准时出席
[今天天气真不错，我们一起去]    -> 公园 / 公园散步 / 公园游玩
[这个问题比较复杂，需要]        -> 深入 / 深入探讨
[周六上午去趟超市，顺便买点]    -> 水果
```

---

## 这套东西解决什么问题

雾凇拼音本身很好用，但有两个地方能更好：

| 问题 | 做法 |
|---|---|
| **打完一句不会联想下一个词** | 加一个 `lua_translator`，从已提交的上文预测下一个词，候选栏标「联」 |
| **专业术语打不出来**（机电 / 电气 / 机器人 / PLC / 单片机） | 独立词库 `mech.dict.yaml`，520 条，高权重抢排序 |
| **拼音不好老打错** | 10 条模糊音（平翘舌 / 前后鼻音 / n-l / f-h / r-l），已实测 7/7 生效 |
| **开源输入法比商业的卡** | 砍掉 400 MB 语法模型、translators 13→6、filters 8→2、词库精简约一半 |

---

## 实测数据

| 项目 | 数值 |
|---|---|
| 显存占用 | **0**（纯 CPU） |
| 内存占用 | 330 MiB（模型，停手 10 分钟释放）+ 29 MB（daemon） |
| 单次预测 | 热 **135 ms**（中位）/ 冷 627 ms |
| daemon 完整一轮（3 次采样） | 热 476 ms / 冷 856 ms |
| 模型体积 | 253 MB |
| 联想词表 | 5.36 MB（140 万词的合法性校验表） |
| AI 部分磁盘合计 | **约 373 MB**（含 Ollama 引擎 114 MB） |

延迟是**异步**的，打字时完全无感：Lua 侧只写请求文件、读缓存文件，从不等待模型。
冷启动那 490 ms 里你照常打字，只是这一次没有候选，下一次按键就出来了。

---

## 架构

```
  ┌──────────────┐   keystroke    ┌─────────────────────┐
  │   Weasel     │ ─────────────> │ llm_translator.lua  │
  │ (小狼毫前端)  │                │  · 读 llm_cache.txt │
  └──────────────┘                │  · 写 llm_req.txt   │
         ▲                        └─────────────────────┘
         │ 候选(标「联」)                    │ 文件
         └──────────────────────────────────┘
                                            │
                                  ┌─────────▼──────────┐
                                  │   llm_daemon.py    │
                                  │  · 轮询请求队列      │
                                  │  · 调 Ollama        │
                                  │  · 词表校验候选      │
                                  └─────────┬──────────┘
                                            │ HTTP
                                  ┌─────────▼──────────┐
                                  │  Ollama (CPU)      │
                                  │  MiniCPM4-0.5B     │
                                  └────────────────────┘
```

**关键设计：Lua 侧不碰网络。** librime-lua 没有 socket，`os.execute` / `io.popen`
是同步阻塞的，在 translator 里用会直接卡住输入。所以 HTTP 全部放在 Python 守护进程里，
两侧只通过两个文件通信。daemon 卡了 / 挂了 / 没装，最坏结果只是没有联想候选，**打字不受影响**。

---

## 安装

### 前置

- Windows + [小狼毫 Weasel](https://rime.im/download/) 0.17+
- [雾凇拼音 rime-ice](https://github.com/iDvel/rime-ice)（本仓库的配置是从它改的）
- [Python 3.10+](https://www.python.org/downloads/)（守护进程）
- [Ollama](https://ollama.com/download)（推理引擎）

### 步骤

```powershell
# 1. 拉模型（265 MB）
ollama pull hf.co/openbmb/MiniCPM4-0.5B-QAT-Int4-GGUF

# 2. 准备数据目录（⚠️ 必须是纯 ASCII 路径，见下方「已知坑」）
New-Item -ItemType Directory -Force E:\APPs\rime-llm

# 3. 把本仓库的文件放进小狼毫用户目录
#    llm_daemon.py        -> 用户目录根
#    lua/llm_translator.lua -> 用户目录\lua\
#    mech.dict.yaml       -> 用户目录根
#    rime_ice.custom.yaml -> 覆盖（或合并 patch 段）
#    rime_ice.dict.yaml   -> 覆盖（或合并 import_tables）

# 4. 构建词表
python build_wordlist.py

# 5. 部署
& 'C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe' /deploy

# 6. 启动守护进程
python llm_daemon.py
```

### 路径配置

所有路径都可以用环境变量覆盖，默认值是作者的（`E:\APPs\小狼毫` / `E:\APPs\rime-llm`）：

| 变量 | 作用 | 默认 |
|---|---|---|
| `RIME_USER_DIR` | 小狼毫用户目录 | `E:\APPs\小狼毫` |
| `RIME_LLM_DIR` | 数据目录（**必须纯 ASCII**） | `E:\APPs\rime-llm` |
| `RIME_DICT_DIR` | 词库目录 | `<RIME_USER_DIR>\cn_dicts` |
| `RIME_LLM_MODEL` | Ollama 模型名 | `hf.co/openbmb/MiniCPM4-0.5B-QAT-Int4-GGUF` |
| `RIME_LLM_NUM_GPU` | 用不用显卡（`0`=纯CPU） | `0` |

### 开机自启

把 `tools/setup-llm.ps1` 里的启动项装到启动文件夹（**必须用 UTF-16 编码的 VBS**，
`.bat` 写成 ASCII/GBK 会把中文路径搞坏）：

```vbs
Set ws = CreateObject("WScript.Shell")
ws.Run """C:\Python313\python.exe"" ""<用户目录>\llm_daemon.py""", 0, False
```

---

## 关键设计决策

### 为什么用 Base 模型 + `raw: true`

这是整个项目最重要的一条。一开始用 Instruct 对话模型，它回的是：

```
好的，接下来最可能出现的 3 个词是：准时、参加、出席
```

改成 **Base 模型 + 不加对话模板**（`raw: true`），同样的输入：

```
准时参加
```

Base 模型是纯下一个词预测器，天生干这个事。
[scukeqi/Wisdom-Weasel](https://github.com/scukeqi/Wisdom-Weasel) 的文档也明确写「推荐使用 Base 模型」。

```python
payload = {
    "model": MODEL, "prompt": context,
    "raw": True,          # 关键：不加 chat 模板
    "stream": False,
    "keep_alive": KEEP_ALIVE,
    "options": {
        "num_predict": 12, "top_p": 0.92,
        "num_gpu": NUM_GPU, "seed": seed,
        "stop": ["\n"],   # 关键：不要放标点，见下方
    },
}
# 用 /api/generate，不是 /api/chat
```

### 为什么要采样 3 次

0.5B 模型单次输出不稳定。采 3 次（不同 seed / temperature）能覆盖更多合理答案，
而且它只要约 50 ms，采 3 次也才 150 ms，完全在异步可接受范围内。

### 候选的三道过滤

模型续写的是**整个从句**（`从多个角度进行分析`），按字数硬切必然出现 `从多个角` 这种碎片。

1. **虚词开头过滤** —— 候选不可能以介词开头
   ```python
   _NO_START = set("从对把被在和与的地得着了着过再又还也都就才而且或但 是之以于为给让使向往由经除连跟同按据")
   ```
2. **结尾助词剪除** —— `进一步的` → `进一步`
   ```python
   _TRIM_TAIL = set("的了着过地得们呢吧啊")
   ```
3. **词表校验**（最有效）—— 用 rime 自己的 189 万词库建 crc32 哈希表，
   切出来的候选不在词表里就丢掉。5.36 MB，运行时占 5.6 MB 内存。
   ```python
   def is_word(w: str) -> bool:
       arr = _WORDS.get(len(w))
       if arr is None or len(arr) == 0: return True   # fail-open
       h = zlib.crc32(w.encode("utf-8")) & 0xFFFFFFFF
       i = bisect.bisect_left(arr, h)
       return i < len(arr) and arr[i] == h
   ```

效果：`进一` / `吃一` / `今天的工` / `将用户输` 全被拦下。12 条实测 9 好 3 一般。

---

## 按 v 调出剪切板

打出 `v`，候选栏列出最近的剪切板内容（最多 6 条），按数字键直接上屏全文。
微信输入法的那个功能，用三个 Lua 文件 + 一个 Python 线程实现，不装任何额外软件。

```
打 v  →  1. 会议纪要： 1. 确认伺服电机型号 2. 下周提交方案   [21:01 · 27字]
         2. 变频器参数 P0.01 设为 50Hz                      [21:01 · 19字]
         3. https://github.com/birdf1/rime-ice-llm           [21:00 · 38字]
按 1  →  上屏完整的三行会议纪要（不是预览那一行）
```

### 为什么显示预览、上屏全文要分两处做

rime 候选的 `text` 字段**同时**是「屏幕显示」和「上屏内容」，没法只显示预览而上屏全文。
把全文塞进 `text` 会让候选栏拉成一条长带（一段会议纪要横跨整个屏幕）。

所以拆开：

- `clip_translator.lua` 只放 **单行预览**（截断到 44 字，换行压成空格）
- `clip_processor.lua` 排在 processors **最前面**，拦截 `v` + 数字键，
  直接调 `env.engine:commit_text()` 上屏**完整原文**

processor 必须排第一，是因为排在 `speller` 后面的话，按下的 `1` 会先被吃进
composition，`ctx.input` 变成 `"v1"` 就不再等于 `"v"` 了。

### 零宽空格是干嘛的

候选文本尾部补了 N 个 U+200B（第 N 条补 N 个）。

`uniquifier` 过滤器按 `text` 去重 —— 两条不同内容如果截断后的预览长得一样，会被吞掉一条，
导致**菜单序号和 processor 的索引错位**（用户按 2 却上屏第 3 条）。
零宽空格不显示，就算真被上屏也无害。

### 和 symbols 的取舍

rime-ice 的 `v` 本来是符号入口（`vfh` 符号、`vdn` 键盘、`vsz` 数学……）。

| 输入 | 现在的结果 |
|---|---|
| `v` | 剪切板历史 |
| `v` + **字母**（`vfh`、`vsz`） | **符号照常可用** |
| `v` + **数字** | 被剪切板占用（原本是数字变体 ① ② ③） |

只有 `v` + 数字 让位了。如果哪天要用回数字变体：

```powershell
# 建个空文件即可临时关闭剪切板
New-Item -ItemType File "$env:RIME_LLM_DIR\clip_off"
# 删除即恢复
Remove-Item "$env:RIME_LLM_DIR\clip_off"
```

### 监控开销

`clip_watcher.py` 用 ctypes 直调 Win32，**不用装 pywin32**：

```
每 0.4 秒 → GetClipboardSequenceNumber()   只读一个计数器，不加锁、不开剪切板
           ↓ 序号变了才
           OpenClipboard + GetClipboardData 读内容
```

所以空闲时几乎零开销，也不会跟别的程序抢剪切板。作为后台线程挂在 `llm_daemon.py` 里，
**不额外起 Python 进程**。

支持文本和文件列表（复制文件时给出路径），自动去重、最多留 40 条、单条上限 4000 字。

### 相关文件

| 文件 | 作用 |
|---|---|
| `clip_watcher.py` | 剪切板监控线程（ctypes，无依赖） |
| `lua/clip_common.lua` | 读缓存 / 反转义 / 生成预览 |
| `lua/clip_translator.lua` | `v` → 候选列表 |
| `lua/clip_processor.lua` | `v`+数字 → 上屏全文 |
| `tests/test_clip_lua.py` | lupa 单测 23/23 |

配置改动（`rime_ice.custom.yaml`）：

```yaml
  engine/processors:
    - lua_processor@*clip_processor        # 必须在最前
    - lua_processor@*select_character
    - ascii_composer
    # ... 其余保持原样

  engine/translators:
    - lua_translator@*clip_translator      # 剪切板
    - lua_translator@*llm_translator
    # ... 其余保持原样
```

---

## 已知坑（都踩过）

### 1. Lua 打不开中文路径 ⚠️ 最容易中招

```lua
-- 报错：Illegal byte sequence，而且 io.open 静默返回 nil
local f = io.open("E:/APPs/小狼毫/data/llm_cache.txt", "r")
```

Lua 的 `io.open` 在 Windows 上走 ANSI(GBK) 的 `fopen`，遇到中文目录直接失败，
**不抛异常、不打印，就是返回 nil**。这个坑让整条链路静默失效过一小时。

→ 数据目录必须是纯 ASCII（如 `E:\APPs\rime-llm`）。
`E:\APPs\小狼毫` 没有 8.3 短路径可用。

### 2. translator 的入口函数名必须是 `M.func`

写成 `M.translator` 不会报错，但**永远不被调用**。必须是：

```lua
function M.init(env) end
function M.func(input, seg, env) ... end
```

### 3. 取上文用 `commit_history:latest_text()`

```lua
-- ❌ 返回空
local txt = env.engine.context:get_commit_text()
-- ✅
local txt = env.engine.context.commit_history:latest_text()
```

### 4. `stop` 列表不能放标点

模型对「哦今天天气很好」的续写是「**，**好到可以骑驴去山」——第一个字符就是逗号。
如果把 `，` 写进 `stop`，服务端立刻截断返回空串，这个上文永远拿不到候选。

→ `stop` 只留 `["\n"]`，标点改在本地切：

```python
raw = raw.lstrip("。，、！？：；\n\r\t （）《》\"'“”‘’.,!?:;")
raw = re.split(r"[。，、！？：；\n\r（）《》\"'“”‘’]", raw, maxsplit=1)[0]
```

### 5. 词库权重只能升不能降

往已有词库体系里插词，**权重必须取 `max(原值, 新值)`**。

`mech` 在 `import_tables` 里排在 `base` 前面，rime 规则是「重复词条最上面的权重生效」——
写死一个固定值会把原本更重的词**降级**。实测踩到 18 个：

| 词 | base 里的权重 | 写死 60000 的后果 |
|---|---|---|
| 配合 | 500,461 | 降 88% |
| 传感器 | 307,125 | 降 80% |
| 单片机 | 126,145 | 降 52% |
| 变频器 | 98,595 | 降 39% |

本想让「变频器」排更前，实际把它降了 39%。改成 `max()` 后：提升 172 个、保持 18 个、降级 0 个。

### 6. 词表里不能用 `#` 注释 + `.split()`

```python
CORE = """
# 电机与拖动          ← 这行会被切成词条
变频器 伺服电机 ...
""".split()
```

会生成 `与自动化`、`安全与运维` 这类垃圾词条。要先逐行过滤 `#`（见 `dictgen/wordlists.py` 的 `_parse()`）。

### 7. rime 的 `$1` ≠ Python 的 `\1`

解析 `speller/algebra` 的 derive 规则时：

```python
pat.sub("$1", "chu")            # ❌ 变成字面量 '$1'
pat.sub(r"\1", "chu")           # ✅ 变成 'cu'
rep = re.sub(r"\$(\d)", r"\\\1", rep)   # 先转换
```

不转换的话所有带捕获组的规则静默失效（曾因此误判「模糊音没生效」）。

### 8. 部署时不加载 Lua

librime-lua 是**懒加载**的，部署日志里查不到 Lua 语法错误。
验证办法：在模块顶层写个 marker 文件，看它有没有被创建。

### 9. librime-lua 沙箱里不能用 `os.getenv`

```lua
-- ❌ 整个模块静默失效，而且 rime 的 ERROR 日志里什么都没有
local DIR = os.getenv("RIME_LLM_DIR") or "E:/APPs/rime-llm"
-- ✅
local DIR = "E:/APPs/rime-llm"
```

`os.getenv` 在 librime-lua 沙箱里可能不存在，调用会抛错 → `require` 失败 →
translator 直接消失。**错误不进 rime 日志**，只能靠自己在模块顶层写 marker 文件验证：

```lua
do
  local f = io.open(DIR .. "/clip_loaded.marker", "w")
  if f then f:write(os.date("%H:%M:%S") .. " loaded\n") f:close() end
end
```

这也是为什么所有路径都用硬编码 —— 环境变量的便利在这里换不来。

### 10. 绝对不要把 `yield` 包进 `pcall` ⚠️ 最坑的一个

```lua
-- ❌ 候选不出来，而且 yield 之后的日志一行都不写
local ok, err = pcall(function()
  yield(cand)
end)
```

`yield` 是**协程挂起**，不是普通函数调用。包在 `pcall` 里会破坏协程边界，
表现是：**候选不出现，且连后面的代码都不执行**。查了两小时才定位。

正确做法是把「算数据」和「yield」分开：

```lua
-- ✅ 先把候选全部算好、日志写完，最后统一 yield
local out = {}
for i, it in ipairs(items) do
  out[#out + 1] = { text = ..., comment = ... }
end
common.dbg("准备 " .. #out .. " 条候选")     -- 一定落盘
for _, c in ipairs(out) do
  yield(Candidate("clip", sstart, send, c.text, c.comment))
end
```

同理，`M.func` 整体也不能套 `pcall`。

### 11. Python `write_text` 在 Windows 会写 CRLF

```python
tmp.write_text(body, encoding="utf-8")              # ❌ 换成 

tmp.write_text(body, encoding="utf-8", newline="")   # ✅ 强制 LF
```

Lua 的 `f:lines()` 按 `
` 切分，行尾会残留 ``，
读出来带看不见的控制字符，`string.format("%q")` 打日志时特别迷惑。

### 12. `tools/test_ime_gui.ps1` 的两个坑

Win11 记事本是商店应用，`MainWindowHandle = 0`，`SetForegroundWindow` 抢不到焦点，
打的字进不了输入法。所以自己建 WinForms 窗口（HWND 是自己的，焦点稳）。

另外 `Add_Tick` 里的脚本块是**新作用域**，闭包外层的 `$t` 取不到，会报
`You cannot call a method on a null-valued expression`。直接顺序执行 + `DoEvents` 更可靠。

注意：`SendKeys` 要逐字符发，`{ESC}` 这种写法会被拆成 `{`、`E`、`S`、`C`、`}` 原样打出。

---

## 模糊拼音

`rime_ice.custom.yaml` 的 `speller/algebra/+` 里加了 10 条：

| 规则 | 解决什么 | 举例 |
|---|---|---|
| `derive/^([zcs])h/$1/` | zh/ch/sh → z/c/s | `jiecuqi` → 接触器 |
| `derive/^([zcs])([^h])/$1h$2/` | 反向 | |
| `derive/([aeiou])ng$/$1n/` | ang/eng/ing → an/en/in | `fen` → 风 |
| `derive/([aeiou])n$/$1ng/` | 反向 | `fang` → 反 |
| `derive/^l/n/` `derive/^n/l/` | n/l 不分 | `lainiu` → 牛奶 |
| `derive/^f/h/` `derive/^h/f/` | f/h 不分 | |
| `derive/^r/l/` `derive/^l/r/` | r/l 不分 | |

验证脚本直接解析 build 出来的 schema、模拟音节代数，**不依赖窗口焦点**：

```powershell
python tests/test_fuzzy_algebra.py
# 还原测试通过 7/7
```

---

## 专业词库

`mech.dict.yaml` 520 条（388 中文 + 132 英文缩写），覆盖机电一体化 / 电气自动化 /
工业机器人 / PLC / 单片机方向。由 `dictgen/` 生成：

```
CORE_MECH       核心 292 条（电机拖动、低压电器、传感检测、液压气动、机械传动、
                            加工工艺、精度制图、配电、PLC、机器人、单片机、仪表、安全运维）
LONG_TAIL_MECH  长尾 103 条（变频器调试、装配维修、机器人示教、伺服调试、电气施工验收）
TOOLS           工程软件 32 条（AutoCAD / SolidWorks / UG NX / ANSYS / Keil / 博途 / GX Works…）
STD             标准规范 7 条
ABBR            英文缩写 77 条（PLC / HMI / Modbus / EtherCAT / STM32 / OPC UA…）
DAILY           日常高频（大部分已在基础词库里，不重复塞）
```

改词库：

```powershell
python dictgen/build_dicts.py    # 生成 mech.dict.yaml
python build_wordlist.py         # 重建 AI 联想的合法性校验表（别漏这步！）
& 'C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe' /deploy
```

### 多音字纠正

pypinyin 按常用读音给，专业词里读法不同：

| 词 | pypinyin | 正确 |
|---|---|---|
| 伺服* | `ci fu` | **`si fu`** |
| 调质 | `diao zhi` | **`tiao zhi`** |
| 调速阀 | `diao su fa` | **`tiao su fa`** |

`伺服` 系列用通用规则兜底，新增词不会再错：

```python
if word.startswith("伺服"):
    code = re.sub(r"^ci\b", "si", code)
```

---

## 性能调优

| 优化 | 效果 |
|---|---|
| 去掉 400 MB 万象语法模型（`grammar: null`） | 卡顿主因，直接消除 |
| translators 13 → 6、filters 8 → 2 | 每键少跑 14 个组件 |
| 注释掉 `cn_dicts/tencent`（98 万条） | `table.bin` 57.8 → **27.7 MB**，部署 18 → **4.6 秒** |
| 关掉 emoji / 简繁转换开关 | 消除每次启动的 `opencc config not found: s2t.json` |
| `contextual_suggestions: false`、`max_homophones: 3` | 候选生成量降一个档 |

去掉 tencent 后常用词抽样 **26/26 全部还在** base 里，一个没丢。
它是长尾短语库，日常打字基本用不上。

> 小狼毫的虚拟内存显示 6,691 MB 是 `mmap` 预留地址空间，
> 实际物理内存只有 40~62 MB。**不是内存泄漏，不用管。**

---

## 测试

```powershell
python tests/test_llm_translator.py   # Lua 模块单测（需要 lupa）  14/14
python tests/test_fuzzy_algebra.py    # 模糊拼音（解析 build 出的 schema）  7/7
python tests/test_wordlist.py         # 词表校验（专业词通过 / 碎片拦截）  18/18
```

`tests/test_llm_translator.py` 用 [lupa](https://pypi.org/project/lupa/) 把 Lua 模块塞进真解释器跑，
不需要部署、不需要打字。注意 lua 里 `yield` 是保留字，测试时要把 `yield(` 换成 `_yield(`。

**GUI 打字测试在 Win11 上不可用**：记事本是商店应用，`MainWindowHandle = 0`，
`SetForegroundWindow` 抢不到焦点。这类验证走数据级（解析 schema / 查词表）。

---

## 日志与排查

小狼毫的日志在 `%TEMP%\rime.weasel\`，最有用的几行：

```
I entry_collector.cc:58] collecting entries from ...\mech.dict.yaml
I entry_collector.cc:129] Pass 1: total 9314 entries collected.   ← 确认词库进了
E table.cc:260] Error opening table file ...                      ← 词库没编译
```

守护进程的日志在 `<RIME_LLM_DIR>\llm_daemon.log`：

```powershell
python llm_daemon.py --status    # 模型 / 显存 / 缓存条数
python llm_daemon.py --unload    # 强制释放内存
python llm_daemon.py --once      # 只跑一轮（调试用）
```

---

## 出处与许可

本仓库是 [**rime-ice（雾凇拼音）**](https://github.com/iDvel/rime-ice) 的修改版，
遵循其 **GPL-3.0** 许可。原项目的 `LICENSE` 与版权声明保持不变。

新增的部分（AI 联想链路、专业词库生成器、词表校验、模糊音测试）同样以 GPL-3.0 发布。

参考过的项目：

- [scukeqi/Wisdom-Weasel](https://github.com/scukeqi/Wisdom-Weasel) —— 同样思路的小狼毫改造，
  它的文档里「推荐使用 Base 模型」这句是本文档第 5 节结论的来源之一
- [openbmb/MiniCPM4-0.5B](https://huggingface.co/openbmb/MiniCPM4-0.5B-QAT-Int4-GGUF) —— 端侧模型
- [Ollama](https://ollama.com/) —— 本地推理引擎
- [librime-lua](https://github.com/hchunhui/librime-lua) —— Lua 扩展

模型权重不在本仓库内，按各自许可单独下载。
