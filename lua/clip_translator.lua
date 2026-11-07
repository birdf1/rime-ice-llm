-- clip_translator.lua —— 打 v 时把剪切板历史列成候选
--
-- 只对「输入正好是 v」生效。
-- v 后面再跟数字/字母的（v1、vs 之类）交给 rime-ice 原有的 symbols_v 处理，
-- 这里不插手。
--
-- 候选显示的是单行预览（截断到 44 字），真正上屏的全文由 clip_processor.lua
-- 在数字键被按下时直接 commit —— 因为 rime 候选的 text 同时是「显示」和「上屏」，
-- 放全文会把候选栏拉成一条长带。

local common = require("clip_common")

local M = {}

local SHOW_MAX = 6        -- 与 menu/page_size 对齐
local PREVIEW_W = 44
local ZWSP = "\226\128\139"   -- U+200B 零宽空格

function M.init(env)
  -- 入口必须是 M.init + M.func。
  -- 写成 M.translator 不会报错，但永远不被调用。
end

function M.func(input, seg, env)
  if input ~= "v" then return end
  if not common.enabled() then return end

  local items = common.load(SHOW_MAX)
  if #items == 0 then return end

  for i, it in ipairs(items) do
    local shown = common.preview(it.text, PREVIEW_W)
    -- 尾部补零宽空格：uniquifier 过滤器按 text 去重，
    -- 两条不同内容若截断后预览相同会被吞掉一条，导致菜单序号与
    -- processor 的索引错位 —— 用户按 2 却上屏第 3 条。
    -- 零宽空格不可见，就算真被上屏也无害。
    shown = shown .. string.rep(ZWSP, i)

    local nchar = common.utf8_len(it.text)
    yield(Candidate("clip", seg.start, seg._end, shown,
                    string.format("%s · %d字", it.time, nchar)))
  end
end

return M
