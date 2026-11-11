-- clip_filter.lua —— 打 v 时把剪切板历史插到候选流最前面
--
-- 为什么不用 translator：
--   实测发现 translator 产出的候选会被「分词竞争」吃掉 ——
--   只要 script_translator / melt_eng 对同一段输入也有产出，
--   我这个 translator 的整段翻译就被丢弃，连候选流里都看不到。
--   （对照实验：rq 只有 date_translator 有产出，能正常显示；
--     v / qq / zzz 都有别的译码器竞争，我的候选就消失了。）
--
--   filter 不一样：它拿到的是所有译码器合并后的候选流，
--   在这里 yield 的候选一定进菜单。rime-ice 自己的 pin_cand_filter
--   用的就是这个思路。
--
-- 附带好处：filter 在候选流里插东西，天然排在原有候选前面（先 yield 谁谁在前）。

local common = require("clip_common")

local M = {}

local SHOW_MAX = 6        -- 与 menu/page_size 对齐
local PREVIEW_W = 44
local ZWSP = "\226\128\139"   -- U+200B 零宽空格，用来给 processor 认领候选

function M.init(env)
  common.dbg("clip_filter.init 被调用")
end

function M.func(input, env)
  local ctx = env.engine.context
  local inp = ctx.input or ""

  -- 只有「正好一个 v」才进入剪切板模式
  if inp ~= "v" then
    -- 退出模式时清掉标记，否则 processor 会误抢数字键
    common.state.active = false
    for cand in input:iter() do
      yield(cand)
    end
    return
  end

  local items = common.enabled() and common.load(SHOW_MAX) or {}

  if #items == 0 then
    common.state.active = false
    for cand in input:iter() do
      yield(cand)
    end
    return
  end

  -- ① 先输出剪切板候选（先 yield 的排前面）
  local send = #inp
  local n = 0
  for i, it in ipairs(items) do
    local shown = common.preview(it.text, PREVIEW_W) .. string.rep(ZWSP, i)
    yield(Candidate("", 0, send, shown,
                    string.format("%s · %d字", it.time, common.utf8_len(it.text))))
    n = n + 1
  end

  -- ② 记下状态，给 processor 用（它只在 active 时才敢抢数字键）
  common.state.active = true
  common.state.count = n
  common.state.items = items

  common.dbg(string.format("filter 插入 %d 条剪切板候选", n))

  -- ③ 原有候选原样透传
  for cand in input:iter() do
    yield(cand)
  end
end

return M
