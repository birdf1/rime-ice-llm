-- clip_common.lua —— 剪切板历史的读取与显示处理
-- 被 clip_translator.lua 和 clip_processor.lua 共用
--
-- ⚠️ 数据目录必须是纯 ASCII 路径。
--    Lua 的 io.open 在 Windows 上走 ANSI(GBK) 的 fopen，
--    遇到 "小狼毫" 这类中文目录会返回 "Illegal byte sequence"，而且不报错。
--    所以数据目录单独放在 E:/APPs/rime-llm（纯英文）。
--
-- ⚠️ 不要用 os.getenv()：librime-lua 沙箱里 os 库不保证带 getenv，
--    调用会抛错导致整个模块加载失败，而且错误不进 rime 日志，极难发现。
--    这里跟 llm_translator.lua 一样用硬编码路径。

local M = {}

local DIR = "E:/APPs/rime-llm"
M.CACHE = DIR .. "/clip_cache.txt"
M.DIR = DIR
local DBG = DIR .. "/clip_debug.log"

-- 跨组件共享状态：filter 写入，processor 读取。
-- librime-lua 的所有组件跑在同一个 Lua state 里，模块级表可以直接共享。
-- 这是「processor 只在候选真的显示了才抢数字键」的关键保险。
M.state = { active = false, count = 0, items = {} }

-- 加载标记：验证模块真的被 require 了
-- （librime-lua 懒加载，部署时不报语法错，只能靠这个确认）
do
  local f = io.open(DIR .. "/clip_loaded.marker", "w")
  if f then
    f:write((os.date and os.date("%Y-%m-%d %H:%M:%S") or "?") .. " clip_common loaded\n")
    f:close()
  end
end

local DEBUG = false  -- 排障时改 true，会在 <DIR>/clip_debug.log 记流水（默认关闭，避免长期写盘）

function M.dbg(msg)
  if not DEBUG then return end
  local f = io.open(DBG, "a")
  if f then
    f:write((os.date and os.date("%H:%M:%S") or "?") .. " " .. tostring(msg) .. "\n")
    f:close()
  end
end

-- 开关：<DIR>/clip_off 存在就停用（不改配置就能临时关掉）
function M.enabled()
  local f = io.open(DIR .. "/clip_off", "r")
  if f then f:close() return false end
  return true
end

-- 反转义：Python 侧写的是 \\  \n  \t
local function unescape(s)
  return (s:gsub("\\(.)", function(c)
    if c == "n" then return "\n" end
    if c == "t" then return "\t" end
    if c == "\\" then return "\\" end
    return c
  end))
end

-- 读前 limit 条。格式：<序号>\t<时间>\t<正文>
function M.load(limit)
  limit = limit or 6
  local out = {}
  local f = io.open(M.CACHE, "r")
  if not f then
    M.dbg("io.open 失败: " .. M.CACHE)
    return out
  end
  for line in f:lines() do
    -- 行尾可能带 \r（Windows 换行），下面会把 \r 去掉
    local idx, tm, body = line:match("^(%d+)\t([^\t]*)\t(.*)$")
    if body and idx then
      out[#out + 1] = {
        n = tonumber(idx),
        time = (tm:gsub("\r", "")),
        text = unescape(body),
      }
      if #out >= limit then break end
    end
  end
  f:close()
  M.dbg(string.format("load -> %d 条", #out))
  return out
end

-- UTF-8 字符数（数非续字节）
function M.utf8_len(s)
  local _, n = s:gsub("[^\128-\191]", "")
  return n
end

-- 生成单行预览，超长按 UTF-8 安全截断
function M.preview(s, width)
  width = width or 38
  s = s:gsub("[\r\n\t]+", " ")
  s = s:gsub("%s+", " ")
  s = s:gsub("^%s+", ""):gsub("%s+$", "")
  if M.utf8_len(s) <= width then return s end

  local n, i = 0, 1
  while i <= #s do
    local b = s:byte(i)
    local step = (b >= 0xF0 and 4) or (b >= 0xE0 and 3) or (b >= 0xC0 and 2) or 1
    if n + 1 > width then break end
    n = n + 1
    i = i + step
  end
  return s:sub(1, i - 1) .. "…"
end

return M
