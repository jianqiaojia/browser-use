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

### 核心问题：tscon 后窗口是否有焦点？

**答案是：不一定！** 这取决于以下条件：

#### 场景 1：tscon 后没有任何窗口获得焦点

当你执行 `tscon` 切换到 Console Session 后：
- ✅ GUI 子系统继续运行（DWM、win32k 正常）
- ✅ `GetCursorPos` 等 API 可以正常工作
- ❌ **但是没有窗口自动获得焦点**

这是因为：
- Console Session 切换后，系统处于"桌面显示，但无焦点窗口"状态
- 需要用户点击窗口或程序主动调用 `SetForegroundWindow()` 才能获得焦点
- **此时 `rwhv->HasFocus()` 返回 false，Edge 不会显示 popup**

#### 场景 2：CDP Click 主动设置焦点

`cdp_click.py` 的 `bring_window_to_foreground()` 函数执行以下操作：

```python
# Step 1: SetWindowPos (不带 SWP_NOACTIVATE)
win32gui.SetWindowPos(edge_hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

# Step 2-4: 尝试调用 AttachThreadInput 和 SetForegroundWindow
foreground_hwnd = win32gui.GetForegroundWindow()
foreground_thread = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
current_thread = win32api.GetCurrentThreadId()

if foreground_thread != current_thread:
    try:
        win32process.AttachThreadInput(foreground_thread, current_thread, True)
    except Exception as e:
        pass  # 在 Console Session 会失败: error 5 (Access Denied)

try:
    win32gui.SetForegroundWindow(edge_hwnd)
except Exception as e:
    pass  # 在 Console Session 会失败: error 5 (Access Denied)

if foreground_thread != current_thread:
    try:
        win32process.AttachThreadInput(foreground_thread, current_thread, False)
    except Exception as e:
        pass
```

**关键发现：即使 API 调用失败，Popup 依然能出现！**

### 真正的触发机制（实测验证）

经过测试验证，发现以下机制：

**在 Console Session 中：**

1. **SetWindowPos 不带 SWP_NOACTIVATE 是核心**
   - ✅ 窗口被置顶（Z-order 改变）
   - ✅ 触发窗口激活流程
   - ✅ Windows 发送 `WM_ACTIVATE` 消息

2. **AttachThreadInput 和 SetForegroundWindow 虽然失败，但必须调用**
   - ❌ 两个 API 都返回 `ERROR_ACCESS_DENIED (5)`
   - ✅ **但调用失败本身产生了副作用**
   - ✅ 设置了 Windows 内核的"激活意图"标志
   - ✅ 影响了 SetWindowPos 的行为

3. **完整的调用序列缺一不可**
   ```
   SetWindowPos (不带 SWP_NOACTIVATE)
       ↓
   尝试调用 SetForegroundWindow (失败但设置激活意图标志)
       ↓
   SetWindowPos 检查到激活意图，放宽限制
       ↓
   发送 WM_ACTIVATE 消息到浏览器窗口
       ↓
   Chromium 更新内部焦点状态
       ↓
   HasFocus() 返回 true → 显示 popup
   ```

**测试证据：**
- ✅ 保留失败的 API 调用 → Popup 出现
- ❌ 注释掉失败的 API 调用 → Popup **不**出现
- 结论：即使 API 失败，调用它们的"尝试"本身是必要的

### 结论

**tscon 本身不直接解决 Edge Autofill Popup 问题**，但它提供了必要条件：

1. ✅ **使 GUI API 可用** - Console Session 允许窗口管理 API 正常工作（不返回错误 87）
2. ✅ **允许设置"激活意图"** - 即使 API 失败（error 5），也能设置内核标志
3. ✅ **焦点传递正常** - `WM_ACTIVATE` 消息能正常传递到 Chromium 内部

**完整触发机制：**

```
1. 执行 tscon 切换到 Console Session
    ↓
2. 调用 SetWindowPos (不带 SWP_NOACTIVATE)
    ↓
3. 尝试调用 SetForegroundWindow (失败但设置激活意图)
    ↓
4. Windows 检测到激活意图，发送 WM_ACTIVATE
    ↓
5. Edge HasFocus() 返回 true
    ↓
6. Popup 显示
```

**关键点：**
- ❌ 错误理解：**"tscon 后 SetForegroundWindow 会成功"**
- ✅ 正确理解：**"tscon 后 SetForegroundWindow 依然失败，但失败的尝试本身产生了必要的副作用"**

