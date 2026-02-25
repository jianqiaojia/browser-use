# RDP Session Management for Browser Automation

## 目录
1. [问题背景](#问题背景)
2. [根本原因分析](#根本原因分析)
3. [解决方案：tscon 命令](#解决方案tscon-命令)
4. [Session 切换的稳定性问题](#session-切换的稳定性问题)
5. [代码实现方案](#代码实现方案)

---

## 问题背景

在虚拟机环境中通过 RDP (Remote Desktop Protocol) 进行浏览器自动化时，存在以下问题：

### RDP 最小化时的限制

当 RDP 窗口最小化时，Windows 会：
- ❌ **挂起远程桌面会话的视频输出** - 停止渲染图形
- ❌ **限制窗口管理 API 访问** - 焦点管理失效
- ❌ **阻止线程输入附加操作** - `AttachThreadInput()` 返回错误
- ❌ **Edge 自动填充弹窗不出现** - Edge 要求窗口必须有焦点

---

## 根本原因分析

### 1. Windows 系统层面限制

```python
# RDP 最小化时，以下调用会失败：
win32process.AttachThreadInput(foreground_thread, current_thread, True)
# 错误: (87, 'AttachThreadInput', 'The parameter is incorrect.')
```

**原因：** Windows 认为远程会话的 Window Station 在最小化时不再活跃，不允许焦点管理操作。

### 2. Edge 浏览器硬性要求

```cpp
// Edge 源码 (Chromium 基于)
void AutofillPopupControllerImpl::ShowWalletECInlineExperience(
  // 关键检查：窗口是否有焦点
  if (auto* rwhv = web_contents_->GetRenderWidgetHostView();
      (!rwhv || !rwhv->HasFocus()) && IsRootPopup()) {
    Hide(SuggestionHidingReason::kNoFrameHasFocus);  // ❌ 没焦点就隐藏
    return;
  }

  // 只有窗口有焦点时，才会显示弹窗
  // ...
}
```

**原因：** Edge 设计上只在用户关注窗口时显示自动填充弹窗（安全和 UX 考虑）。

---

## 解决方案：tscon 命令

### 命令说明

```bash
tscon %sessionid% /dest:console
```

👉 此命令**必须在虚拟机内部执行**，不是在本地物理机执行。

### 正确使用步骤

#### ① 先通过 RDP 登录虚拟机

用 `mstsc` 正常连接。

#### ② 在虚拟机里查看当前 session id

在虚拟机的 CMD 里执行：

```bash
query session
```

你会看到类似：

```
 SESSIONNAME       USERNAME         ID  STATE
 rdp-tcp#1         user             2   Active
 console                               1   Conn
```

记住：👉 你当前 RDP 那一行的 **ID**（比如是 `2`）

#### ③ 在虚拟机里执行（需要管理员权限）

```bash
tscon 2 /dest:console
```

（把 `2` 换成你的 ID）

### 执行效果

**执行瞬间：**
- RDP 窗口会立刻关闭
- 但用户不会注销
- 会话被切换到 console
- GUI 继续运行
- 鼠标 / DWM / win32k 继续刷新

**之后：**
- 即使你不再连接 RDP
- `GetCursorPos` 也不会报错

### 为什么一定要在虚拟机里执行？

因为 `tscon` 操作的是：
- 远端 Windows 的 session manager
- WinStation 对象
- 本机 session 结构

本地机器无法操作远端 session。

### 常见问题

**如果提示：**
```
Access is denied
```

**原因：**
- 你不是管理员
- 或没有权限切换 session

**解决方法：** 👉 用管理员 CMD 执行

### 技术原理

**RDP 会话：**
```
Session X (RDP)
```

**Console 会话：**
```
Session 1 (Physical/Virtual display)
```

**tscon 本质是：**

把 RDP session 的 token 绑定到 console winstation。

**一旦成为 console：**
- Windows 认为"有物理显示器"
- 不再进入 RDP 抑制模式
- win32k 允许输入 API

这也是为什么 UI 自动化服务器都这么干。

### 验证方法

1️⃣ RDP 登录
2️⃣ 不执行 tscon → 最小化 mstsc → 看 GetCursorPos 是否报错
3️⃣ 执行 tscon → 再测试

如果 tscon 后问题消失，说明就是 session inactive 问题。

---

## Session 切换的稳定性问题

### 问题现象

你可能观察到：
- 执行 `tscon` 的瞬间会失败
- RDP 重新连接后的几秒内会失败

这其实是 **Windows 正常行为**。

### 本质原因：桌面正在切换

当你执行：
```bash
tscon X /dest:console
```

**Windows 内部会发生：**
1. WinStation 切换
2. 桌面对象重新绑定
3. DWM 重建
4. 输入队列重置
5. win32k 重建 cursor 状态

**在这段时间内：**
- 当前线程可能仍绑定旧 desktop
- 或 input desktop 暂时不存在
- 或 win32k 尚未完成 attach

**这时调用：**
```cpp
GetCursorPos → ERROR_ACCESS_DENIED
```

**原因：** 👉 当前线程暂时不在 active input desktop 上。

### 为什么 RDP 重新连接也会发生？

当你重新连接 RDP，Windows 会：
1. 从 console session 切回 RDP winstation
2. 创建新的 RDP Desktop
3. DWM 切换
4. 图形驱动模式切换（尤其虚拟机）

这个过程通常持续：🕒 **1~5 秒**

**期间：**
- 输入子系统未 ready
- `OpenInputDesktop` 可能失败
- `GetCursorPos` 可能失败

### 这不是 bug，是状态切换窗口

Windows 并没有保证：**在 session 切换期间 Win32 GUI API 一定可用。**

UI 自动化系统都会遇到这个问题。

### 稳定时间参考

在虚拟机里：

| 操作 | 不稳定时间 |
|------|-----------|
| tscon | 0.5~3 秒 |
| RDP reconnect | 1~5 秒 |
| 显卡模式切换 | 最多 10 秒 |

---

## 代码实现方案

### 方案 1：输入桌面稳定检测

不要直接调用 `GetCursorPos`。应该：

1️⃣ 先检测 input desktop 是否可用
2️⃣ 再调用

**示例代码：**

```c
BOOL WaitForInputDesktop(int timeoutMs)
{
    DWORD start = GetTickCount();
    while (GetTickCount() - start < timeoutMs)
    {
        HDESK hDesk = OpenInputDesktop(0, FALSE, GENERIC_READ);
        if (hDesk)
        {
            CloseDesktop(hDesk);
            return TRUE;
        }
        Sleep(100);
    }
    return FALSE;
}
```

**使用：**

```c
if (WaitForInputDesktop(5000))
{
    GetCursorPos(&pt);
}
```

### 方案 2：Attach 到当前 Input Desktop

在 GUI 程序中：

```c
HDESK hDesk = OpenInputDesktop(0, FALSE, GENERIC_ALL);
SetThreadDesktop(hDesk);
```

**注意：** ⚠ 线程创建窗口后不能再 `SetThreadDesktop`，否则会失败。

### 方案 3：Retry 机制（自动化服务器常用）

UI 自动化系统通常这样设计：

```c
while(true)
{
    if (!GetCursorPos(&pt))
    {
        if (GetLastError() == ERROR_ACCESS_DENIED)
        {
            Sleep(500);
            continue;
        }
    }

    break;
}
```

因为他们知道：**Session 切换时一定会短暂失败。**

### 方案 4：监听 Session 变化（企业级做法）

可以监听：
```c
WM_WTSSESSION_CHANGE
```

通过：
```c
WTSRegisterSessionNotification
```

等收到：
```c
WTS_SESSION_UNLOCK
```

再开始调用 GUI API。

这是企业级做法。

---

## 总结

### 问题本质

👉 是 Windows 图形子系统在 session 切换时的"短暂失联"。

### 解决方式

1. 等待 input desktop ready
2. 或 retry
3. 或监听 session change

### 排除的问题

你这个现象说明：
- ✅ 不是权限问题
- ✅ 不是 VBS / IUM
- ✅ 不是完整性等级
- ✅ 纯粹是 WinStation 切换窗口

---

## tscon 能否解决 Edge Autofill Popup 问题？

### 问题起源

Edge 源码中的关键检查（`autofill_popup_controller_impl_edge.cc` 第 593-597 行）：

```cpp
if (auto* rwhv = web_contents_->GetRenderWidgetHostView();
    (!rwhv || !rwhv->HasFocus()) && IsRootPopup()) {
  Hide(SuggestionHidingReason::kNoFrameHasFocus);
  return;
}
```

这个检查是：**RenderWidgetHostView 必须有焦点，否则隐藏 popup**。

### 焦点传递链路分析

我们追踪了完整的焦点传递路径：

```
Windows WM_ACTIVATE 消息
    ↓
HWNDMessageHandler::PostProcessActivateMessage()
    ↓
DesktopWindowTreeHostWin::HandleActivationChanged()
    ↓
DesktopNativeWidgetAura::HandleActivationChanged()
    ↓
ActivationClient 设置焦点
    ↓
Window::HasFocus() 检查 FocusClient
    ↓
RenderWidgetHostViewAura::HasFocus() 返回 window_->HasFocus()
    ↓
Edge Autofill 检查 rwhv->HasFocus()
```

### 核心问题：tscon 后的 Desktop 绑定问题

**问题：** 当脚本在 RDP Session 中启动，然后执行 tscon 切换到 Console Session 后：
- ✅ GUI 子系统继续运行（DWM、win32k 正常）
- ✅ `GetCursorPos` 等 API 可以正常工作
- ❌ **Python 主线程仍然绑定到旧的 RDP Desktop**

**根本原因：**
- Python 线程在创建时会绑定到当前的 Desktop (Window Station)
- 执行 tscon 后，Input Desktop 从 RDP Desktop 切换到 Console Desktop
- **但已存在的线程不会自动重新绑定到新 Desktop**
- 如果线程已经创建了窗口/hooks/COM 对象，无法调用 `SetThreadDesktop()` 切换（返回 error 170 "resource in use"）

### 解决方案：方案 B - 使用新线程处理 Desktop 切换

**关键发现（2024 年验证）：**

新创建的线程会自动绑定到当前的 Input Desktop！因此：

**方案 B - 在新线程中执行焦点设置：**

```python
def bring_window_to_foreground() -> bool:
    success = [False]

    def _focus_worker():
        """工作线程 - 自动绑定到 Console Desktop"""
        # 1. 在新线程中重新初始化 UIA
        #    新线程创建时会绑定到当前 Input Desktop (Console)
        uia = comtypes.client.CreateObject(...)

        # 2. 查找 Edge 浏览器窗口
        edge_hwnd = find_edge_window()

        # 3. SetWindowPos 置顶
        win32gui.SetWindowPos(edge_hwnd, win32con.HWND_TOP, ...)

        # 4. 尝试 AttachThreadInput (会失败 error 5，但不影响)
        try:
            win32process.AttachThreadInput(...)
        except Exception:
            pass  # 预期失败，忽略

        # 5. SetForegroundWindow (✅ 成功！)
        try:
            win32gui.SetForegroundWindow(edge_hwnd)
            success[0] = True  # ✅ 成功
        except Exception as e:
            success[0] = False

    # 创建新线程（自动绑定到 Console Desktop）
    worker = threading.Thread(target=_focus_worker)
    worker.start()
    worker.join(timeout=10)

    return success[0]
```

**测试结果（2024-02 验证）：**

```
[Focus] Creating new thread for focus setting (main thread ID: 45748)...
[Focus-NewThread] Thread started, ID: 110468  # ← 新线程
[Focus-NewThread] Found 4 Chrome-based windows
[Focus-NewThread] ✅ Found Edge browser window: ...
[Focus-NewThread] SetWindowPos (HWND_TOP, with activation)...
[Focus-NewThread] Attempting SetForegroundWindow...
[Focus-NewThread] ⚠️  AttachThreadInput(attach) failed: (5, 'Access is denied.')  # ← 预期失败
[Focus-NewThread] ✅ SetForegroundWindow succeeded!  # ← ✅ 成功！
[Focus] Worker thread completed, result: True
```

**结论：**
- ✅ **新线程自动绑定到 Console Desktop**
- ✅ **SetForegroundWindow 在新线程中成功**（即使 AttachThreadInput 失败）
- ✅ **Edge 的 HasFocus() 返回 true**
- ✅ **Autofill Popup 正常显示**

### 为什么 AttachThreadInput 失败但 SetForegroundWindow 成功？

**AttachThreadInput 失败的原因：**
- 前台窗口可能属于系统进程（console、explorer 等）
- Windows 安全机制不允许附加到系统进程的输入队列
- 即使以管理员身份运行 tscon，也会返回 error 5

**SetForegroundWindow 为什么仍能成功：**
- 在 Console Session 中，Windows 对前台窗口的限制较宽松
- **关键：新线程绑定到正确的 Desktop**，有权限操作同 Desktop 的窗口
- 不需要 AttachThreadInput 的帮助

**实测验证：**
- ✅ AttachThreadInput 失败 (error 5) → SetForegroundWindow 仍成功
- ✅ SetForegroundWindow 成功 → Edge HasFocus() 返回 true
- ✅ Popup 正常显示

### 方案对比

| 方案 | 脚本启动位置 | Desktop 绑定 | SetForegroundWindow | 是否需要控制台访问 |
|------|--------------|--------------|---------------------|-------------------|
| **方案 A** | Console Session | 主线程绑定 Console Desktop | ✅ 直接成功 | ❌ 需要物理/虚拟控制台 |
| **方案 B** | RDP Session | 新线程绑定 Console Desktop | ✅ 新线程中成功 | ✅ 不需要 |

### 推荐实现方案

**完整流程（方案 B）：**

```
1. 在 RDP Session 中启动脚本
    ↓
2. 脚本提示用户执行 tscon
    ↓
3. 用户执行: tscon <session_id> /dest:console
    （RDP 断开，但脚本继续运行）
    ↓
4. 脚本等待 15 秒让 Console Session 稳定
    ↓
5. 脚本创建新线程执行焦点设置
    （新线程自动绑定到 Console Desktop）
    ↓
6. 新线程中：
   - 重新初始化 UIA
   - 查找浏览器窗口
   - SetWindowPos 置顶
   - SetForegroundWindow (✅ 成功)
    ↓
7. 执行 CDP 点击
    ↓
8. Edge HasFocus() 返回 true
    ↓
9. Autofill Popup 显示 ✅
```

**代码实现要点：**
- ✅ 必须在新线程中重新初始化 UIA（不能复用主线程的 UIA 对象）
- ✅ 必须调用 `SetWindowPos` (不带 SWP_NOACTIVATE)
- ✅ 尝试调用 `AttachThreadInput` (失败是预期的，忽略错误)
- ✅ 调用 `SetForegroundWindow` (在新线程中会成功)

**参考实现：**
- `test_agent/custom_actions/cdp_click.py` - `bring_window_to_foreground()`
- `test_agent/test_script/test_cdp_attach_checkout_plan_b.py` - 完整测试脚本
- `test_agent/test_script/tscon_with_allow.ps1` - tscon 自动化脚本

### tscon 自动化脚本：AllowSetForegroundWindow 集成

**解决的核心问题：**

在 tscon 切换到 Console Session 后，Python 脚本需要调用 `SetForegroundWindow()` 将浏览器窗口设置为前台窗口。但 Windows 有严格的前台窗口限制：

- **限制原因**: 防止恶意程序强制抢占用户焦点
- **失败场景**: 当脚本不是当前前台进程时，`SetForegroundWindow()` 会静默失败
- **解决方案**: 使用 `AllowSetForegroundWindow(PID)` API 授权特定进程设置前台窗口

**自动化脚本实现：`tscon_with_allow.ps1`**

该脚本自动化整个 tscon 流程，包括：

1. **授权 Python 进程**：调用 `AllowSetForegroundWindow(PythonPid)` 授予权限
2. **自动检测 RDP Session ID**：使用 `query session` 自动识别当前 RDP 会话
3. **执行 tscon**：自动切换到 Console Session
4. **UTF-8 BOM 编码**：支持中文字符显示

**脚本用法：**

```powershell
# 在管理员 PowerShell 中执行
.\tscon_with_allow.ps1 -PythonPid 12345
```

**脚本参数：**
- `-PythonPid`: Python 脚本的进程 ID（必需），通过 `os.getpid()` 获取

**Python 集成示例：**

```python
import os
import subprocess
from pathlib import Path

# 获取当前 Python 进程 PID
current_pid = os.getpid()

# PowerShell 脚本路径
TSCON_SCRIPT_PATH = Path(__file__).parent / "tscon_with_allow.ps1"

# 检查脚本是否存在
if not TSCON_SCRIPT_PATH.exists():
    print(f"错误: tscon 辅助脚本不存在: {TSCON_SCRIPT_PATH}")
    return

# 使用 PowerShell Start-Process 以管理员权限执行脚本
powershell_cmd = [
    "powershell",
    "-Command",
    f'Start-Process powershell -ArgumentList \'-ExecutionPolicy Bypass -NoExit -File "{TSCON_SCRIPT_PATH.absolute()}" -PythonPid {current_pid}\' -Verb RunAs'
]

subprocess.Popen(powershell_cmd)

# 注意: tscon 执行后 RDP 会断开，脚本自动等待 Console Session 稳定
print("等待 30 秒让 Console Session 稳定...")
await asyncio.sleep(30)
```

**关键技术点：**

1. **AllowSetForegroundWindow API**:
   ```powershell
   Add-Type @"
       using System;
       using System.Runtime.InteropServices;
       public class WinAPI {
           [DllImport("user32.dll")]
           public static extern bool AllowSetForegroundWindow(int dwProcessId);
       }
   "@

   $result = [WinAPI]::AllowSetForegroundWindow($PythonPid)
   ```

2. **自动检测 RDP Session**:
   ```powershell
   $sessionOutput = query session
   $currentSession = $sessionOutput | Where-Object { $_ -match '>' }

   if ($currentSession -match '>\\s*(\\S+)\\s+\\S+\\s+(\\d+)\\s+Active') {
       $sessionId = $matches[2]
       tscon $sessionId /dest:console
   }
   ```

3. **UAC 管理员权限提升**:
   ```python
   # Python 使用 Start-Process -Verb RunAs 请求管理员权限
   Start-Process powershell -Verb RunAs -ArgumentList '...'
   ```

4. **编码问题解决**:
   - 脚本使用 UTF-8 with BOM 编码保存
   - PowerShell 才能正确解析中文字符
   - Python 使用 `codecs.open('utf-8-sig')` 写入

**工作流程：**

```
1. Python 脚本启动（在 RDP Session 中）
    ↓
2. 获取 Python PID (os.getpid())
    ↓
3. 检查 tscon_with_allow.ps1 是否存在
    ↓
4. 使用 PowerShell Start-Process -Verb RunAs 启动脚本
    ↓
5. 用户点击 UAC 提示的 "是"
    ↓
6. PowerShell 脚本执行：
   - AllowSetForegroundWindow(PythonPid)  ✅ 授权
   - query session                         ✅ 检测 Session ID
   - tscon <session_id> /dest:console      ✅ 切换到 Console
    ↓
7. RDP 连接断开（预期行为）
    ↓
8. Python 脚本自动等待 30 秒让 Console Session 稳定
    ↓
9. 在新线程中调用 bring_window_to_foreground()
    ↓
10. SetForegroundWindow() 成功（已被授权）
    ↓
11. Popup 正常显示 ✅
```

**优势：**

- ✅ **一键自动化**: 不需要手动 `query session` 和记住 Session ID
- ✅ **权限自动授予**: `AllowSetForegroundWindow` 自动授权，无需手动调用 API
- ✅ **错误处理**: 提供详细的成功/失败提示
- ✅ **编码兼容**: 支持中文字符显示
- ✅ **自动继续**: tscon 后脚本自动等待并继续，无需手动 input()

**常见问题：**

1. **Q: 为什么需要 AllowSetForegroundWindow？**
   - A: Windows 默认不允许后台进程设置前台窗口，必须由前台进程（PowerShell）授权

2. **Q: 为什么脚本需要管理员权限？**
   - A: `tscon` 命令需要管理员权限才能切换 Session

3. **Q: tscon 后为什么要等待 30 秒？**
   - A: Console Session 切换需要时间稳定，包括 Desktop 绑定、GUI 子系统初始化等

4. **Q: 如果 PowerShell 脚本不存在会怎样？**
   - A: Python 脚本会检测并给出错误提示，提供手动执行的步骤

**文件位置：**
- PowerShell 脚本: `test_agent/test_script/tscon_with_allow.ps1`
- Python 集成示例: `test_agent/test_script/test_cdp_attach_checkout.py`
- Plan B 完整实现: `test_agent/test_script/test_cdp_attach_checkout_plan_b.py`

### 两台 VM 方案为什么也不行？

用户之前问的"VM A 连接 VM B，然后断开"的方案同样不行，因为：

1. **VM A 断开 mstsc 连接后，VM B 的 RDP Session 变成 Disconnected 状态**
2. Disconnected RDP Session 和 Minimized RDP 的限制相同：
   - Window Station 变为 inactive
   - GUI API 受限
3. **除非在 VM B 里执行 tscon 切换到 Console Session**

### 最终方案总结

| 方案 | GUI API 可用？ | 新线程 Desktop 绑定 | SetForegroundWindow | Popup 显示？ |
|------|---------------|--------------------|--------------------|-------------|
| RDP 最小化 | ❌ (error 87) | N/A | ❌ | ❌ |
| RDP + tscon (主线程) | ✅ | ❌ 绑定旧 Desktop | ❌ | ❌ |
| RDP + tscon (新线程) | ✅ | ✅ 绑定 Console Desktop | ✅ | ✅ |
| Console Session 启动 | ✅ | ✅ 直接绑定 Console | ✅ | ✅ |

**最佳实践（方案 B）：**
1. 在 RDP Session 中启动脚本（不需要控制台访问）
2. 脚本提示用户执行 `tscon <session_id> /dest:console`
3. 等待 15 秒让 Console Session 稳定
4. **在新线程中执行焦点设置和窗口操作**
5. 新线程自动绑定到 Console Desktop
6. `SetForegroundWindow` 成功，Popup 正常显示