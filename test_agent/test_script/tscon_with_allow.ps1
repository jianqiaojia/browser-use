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

# 2. 获取当前 RDP Session 的分辨率
Write-Host "[Step 2] 获取当前 RDP Session 的分辨率..."
Add-Type -AssemblyName System.Windows.Forms
$currentScreen = [System.Windows.Forms.Screen]::PrimaryScreen
$currentWidth = $currentScreen.Bounds.Width
$currentHeight = $currentScreen.Bounds.Height
Write-Host "  当前分辨率: ${currentWidth}x${currentHeight}" -ForegroundColor Cyan

Write-Host ""

# 3. 获取当前 RDP Session ID
Write-Host "[Step 3] 获取当前 RDP Session ID..."
$sessionOutput = query session
$currentSession = $sessionOutput | Where-Object { $_ -match '>' }

if ($currentSession) {
    # 解析 Session ID（格式可能是 "rdp-tcp#0" 或数字）
    if ($currentSession -match '>\s*(\S+)\s+\S+\s+(\d+)\s+Active') {
        $sessionName = $matches[1]
        $sessionId = $matches[2]
        Write-Host "  当前 RDP Session: $sessionName (ID: $sessionId)" -ForegroundColor Cyan

        Write-Host ""
        Write-Host "[Step 4] 执行 tscon 切换到 Console Session..."
        Write-Host "  命令: tscon $sessionId /dest:console"
        Write-Host "  警告: RDP 连接即将断开！" -ForegroundColor Yellow
        Write-Host ""

        # 执行 tscon
        tscon $sessionId /dest:console

        # 等待会话切换完成
        Start-Sleep -Seconds 5

        Write-Host "[Step 5] 设置 Console Session 分辨率为 ${currentWidth}x${currentHeight}..."

        # 定义 ChangeDisplaySettings API
        Add-Type @"
        using System;
        using System.Runtime.InteropServices;

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
        public struct DEVMODE {
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string dmDeviceName;
            public short dmSpecVersion;
            public short dmDriverVersion;
            public short dmSize;
            public short dmDriverExtra;
            public int dmFields;
            public int dmPositionX;
            public int dmPositionY;
            public int dmDisplayOrientation;
            public int dmDisplayFixedOutput;
            public short dmColor;
            public short dmDuplex;
            public short dmYResolution;
            public short dmTTOption;
            public short dmCollate;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string dmFormName;
            public short dmLogPixels;
            public int dmBitsPerPel;
            public int dmPelsWidth;
            public int dmPelsHeight;
            public int dmDisplayFlags;
            public int dmDisplayFrequency;
            public int dmICMMethod;
            public int dmICMIntent;
            public int dmMediaType;
            public int dmDitherType;
            public int dmReserved1;
            public int dmReserved2;
            public int dmPanningWidth;
            public int dmPanningHeight;
        }

        public class DisplayAPI {
            [DllImport("user32.dll")]
            public static extern int ChangeDisplaySettings(ref DEVMODE devMode, int flags);

            public const int CDS_UPDATEREGISTRY = 0x01;
            public const int CDS_TEST = 0x02;
            public const int DISP_CHANGE_SUCCESSFUL = 0;
            public const int DISP_CHANGE_RESTART = 1;
            public const int DISP_CHANGE_FAILED = -1;
            public const int DM_PELSWIDTH = 0x80000;
            public const int DM_PELSHEIGHT = 0x100000;
        }
"@

        try {
            $devMode = New-Object DEVMODE
            $devMode.dmSize = [Runtime.InteropServices.Marshal]::SizeOf($devMode)
            $devMode.dmPelsWidth = $currentWidth
            $devMode.dmPelsHeight = $currentHeight
            $devMode.dmFields = [DisplayAPI]::DM_PELSWIDTH -bor [DisplayAPI]::DM_PELSHEIGHT

            $result = [DisplayAPI]::ChangeDisplaySettings([ref]$devMode, 0)

            if ($result -eq [DisplayAPI]::DISP_CHANGE_SUCCESSFUL) {
                Write-Host "  ✅ Console 分辨率已设置为 ${currentWidth}x${currentHeight}" -ForegroundColor Green
            } elseif ($result -eq [DisplayAPI]::DISP_CHANGE_RESTART) {
                Write-Host "  ⚠️  分辨率更改需要重启系统" -ForegroundColor Yellow
            } else {
                Write-Host "  ❌ 分辨率更改失败 (错误码: $result)" -ForegroundColor Red
            }
        } catch {
            Write-Host "  ❌ 设置分辨率时出错: $_" -ForegroundColor Red
        }

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
