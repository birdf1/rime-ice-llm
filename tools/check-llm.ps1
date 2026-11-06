# check-llm.ps1 —— 检查前文联写是不是真的在工作
#
# 用法：powershell -ExecutionPolicy Bypass -File .\check-llm.ps1
#
# 判据（按顺序）：
#   1. lua 模块被加载了吗（llm_loaded.marker）
#   2. 你打字时 lua 有没有写请求（llm_req.txt 有内容）
#   3. daemon 有没有处理（llm_daemon.log）
#   4. 缓存有没有生成（llm_cache.txt）
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DIR = 'E:\APPs\rime-llm'
$PY  = 'C:\Python313\python.exe'

function Ok($m)  { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad($m) { Write-Host "  [--]   $m" -ForegroundColor Yellow }

Write-Host "`n== 1. lua 模块加载 =="
$mk = Join-Path $DIR 'llm_loaded.marker'
if (Test-Path $mk) { Ok "已加载：$(Get-Content $mk -Raw)" }
else { Bad "还没加载 —— 需要真实敲一次键（随便在记事本里打几个字母）" }

Write-Host "== 2. 请求队列 =="
$rq = Join-Path $DIR 'llm_req.txt'
if (Test-Path $rq) {
    $sz = (Get-Item $rq).Length
    if ($sz -gt 0) { Ok "有 $sz 字节待处理"; Get-Content $rq -Encoding utf8 | Select-Object -First 5 | ForEach-Object { Write-Host "        $_" } }
    else { Bad "队列空 —— 打几个字看看" }
}
# 也看历史：日志里有 req 记录说明 lua 写过
$dbg = Join-Path $DIR 'llm_debug.log'
if (Test-Path $dbg) { Ok ("lua 调试日志有 {0} 字节" -f (Get-Item $dbg).Length) }

Write-Host "== 3. daemon 处理日志 =="
$log = Join-Path $DIR 'llm_daemon.log'
if (Test-Path $log) {
    $tail = Get-Content $log -Tail 6 -Encoding utf8
    Ok "最近 6 条："
    $tail | ForEach-Object { Write-Host "        $_" }
} else { Bad "daemon 没跑过" }

Write-Host "== 4. 缓存 =="
$cache = Join-Path $DIR 'llm_cache.txt'
if (Test-Path $cache) {
    $lines = Get-Content $cache -Encoding utf8
    Ok "$($lines.Count) 条缓存："
    $lines | Select-Object -Last 6 | ForEach-Object { Write-Host "        $_" }
} else { Bad "没有缓存文件" }

Write-Host "== 5. Ollama 与模型 =="
& $PY 'E:\APPs\小狼毫\llm_daemon.py' --status 2>&1 | ForEach-Object { Write-Host "  $_" }

Write-Host "`n下一步：" -ForegroundColor Cyan
Write-Host "  若第 1 项没 OK：去记事本随便打几个字母（必须切到小狼毫输入法）"
Write-Host "  若第 2 项有内容但第 3 项空：daemon 没在跑，执行"
Write-Host "    $PY E:\APPs\小狼毫\llm_daemon.py"
Write-Host "  若都通了但打字看不到 AI 候选："
Write-Host "    先打一句话上屏（比如「我今天」），再打下一句的开头字母，候选里应出现带「联」标记的词"
Write-Host ""
