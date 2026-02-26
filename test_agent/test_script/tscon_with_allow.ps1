# tscon 辅助脚本 - 自动授权 Python 进程设置前台窗口权限
# 用法: .\tscon_with_allow.ps1 -PythonPid <pid>
# 示例: .\tscon_with_allow.ps1 -PythonPid 12345

param(
    [Parameter(Mandatory=$true, HelpMessage="Python 进程的 PID")]
    [int]$PythonPid
)

# ============================================================================
# 日志函数
# ============================================================================

$LogFile = "$env:TEMP\tscon_with_allow.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"
    Add-Content -Path $LogFile -Value $logMessage -Encoding UTF8
}

# ============================================================================
# 分辨率设置函数
# ============================================================================

function Set-ConsoleResolution {
    param(
        [int]$TargetWidth,
        [int]$TargetHeight
    )

    Write-Host "`n[分辨率设置] 开始设置 Console 分辨率为 ${TargetWidth}x${TargetHeight}..." -ForegroundColor Cyan
    Write-Log "开始设置分辨率: ${TargetWidth}x${TargetHeight}"

    # 检查当前分辨率
    Add-Type -AssemblyName System.Windows.Forms
    $currentScreen = [System.Windows.Forms.Screen]::PrimaryScreen
    $logicalWidth = $currentScreen.Bounds.Width
    $logicalHeight = $currentScreen.Bounds.Height

    Write-Log "逻辑分辨率: ${logicalWidth}x${logicalHeight}"
    Write-Host "  逻辑分辨率: ${logicalWidth}x${logicalHeight}" -ForegroundColor Yellow

    # 使用 Python + pyautogui 检测实际物理分辨率
    $pythonCheck = python -c "import pyautogui; size = pyautogui.size(); print(f'{size.width}x{size.height}')" 2>$null
    if ($pythonCheck -match '(\d+)x(\d+)') {
        $physicalWidth = [int]$matches[1]
        $physicalHeight = [int]$matches[2]
        Write-Log "物理分辨率: ${physicalWidth}x${physicalHeight}"
        Write-Host "  物理分辨率: ${physicalWidth}x${physicalHeight}" -ForegroundColor Yellow
    } else {
        Write-Log "⚠️  无法检测物理分辨率，使用逻辑分辨率"
        $physicalWidth = $logicalWidth
        $physicalHeight = $logicalHeight
    }

    # 检查是否已经是目标分辨率
    if ($physicalWidth -eq $TargetWidth -and $physicalHeight -eq $TargetHeight) {
        Write-Host "  ✅ 物理分辨率已经是目标值，无需更改" -ForegroundColor Green
        Write-Log "✅ 分辨率已经是目标值"
        return $true
    }

    Write-Log "需要更改分辨率: ${physicalWidth}x${physicalHeight} -> ${TargetWidth}x${TargetHeight}"

    # 定义 Windows Display API
    Add-Type @'
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
    public static extern int EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);

    [DllImport("user32.dll")]
    public static extern int ChangeDisplaySettings(ref DEVMODE devMode, int flags);

    public const int ENUM_CURRENT_SETTINGS = -1;
    public const int ENUM_REGISTRY_SETTINGS = -2;
    public const int CDS_UPDATEREGISTRY = 0x01;
    public const int CDS_TEST = 0x02;
    public const int DISP_CHANGE_SUCCESSFUL = 0;
    public const int DISP_CHANGE_RESTART = 1;
    public const int DISP_CHANGE_FAILED = -1;
    public const int DM_PELSWIDTH = 0x80000;
    public const int DM_PELSHEIGHT = 0x100000;
    public const int DM_BITSPERPEL = 0x40000;
    public const int DM_DISPLAYFREQUENCY = 0x400000;
}
'@

    try {
        # 枚举所有支持的显示模式
        Write-Log "枚举显示器支持的所有分辨率..."
        Write-Host "  枚举显示器支持的所有分辨率..." -ForegroundColor Cyan

        $supportedModes = @()
        $modeNum = 0

        while ($true) {
            $devMode = New-Object DEVMODE
            $devMode.dmSize = [Runtime.InteropServices.Marshal]::SizeOf($devMode)

            $result = [DisplayAPI]::EnumDisplaySettings($null, $modeNum, [ref]$devMode)
            if ($result -eq 0) { break }

            $supportedModes += @{
                Width = $devMode.dmPelsWidth
                Height = $devMode.dmPelsHeight
                BitsPerPel = $devMode.dmBitsPerPel
                Frequency = $devMode.dmDisplayFrequency
            }

            $modeNum++
        }

        Write-Log "找到 $($supportedModes.Count) 个显示模式"
        Write-Host "  找到 $($supportedModes.Count) 个显示模式" -ForegroundColor Green

        # 查找完全匹配的模式
        $exactMatch = $supportedModes | Where-Object { $_.Width -eq $TargetWidth -and $_.Height -eq $TargetHeight } | Select-Object -First 1

        if ($exactMatch) {
            Write-Log "✅ 找到完全匹配的模式: $($exactMatch.Width)x$($exactMatch.Height) @ $($exactMatch.Frequency)Hz"
            Write-Host "  ✅ 找到完全匹配: $($exactMatch.Width)x$($exactMatch.Height) @ $($exactMatch.Frequency)Hz" -ForegroundColor Green
            $targetMode = $exactMatch
        } else {
            # 查找最接近的模式（按分辨率面积排序）
            Write-Log "⚠️  未找到完全匹配，查找最接近的模式..."
            Write-Host "  ⚠️  未找到完全匹配，查找最接近的模式..." -ForegroundColor Yellow

            $targetArea = $TargetWidth * $TargetHeight
            $closestMode = $supportedModes | ForEach-Object {
                $area = $_.Width * $_.Height
                $diff = [Math]::Abs($area - $targetArea)
                [PSCustomObject]@{
                    Mode = $_
                    Diff = $diff
                }
            } | Sort-Object Diff | Select-Object -First 1

            if ($closestMode) {
                $targetMode = $closestMode.Mode
                Write-Log "找到最接近的模式: $($targetMode.Width)x$($targetMode.Height) @ $($targetMode.Frequency)Hz"
                Write-Host "  找到最接近的模式: $($targetMode.Width)x$($targetMode.Height) @ $($targetMode.Frequency)Hz" -ForegroundColor Cyan
            } else {
                Write-Host "  ❌ 无法找到合适的显示模式" -ForegroundColor Red
                Write-Log "❌ 无法找到合适的显示模式"
                return $false
            }
        }

        # 使用完整的 DEVMODE 结构设置分辨率
        $devMode = New-Object DEVMODE
        $devMode.dmSize = [Runtime.InteropServices.Marshal]::SizeOf($devMode)
        $devMode.dmPelsWidth = $targetMode.Width
        $devMode.dmPelsHeight = $targetMode.Height
        $devMode.dmBitsPerPel = $targetMode.BitsPerPel
        $devMode.dmDisplayFrequency = $targetMode.Frequency
        $devMode.dmFields = [DisplayAPI]::DM_PELSWIDTH -bor [DisplayAPI]::DM_PELSHEIGHT -bor [DisplayAPI]::DM_BITSPERPEL -bor [DisplayAPI]::DM_DISPLAYFREQUENCY

        Write-Log "DEVMODE 结构体已创建"
        Write-Log "  dmPelsWidth: $($devMode.dmPelsWidth), dmPelsHeight: $($devMode.dmPelsHeight)"
        Write-Log "  dmBitsPerPel: $($devMode.dmBitsPerPel), dmDisplayFrequency: $($devMode.dmDisplayFrequency)"

        Write-Log "调用 ChangeDisplaySettings..."
        Write-Host "  正在应用分辨率设置..." -ForegroundColor Cyan
        $result = [DisplayAPI]::ChangeDisplaySettings([ref]$devMode, 0)

        Write-Log "ChangeDisplaySettings 返回: $result"

        if ($result -eq [DisplayAPI]::DISP_CHANGE_SUCCESSFUL) {
            Write-Host "  ✅ Console 分辨率已成功设置为 $($devMode.dmPelsWidth)x$($devMode.dmPelsHeight)" -ForegroundColor Green
            Write-Log "✅ 分辨率设置成功"

            # 验证实际物理分辨率
            Start-Sleep -Seconds 1
            $verifyCheck = python -c "import pyautogui; size = pyautogui.size(); print(f'{size.width}x{size.height}')" 2>$null
            if ($verifyCheck) {
                Write-Log "验证物理分辨率: $verifyCheck"
                Write-Host "  验证物理分辨率: $verifyCheck" -ForegroundColor Green
            }
            return $true
        } elseif ($result -eq [DisplayAPI]::DISP_CHANGE_RESTART) {
            Write-Host "  ⚠️  分辨率更改需要重启系统" -ForegroundColor Yellow
            Write-Log "⚠️  需要重启系统"
            return $false
        } else {
            Write-Host "  ❌ 分辨率更改失败 (错误码: $result)" -ForegroundColor Red
            Write-Log "❌ 分辨率更改失败 (错误码: $result)"
            return $false
        }
    } catch {
        Write-Host "  ❌ 设置分辨率时出错: $_" -ForegroundColor Red
        Write-Log "❌ 异常: $_"
        return $false
    }
}

