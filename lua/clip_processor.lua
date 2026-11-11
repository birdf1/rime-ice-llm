-- clip_processor.lua —— 剪切板候选的「数字键直接上屏全文」
--
-- 为什么需要这个：
--   rime 候选的 text 字段同时用于「显示」和「上屏」，没法只显示预览而上屏全文。
--   所以候选只放预览，真正的全文在这里拦截数字键后直接 commit_text。
--
-- ⚠️ 关键保险：必须先确认「剪切板候选真的在屏幕上」才敢抢数字键。
--    早期版本只看 ctx.input=="v" 就抢，结果候选栏显示的其实是英文
--    （VFD / Visual Studio ...），用户按 1 想选 VFD，却被粘贴了剪切板里的
--    文件路径 —— 这是个会毁掉正常输入的严重 bug。
--    现在靠 common.state.active（由 clip_filter 在真正插入候选时置位）把关。

local common = require("clip_common")

local M = {}

local kNoop = 2
local kAccepted = 1

function M.init(env)
  common.dbg("clip_processor.init 被调用")
end

function M.func(key, env)
  local ctx = env.engine.context

  -- 只在「正好输了个 v」且剪切板候选确实已显示时才接管
  if ctx.input ~= "v" then return kNoop end
  if not common.state.active then return kNoop end

  -- 只要按下，不要抬起，否则会触发两次
  if key:release() then return kNoop end

  -- 带修饰键的（Ctrl+V 之类）不碰
  if key:ctrl() or key:alt() or key:super() then return kNoop end

  local n = tonumber(key:repr())
  if not n or n < 1 or n > (common.state.count or 0) then return kNoop end

  local it = (common.state.items or {})[n]
  if not it or it.text == "" then return kNoop end

  common.dbg(string.format("v+%d -> 上屏 %d 字", n, common.utf8_len(it.text)))
  env.engine:commit_text(it.text)
  ctx:clear()
  common.state.active = false
  return kAccepted
end

return M
