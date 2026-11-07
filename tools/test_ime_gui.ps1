# test_ime_gui.ps1 —— 用真实 Win32 窗口验证输入法
#
# 为什么不用记事本：
#   Win11 记事本是商店应用，MainWindowHandle = 0，
#   SetForegroundWindow 抢不到焦点，打的字全进不了输入法。
#   这里自己建 WinForms 窗口 —— HWND 是自己的，焦点拿得稳，IME 能正常挂上去。
#
# 为什么不用 Timer：
#   Add_Tick 里的脚本块是新作用域，闭包外层的 $t 取不到，会报
#   "You cannot call a method on a null-valued expression"。
#   直接在 Add_Shown 里顺序执行 + DoEvents 更简单可靠。
#
# 用法：
#   pwsh -File test_ime_gui.ps1 -Keys "v"
#   pwsh -File test_ime_gui.ps1 -Keys "v1"      # 验证 v+数字 上屏全文
#   pwsh -File test_ime_gui.ps1 -Keys "nihao"   # 验证普通拼音没被破坏

param(
    [string]$Keys = "v",
    [int]$KeyGapMs = 200,
    [int]$SettleMs = 1200,
    [int]$WarmupMs = 600
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
}
"@

$form = New-Object System.Windows.Forms.Form
$form.Text = "IME Test"
$form.Size = New-Object System.Drawing.Size(680, 220)
$form.StartPosition = "CenterScreen"
$form.TopMost = $true

$tb = New-Object System.Windows.Forms.TextBox
$tb.Multiline = $true
$tb.Dock = "Fill"
$tb.Font = New-Object System.Drawing.Font("Microsoft YaHei", 14)
$form.Controls.Add($tb)

$form.Add_Shown({
    $form.Activate()
    [void][W32]::BringWindowToTop($form.Handle)
    [void][W32]::SetForegroundWindow($form.Handle)
    $tb.Focus()
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds $WarmupMs
    [System.Windows.Forms.Application]::DoEvents()

    $fg = [W32]::GetForegroundWindow()
    Write-Host "  焦点: $(if($fg -eq $form.Handle){'OK'}else{"错 ($fg vs $($form.Handle))"})"

    foreach ($ch in $Keys.ToCharArray()) {
        [System.Windows.Forms.SendKeys]::SendWait($ch.ToString())
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds $KeyGapMs
    }

    $deadline = (Get-Date).AddMilliseconds($SettleMs)
    while ((Get-Date) -lt $deadline) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }

    $script:result = $tb.Text
    $form.Close()
})

[void]$form.ShowDialog()

Write-Host "  上屏结果:"
if ([string]::IsNullOrEmpty($script:result)) {
    Write-Host "    （空 —— 没有内容上屏）"
} else {
    ($script:result -split "`r?`n") | ForEach-Object { Write-Host "    $_" }
}
