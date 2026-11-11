# test_ime_vk.ps1 —— 用真实扫描码 + SendInput 测试输入法选字
#
# 为什么不用 SendKeys：
#   SendWait 走 JournalHook，窗口一多就经常打不进目标窗口（截图里连字母都没有）。
#
# 为什么 keybd_event 扫 0 也不行：
#   扫描码填 0 时，输入法拿不到「物理键位」，转不出字符，字母根本进不了 composition。
#   必须用 MapVirtualKey(vk, 0) 取真实扫描码。
#
# 用法：
#   pwsh -File test_ime_vk.ps1 -Seq "y,a,2"          # 打 ya 再按 2
#   pwsh -File test_ime_vk.ps1 -Seq "n,i,h,a,o,1"

param(
    [string]$Seq = "y,a,2",
    [int]$GapMs = 250,
    [int]$SettleMs = 1800,
    [string]$ShotPath = ""
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;

public class Inp {
    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT {
        public uint type;
        public KEYBDINPUT ki;
        public ulong pad;
    }

    [DllImport("user32.dll", SetLastError=true)]
    public static extern uint SendInput(uint n, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll")]
    public static extern uint MapVirtualKey(uint uCode, uint uMapType);

    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

    public static bool ForceForeground(IntPtr hwnd) {
        uint fgPid;
        uint fgThread = GetWindowThreadProcessId(GetForegroundWindow(), out fgPid);
        uint myThread = GetCurrentThreadId();
        bool attached = false;
        if (fgThread != myThread) attached = AttachThreadInput(myThread, fgThread, true);
        BringWindowToTop(hwnd);
        bool ok = SetForegroundWindow(hwnd);
        if (attached) AttachThreadInput(myThread, fgThread, false);
        return ok;
    }

    // 真实敲键：VK + 扫描码
    public static uint Tap(byte vk) {
        INPUT[] arr = new INPUT[2];

        // 只给 wVk，wScan 留 0：同时给两者时 Windows 会按扫描码解析，
        // 数字键和字母键的扫描码规则不同，会导致数字键失效。
        arr[0].type = 1;
        arr[0].ki.wVk = vk;
        arr[0].ki.wScan = 0;
        arr[0].ki.dwFlags = 0;                 // KEYDOWN

        arr[1].type = 1;
        arr[1].ki.wVk = vk;
        arr[1].ki.wScan = 0;
        arr[1].ki.dwFlags = 2;                 // KEYUP

        return SendInput(2, arr, Marshal.SizeOf(typeof(INPUT)));
    }
}
"@

$form = New-Object System.Windows.Forms.Form
$form.Text = "IME Input Test"
$form.Size = New-Object System.Drawing.Size(720, 240)
$form.StartPosition = "CenterScreen"
$form.TopMost = $true

$tb = New-Object System.Windows.Forms.TextBox
$tb.Multiline = $true
$tb.Dock = "Fill"
$tb.Font = New-Object System.Drawing.Font("Microsoft YaHei", 14)
$form.Controls.Add($tb)

$form.Add_Shown({
    $form.Activate()
    [void][Inp]::ForceForeground($form.Handle)
    $tb.Focus()
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 800
    [System.Windows.Forms.Application]::DoEvents()

    $fg = [Inp]::GetForegroundWindow()
    Write-Host "  焦点: $(if($fg -eq $form.Handle){'OK'}else{"错 ($fg vs $($form.Handle))"})"

    foreach ($tok in $Seq.Split(',')) {
        $t = $tok.Trim()
        if ($t -eq "") { continue }

        $vk = 0
        if ($t.Length -eq 1 -and $t -match '^[A-Za-z]$') {
            $vk = [byte]([char]([string]$t).ToUpper())
        } elseif ($t.Length -eq 1 -and $t -match '^[0-9]$') {
            $vk = [byte](0x30 + [int]$t)
        } elseif ($t -match '^0x([0-9A-Fa-f]{2})$') {
            $vk = [Convert]::ToByte($Matches[1], 16)
        } else {
            Write-Host "  跳过无法识别的键: $t"
            continue
        }

        $sent = [Inp]::Tap([byte]$vk)
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds $GapMs
    }

    $deadline = (Get-Date).AddMilliseconds($SettleMs)
    while ((Get-Date) -lt $deadline) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }

    $script:result = $tb.Text

    if ($ShotPath) {
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
        $bmp.Save($ShotPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $g.Dispose(); $bmp.Dispose()
        Write-Host "  截图已存: $ShotPath"
    }

    $form.Close()
})

[void]$form.ShowDialog()

Write-Host "  上屏结果:"
if ([string]::IsNullOrEmpty($script:result)) {
    Write-Host "    （空 —— 没有内容上屏）"
} else {
    ($script:result -split "`r?`n") | ForEach-Object { Write-Host "    $_" }
}
