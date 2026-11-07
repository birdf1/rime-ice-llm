-- clip_translator.lua —— 打 v 时把剪切板历史列成候选
--
-- 只对「输入正好是 v」生效。
-- v 后面再跟数字/字母的（v1、vs 之类）交给 rime-ice 原有的 symbols_v 处理。
--
-- 候选显示单行预览（截断到 44 字），真正上屏的全文由 clip_processor.lua
-- 在数字键被按下时直接 commit —— 因为 rime 候选的 text 同时是「显示」和「上屏」，
-- 放全文会把候选栏拉成一条长带。
--
-- ⚠️ 绝对不要把 yield 包进 pcall！
--    yield 是协程挂起，包在 pcall 里会破坏协程边界，
--    表现是候选不出来、而且连后面的日志都不执行（排查了两小时）。
--    正确做法：先把所有候选算好、记完日志，最后统一 yield。

local common = require("clip_common")

local M = {}

local SHOW_MAX = 6        -- 与 menu/page_size 对齐
local PREVIEW_W = 44
local ZWSP = "\226\128\139"   -- U+200B 零宽空格

function M.init(env)
  -- 入口必须是 M.init + M.func。
  -- 写成 M.translator 不会报错，但永远不被调用。
  common.dbg("clip_translator.init 被调用")
end

function M.func(input, seg, env)
  if input ~= "v" then return end
  if not common.enabled() then
    common.dbg("被 clip_off 停用")
    return
  end

  local items = common.load(SHOW_MAX)
  if #items == 0 then
    common.dbg("没有剪切板历史，跳过")
    return
  end

  -- seg._end 在某些 librime-lua 版本里取不到，兜底用 start + #input
  local sstart = (seg and seg.start) or 0
  local send = (seg and seg._end) or (sstart + #input)

  -- ① 先把候选全部算出来（这一步不 yield，可以放心出错）
  local out = {}
  for i, it in ipairs(items) do
    local shown = common.preview(it.text, PREVIEW_W)
    -- 尾部补零宽空格：uniquifier 按 text 去重，
    -- 两条不同内容若截断后预览相同会被吞掉一条，导致菜单序号与
    -- processor 的索引错位 —— 用户按 2 却上屏第 3 条。
    shown = shown .. string.rep(ZWSP, i)

    out[#out + 1] = {
      text = shown,
      comment = string.format("%s · %d字", it.time, common.utf8_len(it.text)),
    }
  end

  -- ② 日志在 yield 之前写，保证一定能落到文件里
  common.dbg(string.format("v 匹配：准备 %d 条候选（seg %d-%d）",
    #out, sstart, send))

  -- ③ 最后统一 yield，yield 外面不能有 pcall
  for _, c in ipairs(out) do
    yield(Candidate("clip", sstart, send, c.text, c.comment))
  end
end

return M
