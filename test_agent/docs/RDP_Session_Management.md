# RDP Session Management for Browser Automation

## 目录
1. [问题背景](#问题背景)
2. [tscon 解决方案](#tscon-解决方案)
3. [Desktop 绑定问题与新线程方案](#desktop-绑定问题与新线程方案)
4. [tscon 自动化脚本](#tscon-自动化脚本)
5. [Azure VM 无人值守方案](#azure-vm-无人值守方案)

---

## 问题背景

### RDP 最小化时的限制

当 RDP 窗口最小化或断开连接时，Windows 会：
- ❌ 挂起视频输出，停止渲染图形
- ❌ 限制窗口管理 API（焦点管理失效）
- ❌ 阻止线程输入附加操作（`AttachThreadInput()` 失败）
- ❌ Edge 自动填充弹窗不出现（Edge 要求窗口必须有焦点）

### 根本原因

**Windows 系统层面：** Window Station 在最小化时变为 inactive，不允许焦点管理操作。

**Edge 浏览器硬性要求：** `RenderWidgetHostView::HasFocus()` 必须返回 true，否则隐藏 Autofill Popup。

---

## tscon 解决方案

### 基本用法

```bash
# 在虚拟机内执行（需要管理员权限）
query session          # 查看当前 session id
tscon <session_id> /dest:console  # 切换到 console session
```

### 执行效果

- RDP 窗口立刻关闭，但用户不会注销
- 会话切换到 Console Session
- GUI 继续运行，DWM/win32k 继续刷新
- `GetCursorPos` 等 API 恢复正常

### 技术原理

**tscon 本质：** 把 RDP session 的 token 绑定到 console winstation。

**一旦成为 console：**
- Windows 认为"有物理显示器"
- 不再进入 RDP 抑制模式
- win32k 允许输入 API

### Session 切换稳定性

**注意：** tscon 执行后，需要等待 **15-30 秒** 让 Console Session 稳定。

切换期间会发生：
- WinStation 切换
- 桌面对象重新绑定
- DWM 重建
- 输入队列重置

**稳定时间参考：**
- tscon: 0.5~3 秒
- RDP reconnect: 1~5 秒
- 显卡模式切换: 最多 10 秒

---

## Desktop 绑定问题与新线程方案

### 核心问题

当脚本在 RDP Session 中启动，然后执行 tscon 切换到 Console Session 后：
- ✅ GUI 子系统继续运行
- ❌ **Python 主线程仍绑定到旧的 RDP Desktop**

**根本原因：**
- 线程在创建时会绑定到当前的 Desktop
- tscon 切换后，Input Desktop 改变，但已存在的线程不会自动重新绑定
- 线程创建窗口/hooks/COM 对象后，无法调用 `SetThreadDesktop()` 切换

### 解决方案：使用新线程

**关键发现：** 新创建的线程会自动绑定到当前的 Input Desktop！

```python
def bring_window_to_foreground() -> bool:
    success = [False]

    def _focus_worker():
        """工作线程 - 自动绑定到 Console Desktop"""
        # 1. 在新线程中重新初始化 UIA（自动绑定到当前 Input Desktop）
        uia = comtypes.client.CreateObject(...)

        # 2. 查找并置顶浏览器窗口
        edge_hwnd = find_edge_window()
        win32gui.SetWindowPos(edge_hwnd, win32con.HWND_TOP, ...)

        # 3. 设置前台窗口（在新线程中会成功）
        win32gui.SetForegroundWindow(edge_hwnd)
        success[0] = True

    # 创建新线程（自动绑定到 Console Desktop）
    worker = threading.Thread(target=_focus_worker)
    worker.start()
    worker.join(timeout=10)

    return success[0]
```

**代码实现要点：**
- ✅ 必须在新线程中重新初始化 UIA（不能复用主线程的对象）
- ✅ 调用 `SetWindowPos` (不带 SWP_NOACTIVATE)
- ✅ 调用 `SetForegroundWindow` (在新线程中会成功)

### 方案对比

| 方案 | GUI API 可用？ | 新线程 Desktop 绑定 | SetForegroundWindow | Popup 显示？ |
|------|---------------|--------------------|--------------------|-------------|
| RDP 最小化 | ❌ | N/A | ❌ | ❌ |
| RDP + tscon (主线程) | ✅ | ❌ 绑定旧 Desktop | ❌ | ❌ |
| **RDP + tscon (新线程)** | ✅ | ✅ 绑定 Console Desktop | ✅ | ✅ |
| Console Session 启动 | ✅ | ✅ 直接绑定 Console | ✅ | ✅ |

---

## tscon 自动化脚本

### 脚本功能

`tscon_helper.ps1` 自动化整个 tscon 流程：
1. 调用 `AllowSetForegroundWindow(PythonPid)` 授权 Python 进程
2. 自动检测 RDP Session ID
3. 执行 tscon 切换到 Console Session
4. 等待 20 秒让 Console Session 稳定
5. 自动设置 Console 分辨率为 RDP 的分辨率

### 使用方法

**在 Python 脚本中集成：**

```python
import os
import subprocess
from pathlib import Path

current_pid = os.getpid()
script_path = Path(__file__).parent.parent / "utils" / "tscon_helper.ps1"

# 以管理员权限执行脚本
powershell_cmd = [
    "powershell", "-Command",
    f'Start-Process powershell -ArgumentList \'-ExecutionPolicy Bypass -File "{script_path.absolute()}" -PythonPid {current_pid}\' -Verb RunAs'
]
subprocess.Popen(powershell_cmd)

# 等待 tscon 完成 + Console Session 稳定
await asyncio.sleep(35)
```

### 工作流程

```
1. Python 脚本启动（在 RDP Session 中）
2. 获取 Python PID，启动 PowerShell 脚本
3. 用户点击 UAC 提示的 "是"
4. PowerShell 执行：
   - AllowSetForegroundWindow(PythonPid)  ✅
   - query session → 检测 Session ID   ✅
   - tscon <id> /dest:console           ✅
   - 等待 20 秒稳定
   - 设置分辨率为 RDP 的分辨率
5. RDP 连接断开（预期行为）
6. Python 脚本在新线程中调用 bring_window_to_foreground()
7. SetForegroundWindow() 成功 → Popup 正常显示 ✅
```

---

## Azure VM 无人值守方案

### 问题背景

Azure 标准 VM（B/D/E 系列）默认：
- ❌ 没有物理显示器或虚拟 GPU
- ❌ Console Session 无法渲染图形界面
- ❌ DWM 可能不完全启动
- ❌ 浏览器检测不到显示设备而进入受限模式

### 方案对比

| 方案 | 成本 | 复杂度 | 无人值守 | Console 图形 | 自定义分辨率 | 推荐指数 |
|------|------|--------|---------|-------------|-------------|---------|
| **IddSampleDriver + tscon** | 低（标准 VM） | 中 | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| **NV 系列 VM** | 高（GPU VM ~5-10倍） | 低 | ✅ | ✅ | ✅ | ⭐⭐⭐ |
| 保持 RDP 连接 | 低 | 低 | ❌ | ✅ | ✅ | ⭐ |
| Headless 模式 | 低 | 低 | ✅ | ❌ | ✅ | ⭐⭐ |

### 推荐方案：IddSampleDriver + tscon

**IddSampleDriver** 是开源的 Windows 虚拟显示器驱动（Indirect Display Driver）：
- **项目地址**: https://github.com/roshkins/IddSampleDriver
- **作用**: 让 Windows 认为有真实显示器连接
- **成本**: 免费开源
- **性能开销**: CPU < 1%, 内存 < 50 MB

**安装后效果：**
```
Console Session
├─ 虚拟显示器激活 ✅
├─ DWM 完全启动 ✅
├─ 浏览器认为有显示器 ✅
├─ 可设置任意分辨率 ✅
└─ 自动化测试正常工作 ✅
```

### 完整部署流程

#### 1. 初始化 Azure VM（一次性）

创建 `init_azure_vm_for_automation.ps1`：

```powershell
# 启用测试签名模式
bcdedit /set testsigning on

# 下载并安装 IddSampleDriver
$driverUrl = "https://github.com/roshkins/IddSampleDriver/releases/latest/download/IddSampleDriver.zip"
Invoke-WebRequest -Uri $driverUrl -OutFile "$env:TEMP\IddSampleDriver.zip"
Expand-Archive -Path "$env:TEMP\IddSampleDriver.zip" -DestinationPath "$env:TEMP\IddSampleDriver"
$infPath = Get-ChildItem -Path "$env:TEMP\IddSampleDriver" -Filter "*.inf" -Recurse | Select-Object -First 1
pnputil /add-driver $infPath.FullName /install

# 配置电源计划（防止休眠）
powercfg /change monitor-timeout-ac 0
powercfg /change standby-timeout-ac 0

# 重启 VM 使驱动生效
Restart-Computer -Force
```

#### 2. 验证虚拟显示器

```powershell
# 检查虚拟显示器设备
Get-WmiObject -Class Win32_VideoController | Format-Table Name, Status, VideoModeDescription

# 应该看到：
# IddSampleDriver Device  OK  1920 x 1080 x 4294967296 colors  ← 虚拟显示器
```

#### 3. 配置测试启动方式

**选项 A：完全自动（推荐用于 CI/CD）**

```powershell
# 创建计划任务：系统启动时自动运行测试
$action = New-ScheduledTaskAction -Execute "python.exe" -Argument "C:\path\to\test_script.py"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName "BrowserAutomationTest" -Action $action -Trigger $trigger -Principal $principal
```

**选项 B：手动触发 + tscon（适合调试）**

使用现有的 `tscon_helper.ps1` 脚本（见上一节）。

#### 4. 更新 tscon 脚本添加虚拟显示器检测

在 `tscon_helper.ps1` 中添加：

```powershell
# 验证虚拟显示器状态
$virtualDisplay = Get-WmiObject -Class Win32_VideoController | Where-Object {
    $_.Name -like "*IddSample*" -or $_.Name -like "*Indirect Display*"
}

if ($virtualDisplay) {
    Write-Host "✅ 虚拟显示器已加载: $($virtualDisplay.Name)"
} else {
    Write-Host "⚠️  未检测到虚拟显示器，请先运行 init_azure_vm_for_automation.ps1"
}
```

### Azure VM 部署总结

```
1. 创建 Azure VM（标准 B/D/E 系列即可，无需 GPU VM）
2. RDP 连接到 VM
3. 运行 init_azure_vm_for_automation.ps1
   - 启用测试签名
   - 安装 IddSampleDriver
   - 配置电源计划
4. 重启 VM（使驱动生效）
5. 验证虚拟显示器状态
6. 部署测试代码 + tscon_helper.ps1
7. 选择启动方式：
   - 选项 A: 计划任务（完全自动）
   - 选项 B: RDP 触发 → tscon → 断开
8. 测试在 Console Session + 虚拟显示器环境中运行 ✅
```

### NV 系列 VM（可选）

如果预算充足，可选择 NV 系列 VM：
- **型号**: NV6/NV12/NV24（配备 NVIDIA Tesla M60 GPU）
- **优势**: 直接有虚拟 GPU 和显示器，无需安装 IddSampleDriver
- **缺点**: 成本高（比标准 VM 贵 5-10 倍，~$1.14-4.56/小时）
- **适用场景**: GPU 加速计算、高质量视频编码、GPU 密集型 Web 应用

**对于普通浏览器自动化测试，IddSampleDriver + 标准 VM 足够。**

---

## 常见问题

### Q1: 为什么不用 Headless 模式？
**A:** Headless 模式检测不到显示器，某些功能（如 Autofill Popup）会被禁用，且截图调试困难。

### Q2: 为什么需要 AllowSetForegroundWindow？
**A:** Windows 默认不允许后台进程设置前台窗口，必须由前台进程（PowerShell）授权。

### Q3: tscon 后为什么要等待 30 秒？
**A:** Console Session 切换需要时间稳定（Desktop 绑定、DWM 初始化等）。

### Q4: IddSampleDriver 需要定期维护吗？
**A:** 不需要。一次安装永久有效，Windows 更新不会移除驱动，VM 重启后自动加载。

### Q5: 两台 VM 方案（VM A 连接 VM B，然后断开）为什么不行？
**A:** VM A 断开后，VM B 的 RDP Session 变成 Disconnected 状态，和 RDP 最小化限制相同（Window Station 变为 inactive，GUI API 受限）。除非在 VM B 里执行 tscon 切换到 Console Session。

---

## 文件位置

- **Azure 初始化脚本**: `test_agent/test_script/init_azure_vm_for_automation.ps1`
- **tscon 辅助脚本**: `test_agent/utils/tscon_helper.ps1`
- **焦点设置实现**: `test_agent/custom_actions/cdp_click.py` - `bring_window_to_foreground()`
