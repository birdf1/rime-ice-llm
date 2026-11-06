# 出处与改动说明

## 上游

本仓库是 **雾凇拼音（rime-ice）** 的修改版本。

- 上游项目：https://github.com/iDvel/rime-ice
- 上游许可：GNU General Public License v3.0（见 `LICENSE`，原样保留）
- 上游版权归其作者所有

## 本仓库新增/修改的内容

| 文件 | 说明 |
|---|---|
| `lua/llm_translator.lua` | **新增** —— AI 联想 translator（读缓存 / 写请求，不碰网络） |
| `llm_daemon.py` | **新增** —— 后台守护进程，调 Ollama 做前文联写 |
| `build_wordlist.py` | **新增** —— 从 rime 词库构建候选合法性校验表 |
| `dictgen/wordlists.py` | **新增** —— 专业词表（机电 / 电气 / 机器人 / PLC / 单片机） |
| `dictgen/build_dicts.py` | **新增** —— 生成 `mech.dict.yaml` |
| `mech.dict.yaml` | **新增** —— 520 条专业词库 |
| `tests/*.py` | **新增** —— Lua 单测 / 模糊音验证 / 词表验证 |
| `tools/*` | **新增** —— 模型横评、自检、打字验证、安装脚本 |
| `rime_ice.custom.yaml` | **修改** —— 性能调优、模糊音开关、AI translator 挂载 |
| `rime_ice.dict.yaml` | **修改** —— 挂载 `mech` 词库，注释掉 `tencent` |

## 修改摘要

1. **性能**：移除 400 MB 语法模型依赖；translators 13→6、filters 8→2；
   注释掉 98 万条的 tencent 长尾词库（`table.bin` 57.8→27.7 MB，部署 18→4.6 秒）；
   关闭 emoji 与简繁转换开关（原配置引用了不存在的 `s2t.json`，每次启动报错）。
2. **模糊拼音**：`speller/algebra/+` 新增 10 条 derive 规则（平翘舌 / 前后鼻音 / n-l / f-h / r-l）。
3. **专业词库**：新增 `mech.dict.yaml`（520 条）。权重处理遵循「只升不降」
   —— 取 `max(现有权重, 保底值)`，避免覆盖上游更高的词频。
4. **AI 联想**：新增 `lua_translator` + Python 守护进程 + MiniCPM4-0.5B 本地推理。

## 第三方

- **MiniCPM4-0.5B**：https://huggingface.co/openbmb/MiniCPM4-0.5B-QAT-Int4-GGUF
  模型权重不随本仓库分发，按模型自身许可单独下载。
- **Ollama**：本地推理引擎，需要单独安装。
- **lupa**：仅测试时需要（`pip install lupa`）。