# ============================================================================
# 主流程
# ============================================================================

Write-Host "=" * 80
Write-Host "tscon 辅助脚本 - 带 AllowSetForegroundWindow"
Write-Host "=" * 80
Write-Host ""

Write-Log "=========================================="
Write-Log "脚本开始执行"
Write-Log "Python PID: $PythonPid"

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
        Write-Log "AllowSetForegroundWindow 成功"
    } else {
        Write-Host "  ⚠️  AllowSetForegroundWindow 返回 False" -ForegroundColor Yellow
        Write-Log "AllowSetForegroundWindow 返回 False"
    }
} catch {
    Write-Host "  ❌ AllowSetForegroundWindow 失败: $_" -ForegroundColor Red
    Write-Log "AllowSetForegroundWindow 失败: $_"
}

Write-Host ""

# 2. 获取当前 RDP Session 的分辨率
Write-Host "[Step 2] 获取当前 RDP Session 的分辨率..."
Add-Type -AssemblyName System.Windows.Forms
$currentScreen = [System.Windows.Forms.Screen]::PrimaryScreen
$currentWidth = $currentScreen.Bounds.Width
$currentHeight = $currentScreen.Bounds.Height
Write-Host "  当前分辨率: ${currentWidth}x${currentHeight}" -ForegroundColor Cyan
Write-Log "RDP Session 分辨率: ${currentWidth}x${currentHeight}"

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
        Write-Log "当前 RDP Session: $sessionName (ID: $sessionId)"

        Write-Host ""
        Write-Host "[Step 4] 执行 tscon 切换到 Console Session..."
        Write-Host "  命令: tscon $sessionId /dest:console"
        Write-Host "  警告: RDP 连接即将断开！" -ForegroundColor Yellow
        Write-Host "  提示: 切换后将等待 20 秒，然后自动设置分辨率为 ${currentWidth}x${currentHeight}" -ForegroundColor Cyan
        Write-Host "  提示: 查看执行日志: $LogFile" -ForegroundColor Cyan
        Write-Host ""

        Start-Sleep -Seconds 2

        Write-Log "执行 tscon $sessionId /dest:console"

        # 执行 tscon
        tscon $sessionId /dest:console

        # tscon 执行后，当前 PowerShell 进程会继续在 Console Session 中运行
        Write-Log "tscon 已执行，当前进程已在 Console Session 中"
        Write-Host "`n[Step 5] tscon 已执行，等待 Console Session 稳定..." -ForegroundColor Cyan

        # 等待 20 秒让 Console Session 稳定
        for ($i = 20; $i -gt 0; $i--) {
            Write-Host "  倒计时: $i 秒" -NoNewline
            Start-Sleep -Seconds 1
            Write-Host "`r" -NoNewline
        }
        Write-Host "  等待完成                    "
        Write-Log "等待 20 秒完成"

        # 直接执行分辨率设置
        Write-Host ""
        Write-Host "[Step 6] 设置 Console Session 分辨率..."
        $success = Set-ConsoleResolution -TargetWidth $currentWidth -TargetHeight $currentHeight

        if ($success) {
            Write-Host "`n✅ 脚本执行完成！" -ForegroundColor Green
            Write-Log "脚本执行成功"
        } else {
            Write-Host "`n⚠️  脚本执行完成，但分辨率设置可能失败" -ForegroundColor Yellow
            Write-Log "脚本执行完成，但分辨率设置失败"
        }

        Write-Log "=========================================="

    } else {
        Write-Host "  ❌ 无法解析 Session ID，请手动执行 tscon" -ForegroundColor Red
        Write-Host "  当前会话信息:"
        Write-Host $currentSession
        Write-Log "无法解析 Session ID"
    }
} else {
    Write-Host "  ❌ 未找到活动的 RDP Session" -ForegroundColor Red
    Write-Host "  所有会话:"
    Write-Host $sessionOutput
    Write-Log "未找到活动的 RDP Session"
}
