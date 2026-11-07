-- clip_common.lua —— 剪切板历史的读取与显示处理
-- 被 clip_translator.lua 和 clip_processor.lua 共用
--
-- ⚠️ 数据目录必须是纯 ASCII 路径。
--    Lua 的 io.open 在 Windows 上走 ANSI(GBK) 的 fopen，
--    遇到 "小狼毫" 这类中文目录会静默返回 nil —— 不报错、不打印。

local M = {}

local DIR = os.getenv("RIME_LLM_DIR") or "E:/APPs/rime-llm"
M.CACHE = DIR .. "/clip_cache.txt"
M.DIR = DIR

-- 反转义：Python 侧写的是 \\  \n  \t
local function unescape(s)
  local out = s:gsub("\\(.)", function(c)
    if c == "n" then return "\n" end
    if c == "t" then return "\t" end
    if c == "\\" then return "\\" end
    return c
  end)
  return out
end


-- 开关：<DIR>/clip_off 存在就停用（不改配置就能临时关掉）
-- 这样万一哪天想用 v1 符号，创建一个空文件即可
function M.enabled()
  local f = io.open(DIR .. "/clip_off", "r")
  if f then f:close() return false end
  return true
end

-- 读前 limit 条。格式：<序号>\t<时间>\t<正文>
function M.load(limit)
  limit = limit or 6
  local out = {}
  local f = io.open(M.CACHE, "r")
  if not f then return out end
  for line in f:lines() do
    local idx, tm, body = line:match("^(%d+)\t([^\t]*)\t(.*)$")
    if body and idx then
      out[#out + 1] = {
        n = tonumber(idx),
        time = tm,
        text = unescape(body),
      }
      if #out >= limit then break end
    end
  end
  f:close()
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
  s = s:gsub("[\r\n\t]+", " ")       -- 换行制表 -> 空格
  s = s:gsub("%s+", " ")             -- 连续空白压成一个
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
