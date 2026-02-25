# tscon 辅助脚本 - 自动授权 Python 进程设置前台窗口权限
# 用法: .	scon_with_allow.ps1 -PythonPid <pid>
# 示例: .	scon_with_allow.ps1 -PythonPid 12345

param(
    [Parameter(Mandatory=$true, HelpMessage="Python 进程的 PID")]
    [int]$PythonPid
)

Write-Host "=" * 80
Write-Host "tscon 辅助脚本 - 带 AllowSetForegroundWindow"
Write-Host "=" * 80
Write-Host ""

# 1. 允许 Python 进程设置前台窗口
Write-Host "[Step 1] 允许 Python 进程设置前台窗口..."
Write-Host "  Python PID: $PythonPid"

Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class WinAPI {
        [DllImport("user32.dll")]
        public static extern bool AllowSetForegroundWindow(int dwProcessId);
    }
"@

try {
    $result = [WinAPI]::AllowSetForegroundWindow($PythonPid)
    if ($result) {
        Write-Host "  ✅ AllowSetForegroundWindow 成功" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  AllowSetForegroundWindow 返回 False" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ❌ AllowSetForegroundWindow 失败: $_" -ForegroundColor Red
}

Write-Host ""

# 2. 获取当前 RDP Session ID
Write-Host "[Step 2] 获取当前 RDP Session ID..."
$sessionOutput = query session
$currentSession = $sessionOutput | Where-Object { $_ -match '>' }

if ($currentSession) {
    # 解析 Session ID（格式可能是 "rdp-tcp#0" 或数字）
    if ($currentSession -match '>\s*(\S+)\s+\S+\s+(\d+)\s+Active') {
        $sessionName = $matches[1]
        $sessionId = $matches[2]
        Write-Host "  当前 RDP Session: $sessionName (ID: $sessionId)" -ForegroundColor Cyan

        Write-Host ""
        Write-Host "[Step 3] 执行 tscon 切换到 Console Session..."
        Write-Host "  命令: tscon $sessionId /dest:console"
        Write-Host "  警告: RDP 连接即将断开！" -ForegroundColor Yellow
        Write-Host ""

        # 执行 tscon
        tscon $sessionId /dest:console

    } else {
        Write-Host "  ❌ 无法解析 Session ID，请手动执行 tscon" -ForegroundColor Red
        Write-Host "  当前会话信息:"
        Write-Host $currentSession
    }
} else {
    Write-Host "  ❌ 未找到活动的 RDP Session" -ForegroundColor Red
    Write-Host "  所有会话:"
    Write-Host $sessionOutput
}
