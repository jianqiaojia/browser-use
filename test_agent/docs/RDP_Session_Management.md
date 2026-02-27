# RDP Session Management for Browser Automation

## 目录
1. [问题背景](#问题背景)
2. [tscon 解决方案](#tscon-解决方案)
3. [Desktop 绑定问题与新线程方案](#desktop-绑定问题与新线程方案)
4. [tscon 自动化脚本](#tscon-自动化脚本)
5. [Azure VM 无人值守方案](#azure-vm-无人值守方案)
6. [VM 显示分辨率管理](#vm-显示分辨率管理)

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

`tscon_worker.ps1` 自动化整个 tscon 流程：
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
script_path = Path(__file__).parent.parent / "utils" / "tscon_worker.ps1"

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

使用现有的 `tscon_worker.ps1` 脚本（见上一节）。

#### 4. 更新 tscon 脚本添加虚拟显示器检测

在 `tscon_worker.ps1` 中添加：

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
6. 部署测试代码 + tscon_worker.ps1
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

---

## VM 显示分辨率管理

### 核心问题：RDP Session 与 Console 分辨率隔离

在虚拟机中通过 RDP 连接时，存在显示路径隔离：

**RDP Session**:
- 使用虚拟显示驱动（RDPDD / Microsoft Remote Display Adapter）
- 分辨率由 RDP 客户端窗口大小和配置决定
- 与 Console Session 完全独立

**Console Session**:
- 使用 VM 的虚拟显卡驱动（Hyper-V Video / VMware SVGA）
- 分辨率取决于 hypervisor 和虚拟显卡配置
- 没有 active viewer 时可能 fallback 到 1024x768

**关键点**: 在 RDP Session 里调用 `EnumDisplaySettings()` / `GetSystemMetrics(SM_CXSCREEN)` 等 API 只能获取 RDP 虚拟显示器的分辨率，**无法直接获取 Console 的物理分辨率**。

### 如何获取 Console 分辨率？

理论上可以，但必须满足特定条件：

**✅ 方案 1：在 Console Session 里运行代码**

如果进程运行在 `WTSGetActiveConsoleSessionId()` 对应的 session 里：

```python
# 获取 Console session ID
console_session_id = win32ts.WTSGetActiveConsoleSessionId()

# 在 Console session 中运行时，才能获取真实 Console 分辨率
if current_session_id == console_session_id:
    # QueryDisplayConfig() 可以拿到真实 Console 显示信息
    ...
```

**✅ 方案 2：用服务 + CreateProcessAsUser 切到 Console**

这是企业软件的常用做法：

```
1. 在 Windows Service 里运行
2. 获取 Console session id (WTSGetActiveConsoleSessionId)
3. 用 CreateProcessAsUser 在 Console session 里启动 helper 进程
4. Helper 进程查询 Console 分辨率
5. 通过 IPC (Named Pipe / Shared Memory) 把分辨率回传给 Service
```

**示例架构**:

```
Service (Session 0)
    ↓ CreateProcessAsUser
Helper.exe (Console Session)
    ↓ QueryDisplayConfig()
    ↓ Named Pipe
Service 接收分辨率数据
```

**❌ 在 RDP Session 里直接读 Console？**

正常权限下做不到，因为：
- Session 隔离机制
- Win32k 显示对象隔离
- RDP 使用独立 display driver

**⚠️ 特殊情况：Console 无人登录**

如果：
- Console 当前没人登录
- 或 VM console viewer 被断开

那么：
- **根本没有"物理分辨率"**
- 很多 VM 会 fallback 到 1024x768 或驱动默认值

**获取 Console 分辨率总结**:

| 场景 | 能否获取 Console 分辨率 |
|------|----------------------|
| RDP Session 内直接查询 | ❌ 不能 |
| Console Session 内运行 | ✅ 可以 |
| Service + CreateProcessAsUser 切到 Console | ✅ 可以 |
| 纯 VM 无物理显示器 | ⚠️ 取决于虚拟显卡 |

### tscon 切换后的分辨率行为

当执行 `tscon <id> /dest:console` 后：

```
1. RDP Session 断开
2. RDP 虚拟显示驱动卸载
3. 系统重新枚举 Console 显示设备
4. 切换到 VM 虚拟显卡
```

**可能的结果**:

| 场景 | 是否 fallback 到 1024x768 |
|------|------------------------|
| VM 有 active console viewer（VMConnect / VMware Console） | ❌ 通常不会 |
| VM 无 active console viewer | ✅ 很可能 |
| VMware + VMware Tools 正常 | ❌ 一般不会 |
| Hyper-V 无 VMConnect 连接 | ✅ 经常会 |
| QEMU/KVM SPICE viewer 断开 | ✅ 大概率 |

**为什么会 fallback**:

当 VM 没有 active console viewer 时：
- 虚拟显卡没有报告可用的显示模式（EDID 信息缺失）
- Windows 认为没有可用的显示设备
- 加载 Basic Display Driver 或使用 fallback mode
- 默认回退到 1024x768 或 800x600

**即使手动设置分辨率也可能失败**，因为驱动报告的 mode list 可能只包含默认分辨率。

### 不同虚拟化平台的行为差异

**🟦 Hyper-V**

如果 Enhanced Session Mode 关闭 或 VMConnect 未连接：
- 👉 常 fallback 到 1024x768

但如果 VMConnect 正在连接：
- 👉 会按窗口大小动态调整分辨率

**🟩 VMware Workstation/ESXi**

只要 VMware Tools 正常运行：
- Console 分辨率通常可自定义
- 不一定会 fallback
- 支持动态分辨率调整

**🟥 QEMU + SPICE**

如果 SPICE viewer 断开：
- 没有 QXL/virtio-gpu active surface
- 👉 大概率 fallback 到默认分辨率

### 为什么手动设置分辨率也不生效？

**情况 A：VM 显卡支持多分辨率**（例如 VMware SVGA / Hyper-V Video）

✔ 可以设置任意分辨率
✔ 分辨率会保留

**情况 B：当前没有 active console 输出**

例如：
- Hyper-V 没打开 VMConnect
- VMware 没打开 console viewer
- SPICE viewer 断开

此时：
- 显卡报告的 mode 可能只有 1024x768
- 你设置其他分辨率会失败（API 返回错误）
- 或设置成功但立即被 reset 回默认值

**底层机制**:

Windows 分辨率来自以下 API：
```
EnumDisplayDevices() - 枚举显示设备
EnumDisplaySettings() - 枚举支持的分辨率
QueryDisplayConfig() - 查询当前配置
```

这些依赖：
- WDDM 驱动
- 当前 active output
- EDID 或虚拟 EDID

当输出消失时：
- 驱动会回退到 safe mode
- 只报告最基本的分辨率

**重要提示**:

如果你：
1. 先在 RDP 设置 1920x1080
2. 然后 `tscon` 到 console

**分辨率不会继承**，因为：
- RDP 用的是独立 display stack
- Console 是另一套 display stack
- 两者不共享配置

### 解决方案：使用 IDD 虚拟显示驱动

**核心思路**: 创建一个永久在线的虚拟显示器，避免 Console Session 因缺少显示设备而 fallback。

### 避免 Fallback 的实战建议

**方案 1：保持 console viewer 打开**（最简单）

- Hyper-V: 保持 VMConnect 打开
- VMware: 保持 console 窗口打开
- QEMU: 保持 SPICE/VNC viewer 连接

**方案 2：安装正确的 VM 显卡驱动**

例如：
- VMware Tools（包含 VMware SVGA 驱动）
- Hyper-V Integration Services（包含 Hyper-V Video 驱动）
- virtio-gpu 驱动（for QEMU/KVM）

**方案 3：在 Console session 内强制设置分辨率**

使用 `ChangeDisplaySettingsEx()` API：

```python
import win32api
import win32con

# 设置 1920x1080 分辨率
devmode = win32api.EnumDisplaySettings(None, 0)
devmode.PelsWidth = 1920
devmode.PelsHeight = 1080
devmode.Fields = win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT

result = win32api.ChangeDisplaySettingsEx(None, devmode, win32con.CDS_UPDATEREGISTRY)
```

⚠️ **前提**: 驱动必须支持该 mode。

**方案 4：使用 IDD 虚拟显示驱动**（最稳定）

见下一节详细说明。

### IDD 虚拟显示驱动详解

### IDD 虚拟显示驱动详解

#### IDD (Indirect Display Driver) 原理

IDD 是 Windows 10+ 支持的 WDDM Indirect Display 架构：
- 创建一个虚拟显示输出（类似虚拟显示器）
- 由驱动声明支持的分辨率列表
- Windows 将其视为真实物理显示器

**对比正常 VM 显示路径**:

```
【没有 IDD】
RDP disconnect → Display stack reset → 无 active monitor
→ Basic Display Driver → 1024x768

【有 IDD】
RDP disconnect → IDD 虚拟显示器依然存在
→ Driver 报告支持的 mode → Console 分辨率保持
```

#### IDD 驱动关键实现

IDD 驱动需要实现以下回调函数声明支持的分辨率：

```cpp
EVT_IDD_CX_MONITOR_QUERY_TARGET_MODES MyQueryTargetModes
{
    // 声明支持的分辨率列表
    IDDCX_TARGET_MODE modes[] = {
        { 1920, 1080, 60 },
        { 2560, 1440, 60 },
        { 3840, 2160, 60 },
        // 可以添加任意自定义分辨率
    };

    return IddCxMonitorQueryTargetModes(...);
}
```

**效果**:
- `EnumDisplaySettings()` 会返回这些 mode
- Console Session 可以设置任意声明的分辨率
- 不会因为 RDP disconnect 或缺少 viewer 而 fallback

#### 为什么 IddSampleDriver 需要定制

微软提供的 `IddSampleDriver` 是示例代码，有以下限制：

❌ 只包含固定几个 mode
❌ 不支持热插拔
❌ 不支持动态调整
❌ 缺少生产级错误处理

**需要定制的内容**:

✅ 修改 mode list 支持所需的分辨率
✅ 处理 DXGI 帧传递（如果需要远程截图）
✅ 驱动签名（测试签名或 WHQL）
✅ 处理多 session 环境

#### IDD 方案优势

| 方案 | 可行性 | 复杂度 | 稳定性 | 适用场景 |
|------|--------|--------|--------|----------|
| `tscon` 到 Console | ⚠️ 会 fallback | 低 | 差 | 临时测试 |
| 保持 console viewer 打开 | ✅ 可用 | 低 | 中 | 开发调试 |
| VMware Tools + console | ✅ 可用 | 低 | 中-高 | VMware 环境 |
| **IDD 虚拟显示驱动** | ✅ 最彻底 | 高 | 高 | **生产环境** |

**真实应用案例**:
- 云桌面服务（AWS WorkSpaces / Azure Virtual Desktop）
- 远程自动化（UI 测试 / RPA）
- 图形渲染农场
- 无人值守系统

这些企业产品都使用 IDD 架构来：
- 创建永久在线的虚拟显示器
- 精确控制分辨率
- 避免 fallback

### 其他替代方案

如果不想开发内核驱动，可以考虑：

**方案 A: 安装 VM 增强工具**
- VMware Tools / Hyper-V Integration Services
- 保持一个最小化 console viewer 打开
- 分辨率不会 fallback

**方案 B: 虚拟 EDID 注入**
- 某些 hypervisor 支持注入虚拟 EDID
- 让 VM 认为有物理显示器连接
- 配置复杂度取决于 hypervisor

**方案 C: 使用 GPU VM**
- Azure NV 系列 / AWS G4 实例
- 直接提供虚拟 GPU 和显示器
- 成本高（比标准 VM 贵 5-10 倍）

### 总结

**问题根源**: RDP Session 和 Console Session 使用不同的显示驱动，分辨率独立管理。tscon 切换后，Console 缺少 active 显示设备时会 fallback。

**最佳方案**:
- **开发/调试环境**: 使用 VM 增强工具 + 保持 console viewer 打开
- **生产/自动化环境**: 部署 IDD 虚拟显示驱动（基于 IddSampleDriver 定制）

**当前项目**: 已使用 IddSampleDriver 解决 Azure VM Console Session 的分辨率问题（见上一节）。

### 针对不同自动化场景的建议

**场景 A：无人值守 UI 自动化 / 浏览器自动化**

最稳做法：
- 👉 不要使用 `tscon`（会 fallback）
- 👉 直接在 Console session 启动程序
- 👉 或使用 headless GPU driver（例如 IDD）

**场景 B：远程渲染 / 图形测试**

推荐方案：
- 部署 IDD 虚拟显示驱动
- 或使用 GPU VM（NV 系列 / G4 实例）

**场景 C：开发调试**

简单方案：
- 保持 console viewer 打开
- 或使用 VMware Tools / Hyper-V Integration Services

---

## 文件位置

- **Azure 初始化脚本**: `test_agent/test_script/init_azure_vm_for_automation.ps1`
- **tscon 辅助脚本**: `test_agent/utils/tscon_worker.ps1`
- **焦点设置实现**: `test_agent/custom_actions/cdp_click.py` - `bring_window_to_foreground()`
