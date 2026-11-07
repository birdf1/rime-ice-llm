-- clip_processor.lua —— 剪切板候选的「数字键直接上屏全文」
--
-- 为什么需要这个：
--   rime 候选的 text 字段同时用于「显示」和「上屏」，没法只显示预览而上屏全文。
--   所以候选只放预览，真正的全文在这里拦截数字键后直接 commit_text。
--
-- 必须放在 processors 列表最前面（ascii_composer 之前）：
--   如果排在 speller 后面，按下的 '1' 会先被 speller 吃进 composition，
--   ctx.input 变成 "v1" 就不再等于 "v" 了。
--
-- 只有 ctx.input 正好等于 "v" 时才动，其它情况一律 kNoop，不影响正常打字。

local common = require("clip_common")

local M = {}

local SHOW_MAX = 6

local kRejected = 0
local kAccepted = 1
local kNoop = 2

function M.init(env)
end

function M.func(key, env)
  local ctx = env.engine.context

  -- 只在「正好输了个 v」时接管
  if ctx.input ~= "v" then return kNoop end
  if not common.enabled() then return kNoop end

  -- 只要按下，不要抬起，否则会触发两次
  if key:release() then return kNoop end

  -- 带修饰键的（Ctrl+V 之类）不碰
  if key:ctrl() or key:alt() or key:super() then return kNoop end

  local ch = key:repr()
  local n = tonumber(ch)
  if not n or n < 1 or n > SHOW_MAX then return kNoop end

  local items = common.load(SHOW_MAX)
  local it = items[n]
  if not it or it.text == "" then return kNoop end

  env.engine:commit_text(it.text)
  ctx:clear()
  return kAccepted
end

return M
