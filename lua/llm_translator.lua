--[[
llm_translator.lua —— 小狼毫「前文联写」候选（librime-lua）

═══════════════════════════════════════════════════════════════════
定位（2026-11-06 实测确定）

❌ 不做「拼音 → 汉字」。1.5b/3b 小模型干这个错得离谱：
     zhegegongnengbucuo → 这个功能出错（实际是不错）
     womenzai           → 女人在（实际是我们）
   rime 自己 57MB 词库 + 用户词典准得多。

✅ 做「已输入的文字 → 预测下一个词」。这是语言建模，小模型擅长：
     「我刚吃完饭，准备去」→ 散步 / 看电影 / 购物   (40-200ms)
     「这个问题比较复杂，需要」→ 深入分析
   这正是微信输入法"聪明"的来源。

═══════════════════════════════════════════════════════════════════
关键设计约束（决定成败，别改）

小狼毫的 Lua 里 os.execute / io.popen 都是**同步阻塞**的。
在 translator 里直接发 HTTP = 每敲一键卡 200ms~2s。

所以这里只做两件微秒级的事：
  ① 读  data/llm_cache.txt          （上文<TAB>词1|词2|词3<TAB>时间戳）
  ② 追加 data/llm_req.txt           （上文）
真正的模型调用由 llm_daemon.py 后台完成。

主线程永不等待网络 → 模型再慢也不卡打字。

入口函数名必须是 func + init（librime-lua 约定）。
写成 M.translator 模块根本不会被调用 —— 这个坑踩过。
]]

local M = {}

-- ───────────────────────── 可调参数 ─────────────────────────
local MIN_CTX   = 4         -- 上文至少几个汉字才开始预测
local SHOW_MAX  = 2         -- 最多显示几条 AI 候选
local LABEL     = "联"      -- 候选右侧标记（"联想"太长了）
local TTL       = 900       -- 缓存有效期（秒）
local REQ_GAP   = 3         -- 同一上文两次请求最小间隔（秒）
local DEBUG     = false     -- 排障时改 true

-- ───────────────────────── 路径 ─────────────────────────
-- ⚠️ 必须是纯 ASCII 路径！
--    Lua 的 io.open 在 Windows 上走 ANSI(GBK) 的 fopen，
--    遇到 "小狼毫" 这种中文目录会返回 "Illegal byte sequence"，
--    于是缓存永远读不到、请求永远写不出去 —— 而且不报错，极难发现。
--    所以数据目录单独放在 E:/APPs/rime-llm（纯英文）。
-- ⚠️ 必须是纯 ASCII 路径！
--    Lua 的 io.open 在 Windows 上走 ANSI(GBK) 的 fopen，
--    遇到 "小狼毫" 这类中文目录会返回 "Illegal byte sequence"，而且**静默失败**。
--    想换位置就设环境变量 RIME_LLM_DIR（同样要纯 ASCII）。
local DIR = os.getenv("RIME_LLM_DIR") or "E:/APPs/rime-llm"
local CACHE_FILE = DIR .. "/llm_cache.txt"
local REQ_FILE   = DIR .. "/llm_req.txt"
local DBG_FILE   = DIR .. "/llm_debug.log"

-- 加载标记：验证模块真的被 require 了
do
  local mf = io.open(DIR .. "/llm_loaded.marker", "w")
  if mf then
    mf:write(os.date("%Y-%m-%d %H:%M:%S") .. " loaded\n")
    mf:close()
  end
end

-- ───────────────────────── 状态 ─────────────────────────
local cache     = {}    -- ctx -> { words, at }
local cache_len = -1    -- 上次解析时的文件长度
local last_req  = {}    -- ctx -> epoch

local function log(msg)
  if not DEBUG then return end
  local f = io.open(DBG_FILE, "a")
  if f then f:write(os.date("%H:%M:%S ") .. tostring(msg) .. "\n"); f:close() end
end

-- 读缓存（文件长度变了才重新解析，零成本）
local function load_cache()
  local f = io.open(CACHE_FILE, "r")
  if not f then return end
  local body = f:read("*a")
  f:close()
  if not body or #body == 0 or #body == cache_len then return end
  cache_len = #body

  local n = 0
  cache = {}
  for line in body:gmatch("[^\r\n]+") do
    local k, words, ts = line:match("^([^\t]+)\t([^\t]*)\t?(%d*)$")
    if k and words and #words > 0 then
      local list = {}
      for w in words:gmatch("[^|]+") do list[#list + 1] = w end
      if #list > 0 then
        cache[k] = { words = list, at = tonumber(ts) or 0 }
        n = n + 1
      end
    end
  end
  log("cache reloaded: " .. n .. " entries")
end

-- 追加请求（O(1)，不重写文件）
local function push_request(ctx)
  local t = os.time()
  if last_req[ctx] and (t - last_req[ctx]) < REQ_GAP then return end
  last_req[ctx] = t
  local f = io.open(REQ_FILE, "a")
  if not f then return end
  f:write(ctx .. "\n")
  f:close()
  log("req: " .. ctx)
end

-- 取上文：最近提交的文字
-- ⚠️ 正确 API 是 commit_history:latest_text()，不是 context:get_commit_text()。
--    get_commit_text() 返回的是"当前这次提交"的内容（还没上屏时是空串），
--    latest_text() 才是真正的历史。这个坑对照 en_spacer.lua 才发现的。
local function get_context(env)
  if not env or not env.engine then return "" end
  local ch = env.engine.context and env.engine.context.commit_history
  if not ch then return "" end
  local ok, txt = pcall(function() return ch:latest_text() end)
  if not ok or type(txt) ~= "string" or #txt == 0 then return "" end
  -- 只留汉字（UTF-8 汉字首字节 e4~e9，即 228~233）
  local han = {}
  for ch1 in txt:gmatch("[^\128-\191][\128-\191]*") do
    local b = ch1:byte(1)
    if b and b >= 228 and b <= 233 then han[#han + 1] = ch1 end
  end
  return table.concat(han):sub(-30)
end

-- ───────────────────────── 入口 ─────────────────────────
function M.init(env)
  local cfg = env and env.engine and env.engine.schema and env.engine.schema.config
  if cfg then
    local ns = (env.name_space or ""):gsub("^%*", "")
    local ok1, v1 = pcall(function() return cfg:get_int(ns .. "/min_ctx") end)
    if ok1 and type(v1) == "number" and v1 > 0 then MIN_CTX = v1 end
    local ok2, v2 = pcall(function() return cfg:get_int(ns .. "/show_max") end)
    if ok2 and type(v2) == "number" and v2 > 0 then SHOW_MAX = v2 end
  end
end

-- 主入口。input 是当前编码串。
-- 返回联想候选的条件：有上文 且 缓存里有预测结果。
function M.func(input, seg, env)
  load_cache()

  local ctx = get_context(env)
  -- 排障：把拿到的上文写进日志，看它到底是空还是短
  log(string.format("func input=%q ctx=%q len=%d MIN=%d",
      tostring(input), tostring(ctx), #ctx, MIN_CTX))
  if #ctx < MIN_CTX then return end

  local hit = cache[ctx]
  if hit and (os.time() - hit.at) < TTL then
    log("HIT ctx=" .. ctx .. " words=" .. table.concat(hit.words, "/"))
    local n = 0
    for _, w in ipairs(hit.words) do
      if n >= SHOW_MAX then break end
      yield(Candidate("llm", seg.start, seg._end, w, LABEL))
      n = n + 1
    end
    log("yielded " .. n .. " candidates")
    return
  end

  -- 没缓存：排队，下次按键时可能就有了
  push_request(ctx)
end

return M