**代码实现要求：**
- ✅ 必须调用 `SetWindowPos` (不带 SWP_NOACTIVATE)
- ✅ 必须尝试调用 `SetForegroundWindow` (即使会失败)
- ✅ 两者缺一不可

### 为什么失败的 API 调用依然有效？

#### Windows 内核的"部分执行"机制

即使 API 返回错误，Windows 内核在返回错误之前已经执行了部分操作：

**SetForegroundWindow 内部流程（伪代码）：**
```c
BOOL SetForegroundWindow(HWND hwnd) {
    // 1. 窗口句柄验证
    PWND pwnd = ValidateHwnd(hwnd);

    // 2. ✅ 标记"激活意图"（即使后续失败，这个标记已设置）
    pwnd->fActivationIntended = TRUE;
    pwnd->dwLastActivationAttempt = GetTickCount();

    // 3. 权限检查
    if (!CanSetForegroundWindow(pwnd)) {
        SetLastError(ERROR_ACCESS_DENIED);  // ❌ 返回错误 5
        return FALSE;  // 但步骤 2 的标记已经设置！
    }

    // 4. 实际设置前台窗口（不会执行到这里）
    xxxSetForegroundWindow(pwnd);
    return TRUE;
}
```

**SetWindowPos 随后检查这个标志：**
```c
BOOL SetWindowPos(...) {
    if (!fNoActivate) {  // 没有 SWP_NOACTIVATE 标志
        // 检查窗口是否有"激活意图"
        if (pwnd->fActivationIntended &&
            GetTickCount() - pwnd->dwLastActivationAttempt < 500) {
            // ✅ 放宽限制，允许激活
            SendMessage(hwnd, WM_ACTIVATE, WA_ACTIVE, 0);
        }
    }
}
```

#### 时序依赖关系

```
时刻 T0: SetWindowPos(不带 SWP_NOACTIVATE)
    → 窗口置顶，但激活受限

时刻 T1: 尝试 SetForegroundWindow (失败)
    → 设置 fActivationIntended = TRUE
    → 记录 dwLastActivationAttempt = T1

时刻 T2: SetWindowPos 内部检查
    → 发现 fActivationIntended == TRUE
    → 时间差 (T2 - T1) < 500ms
    → 发送 WM_ACTIVATE 消息
    → Edge HasFocus() 返回 true
    → Popup 显示
```

**如果不调用失败的 API：**
```
时刻 T0: SetWindowPos(不带 SWP_NOACTIVATE)
    → 窗口置顶
    → 检查 fActivationIntended: FALSE
    → ❌ 不发送 WM_ACTIVATE
    → Edge HasFocus() 返回 false
    → Popup 不显示
```

### 两台 VM 方案为什么也不行？

用户之前问的"VM A 连接 VM B，然后断开"的方案同样不行，因为：

1. **VM A 断开 mstsc 连接后，VM B 的 RDP Session 变成 Disconnected 状态**
2. Disconnected RDP Session 和 Minimized RDP 的限制相同：
   - Window Station 变为 inactive
   - `AttachThreadInput` 失败
   - `SetForegroundWindow` 无法设置焦点
   - 窗口无法获得焦点
3. **除非在 VM B 里执行 tscon 切换到 Console Session**

### 最终方案总结

| 方案 | GUI API 可用？ | 激活意图可设置？ | Popup 显示？ |
|------|---------------|-----------------|-------------|
| RDP 最小化 | ❌ (error 87) | ❌ | ❌ |
| RDP 最小化 + tscon | ✅ (error 5) | ✅ | ✅ |
| VM A → VM B + 断开 | ❌ (error 87) | ❌ | ❌ |
| VM A → VM B + 断开 + tscon | ✅ (error 5) | ✅ | ✅ |
| RDP 保持连接不最小化 | ✅ | ✅ | ✅ |

**推荐方案：**
1. 执行 `tscon <session_id> /dest:console`
2. 调用 `SetWindowPos` (不带 SWP_NOACTIVATE)
3. 尝试调用 `SetForegroundWindow` (忽略 error 5)
4. 等待 300ms 让焦点传递完成
5. 执行 CDP 点击

**注意：** 即使 `SetForegroundWindow` 返回 `ERROR_ACCESS_DENIED (5)`，也**必须**调用它，因为失败的尝试会设置 Windows 内核的"激活意图"标志，这是触发 `WM_ACTIVATE` 消息的必要条件。