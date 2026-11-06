# verify-final.ps1 —— 最终验证：确认 lua 命中缓存后真的产出候选
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DIR   = 'E:\APPs\rime-llm'
$DBG   = "$DIR\llm_debug.log"
$REQ   = "$DIR\llm_req.txt"
$CACHE = "$DIR\llm_cache.txt"

# 清空调试日志，但保留缓存（缓存里已有「我今天天气很好」）
Remove-Item $DBG -ErrorAction SilentlyContinue
if (Test-Path $REQ) { Set-Content $REQ '' -Encoding utf8 }

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern IntPtr SendInput(uint n, INPUT[] p, int cb);
    [DllImport("user32.dll")] public static extern IntPtr GetKeyboardLayout(uint idThread);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT { public uint type; public KEYBDINPUT ki; public int pad1, pad2; }
    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT { public ushort wVk, wScan; public uint dwFlags, time; public IntPtr dwExtraInfo; }
    public static string Title() {
        var sb = new StringBuilder(256);
        GetWindowText(GetForegroundWindow(), sb, 256);
        return sb.ToString();
    }
    public static string Layout() {
        IntPtr h = GetForegroundWindow();
        uint pid; uint tid = GetWindowThreadProcessId(h, out pid);
        return GetKeyboardLayout(tid).ToInt64().ToString("X8");
    }
    public static void Key(ushort vk, bool up) {
        INPUT[] i = new INPUT[1];
        i[0].type = 1; i[0].ki.wVk = vk; i[0].ki.dwFlags = up ? (uint)2 : 0;
        SendInput(1, i, Marshal.SizeOf(typeof(INPUT)));
    }
    public static void Type(string s, int ms) {
        foreach (char c in s) {
            ushort vk = (ushort)Char.ToUpper(c);
            Key(vk, false); System.Threading.Thread.Sleep(ms);
            Key(vk, true);  System.Threading.Thread.Sleep(ms);
        }
    }
    public static void Press(ushort vk) {
        Key(vk, false); System.Threading.Thread.Sleep(100);
        Key(vk, true);  System.Threading.Thread.Sleep(100);
    }
}
"@

$np = Start-Process notepad -PassThru
Start-Sleep -Seconds 3

Add-Type -AssemblyName Microsoft.VisualBasic
foreach ($t in @('记事本','Untitled - Notepad','无标题 - 记事本')) {
    try { [Microsoft.VisualBasic.Interaction]::AppActivate($t) | Out-Null; break } catch {}
}
Start-Sleep -Seconds 1

Write-Host "前台窗口: $([Win]::Title())"
Write-Host "键盘布局: $([Win]::Layout())   (08040804=中文)"

if ($args -contains '-clean') {
    Write-Host "`n[clean 模式] 先打一句并上屏"
    [Win]::Type("wojintiantianqihenhao", 75)
    Start-Sleep -Milliseconds 600
    [Win]::Press(0x20)   # 空格上屏
    Start-Sleep -Seconds 4
    Write-Host "  已上屏，等 daemon 处理完"
}

Write-Host "`n打下一句拼音（缓存里已有「我今天天气很好」）"
[Win]::Type("women", 75)
Start-Sleep -Milliseconds 500
[Win]::Type("zou", 75)
Start-Sleep -Seconds 2

if ($np) { $np.CloseMainWindow() | Out-Null }
Start-Sleep -Seconds 1
if ($np -and -not $np.HasExited) { Stop-Process -Id $np.Id -Force }

Write-Host "`n=== 结果 ==="
if (Test-Path $DBG) {
    $d = Get-Content $DBG -Encoding utf8
    Write-Host "调试日志 $($d.Count) 行" -ForegroundColor Green
    $hits = $d | Select-String 'HIT|yielded'
    if ($hits) {
        Write-Host "  ✅ 命中并产出候选：" -ForegroundColor Green
        $hits | Select-Object -Last 6 | ForEach-Object { Write-Host "     $_" }
    } else {
        Write-Host "  未命中（缓存 key 不匹配）" -ForegroundColor Yellow
        $d | Select-Object -Last 6 | ForEach-Object { Write-Host "     $_" }
    }
} else {
    Write-Host "  无调试日志 —— func 未被调用" -ForegroundColor Yellow
}
