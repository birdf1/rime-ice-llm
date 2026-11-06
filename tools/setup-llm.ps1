# setup-llm.ps1 —— Ollama 装好后一键完成剩余步骤
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\setup-llm.ps1
#
# 它会：
#   1. 确认 Ollama 已安装并启动
#   2. 拉取 qwen2.5:1.5b 模型（约 1 GB，走代理）
#   3. 实测模型响应速度
#   4. 造一条测试请求，验证 llm_daemon.py 能正确产出候选
#   5. 装开机自启

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RIME   = 'E:\APPs\小狼毫'
$PY     = 'C:\Python313\python.exe'
$MODEL  = 'qwen2.5:1.5b'
$PROXY  = 'http://127.0.0.1:7890'

function Step($n, $m) { Write-Host "`n[$n] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  ✓ $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  ✗ $m" -ForegroundColor Yellow }

# ─────────────────── 1. 找 Ollama ───────────────────
Step 1 "定位 Ollama"
$ollama = $null
foreach ($p in @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "C:\Program Files\Ollama\ollama.exe",
    "$env:LOCALAPPDATA\Ollama\ollama.exe"
)) {
    if (Test-Path $p) { $ollama = $p; break }
}
if (-not $ollama) {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { $ollama = $cmd.Source }
}
if (-not $ollama) {
    Bad "没找到 ollama.exe，先装 Ollama"
    Write-Host "  下载：$env:TEMP\OllamaSetup.exe"
    Write-Host "  或跑：winget install Ollama.Ollama"
    exit 1
}
Ok "ollama: $ollama"
& $ollama --version 2>&1 | Select-Object -First 1

# ─────────────────── 2. 启动服务 ───────────────────
Step 2 "启动 Ollama 服务"
$alive = $false
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 -ErrorAction Stop
    $alive = ($r.StatusCode -eq 200)
} catch { $alive = $false }

if (-not $alive) {
    Write-Host "  服务没跑，启动中..."
    Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -eq 200) { $alive = $true; break }
        } catch {}
    }
}
if ($alive) { Ok "服务在线 127.0.0.1:11434" } else { Bad "服务起不来"; exit 1 }

# ─────────────────── 3. 拉模型 ───────────────────
Step 3 "拉取模型 $MODEL"
$tags = (Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5).Content | ConvertFrom-Json
$have = @($tags.models | ForEach-Object { $_.name })
if ($have -contains $MODEL -or $have -contains "$MODEL:latest") {
    Ok "模型已存在"
} else {
    Write-Host "  开始下载（约 1 GB，走代理 $PROXY）..."
    $env:HTTPS_PROXY = $PROXY
    $env:HTTP_PROXY  = $PROXY
    & $ollama pull $MODEL 2>&1 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -eq 0) { Ok "模型拉取完成" } else { Bad "拉取失败，可手动跑：$ollama pull $MODEL" }
}

# ─────────────────── 4. 测速 ───────────────────
Step 4 "实测模型响应速度"
$body = @{
    model  = $MODEL
    prompt = "拼音 nihao 对应的中文词是什么？只回答一个词。"
    stream = $false
    options = @{ num_predict = 10; temperature = 0.1 }
} | ConvertTo-Json -Depth 5

$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 60 -ErrorAction Stop
    $sw.Stop()
    Ok ("首字响应 {0:N0} ms，总耗时 {1:N1} s" -f $resp.prompt_eval_duration/1e6, $sw.Elapsed.TotalSeconds)
    Write-Host "  模型回复: $($resp.response.Trim())"
} catch {
    $sw.Stop()
    Bad "调用失败: $($_.Exception.Message)"
}

# ─────────────────── 5. 端到端测试 ───────────────────
Step 5 "端到端：模拟 lua 写请求 → daemon 产出候选"
$dataDir = Join-Path $RIME 'data'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Remove-Item "$dataDir\llm_cache.txt" -ErrorAction SilentlyContinue
# 造 3 条请求
@("nihao`t", "shijie`t", "zhongguo`t") | Out-File "$dataDir\llm_req.txt" -Encoding utf8
Write-Host "  已写入 3 条请求到 llm_req.txt"

& $PY (Join-Path $RIME 'llm_daemon.py') --once 2>&1 | ForEach-Object { Write-Host "    $_" }

if (Test-Path "$dataDir\llm_cache.txt") {
    Ok "缓存已生成："
    Get-Content "$dataDir\llm_cache.txt" -Encoding utf8 | ForEach-Object { Write-Host "      $_" }
} else {
    Bad "缓存没生成"
}

# ─────────────────── 6. 自启 ───────────────────
Step 6 "装开机自启"
& $PY (Join-Path $RIME 'llm_daemon.py') --install 2>&1 | ForEach-Object { Write-Host "    $_" }
$t = schtasks /Query /TN "RimeLLMDaemon" /FO LIST 2>&1
if ($LASTEXITCODE -eq 0) { Ok "计划任务 RimeLLMDaemon 已创建" } else { Bad "计划任务创建失败" }

# ─────────────────── 完成 ───────────────────
Write-Host "`n════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " 完成。现在去打字试试：" -ForegroundColor Cyan
Write-Host "   打 nihao  → 候选里应该有带 AI 标记的词"
Write-Host "   打 shijie → 同上"
Write-Host ""
Write-Host " 第一次按键是请求，第二次按键候选才会出现（异步设计）"
Write-Host " 看日志: $dataDir\llm_daemon.log"
Write-Host " 看状态: $PY $RIME\llm_daemon.py --status"
Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
