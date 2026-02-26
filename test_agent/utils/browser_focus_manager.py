"""
Browser Focus Manager - 浏览器窗口焦点管理器

独立工具类，无需修改 browser-use 源码，可在任何自动化测试项目中使用。

功能：
1. 设置浏览器窗口为 TOPMOST（总在最前）
2. 定期检查并恢复焦点（可选）
3. 兼容 tscon 后的 Desktop 切换（使用新线程）

使用方法：
    from test_agent.utils.browser_focus_manager import BrowserFocusManager

    # 启动 browser-use
    agent = Agent(...)

    # 启动焦点管理器
    focus_manager = BrowserFocusManager(
        browser_process_name='msedge.exe',
        keep_topmost=True,           # 设置为 TOPMOST
        auto_restore_focus=True,     # 自动恢复焦点
        check_interval=2.0           # 每 2 秒检查一次
    )
    focus_manager.start()

    # 运行测试
    await agent.run(...)

    # 清理
    focus_manager.stop()
"""

import threading
import time
import win32gui
import win32con
import win32process
import psutil
import comtypes.client
from typing import Optional


def _get_uia_client():
	"""获取 UIAutomationClient 模块"""
	try:
		from comtypes.gen import UIAutomationClient
		return UIAutomationClient
	except ImportError:
		print("[UIA] 正在生成 UI Automation 类型库...")
		comtypes.client.GetModule("UIAutomationCore.dll")
		from comtypes.gen import UIAutomationClient
		print("[UIA] 类型库生成完成")
		return UIAutomationClient


class BrowserFocusManager:
	"""
	浏览器窗口焦点管理器

	独立工具类，用于：
	1. 设置浏览器窗口为 TOPMOST（总在最前，类似任务管理器）
	2. 定期检查并恢复窗口焦点
	3. 兼容 RDP + tscon 环境（使用新线程处理 Desktop 切换）
	"""

	def __init__(
		self,
		browser_process_name: str = 'msedge.exe',
		keep_topmost: bool = True,
		auto_restore_focus: bool = True,
		check_interval: float = 2.0
	):
		"""
		Args:
			browser_process_name: 浏览器进程名（msedge.exe / chrome.exe / firefox.exe）
			keep_topmost: 是否设置为 TOPMOST（总在最前）
			auto_restore_focus: 是否自动恢复焦点（失去焦点时重新设置）
			check_interval: 焦点检查间隔（秒），仅在 auto_restore_focus=True 时有效
		"""
		self.browser_process_name = browser_process_name.lower()
		self.keep_topmost = keep_topmost
		self.auto_restore_focus = auto_restore_focus
		self.check_interval = check_interval

		self.running = False
		self._thread: Optional[threading.Thread] = None
		self._browser_hwnd: Optional[int] = None

	def start_sync(self) -> bool:
		"""
		启动焦点管理（同步版本，用于在线程池中执行）

		Returns:
			True if started successfully, False otherwise
		"""
		if self.running:
			print(f"[FocusManager] Already running")
			return True

		print(f"[FocusManager] Starting...")
		print(f"  - Browser: {self.browser_process_name}")
		print(f"  - TOPMOST: {self.keep_topmost}")
		print(f"  - Auto restore: {self.auto_restore_focus}")

		# 同步等待浏览器窗口出现（带重试）
		print(f"[FocusManager] Waiting for browser window to appear...")
		max_retries = 3
		retry_interval = 2

		for attempt in range(1, max_retries + 1):
			self._browser_hwnd = self._find_browser_window()
			if self._browser_hwnd:
				print(f"[FocusManager] ✅ Found browser window (attempt {attempt}/{max_retries})")
				break

			if attempt < max_retries:
				print(f"[FocusManager] ⚠️  Browser not found (attempt {attempt}/{max_retries}), retrying in {retry_interval}s...")
				time.sleep(retry_interval)
			else:
				print(f"[FocusManager] ⚠️  Browser window not found after {max_retries} retries")
				return False

		# 诊断窗口层级信息
		# self._diagnose_window_hierarchy()

		# 设置为 TOPMOST
		if self.keep_topmost:
			self._set_topmost(True)
			print(f"[FocusManager] ✅ Browser set to TOPMOST (always on top)")

		# 启动焦点守护线程
		if self.auto_restore_focus:
			self.running = True
			self._thread = threading.Thread(
				target=self._focus_keeper_loop,
				daemon=True,
				name="BrowserFocusKeeper"
			)
			self._thread.start()
			print(f"[FocusManager] 🔒 Focus keeper started (check interval: {self.check_interval}s)")

		print(f"[FocusManager] ✅ Started successfully")
		return True

	# def _diagnose_window_hierarchy(self):
	# 	"""诊断窗口层级结构，帮助排查问题"""
	# 	if not self._browser_hwnd:
	# 		return

	# 	try:
	# 		hwnd = self._browser_hwnd
	# 		root_hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
	# 		parent_hwnd = win32gui.GetParent(hwnd)
	# 		owner_hwnd = win32gui.GetWindow(hwnd, win32con.GW_OWNER) if hwnd else 0

	# 		print(f"[FocusManager] 窗口层级诊断:")
	# 		print(f"  - 原始 HWND: {hwnd}")
	# 		print(f"  - Root HWND: {root_hwnd} {'(相同 ✅)' if hwnd == root_hwnd else '(不同 ⚠️)'}")
	# 		print(f"  - Parent HWND: {parent_hwnd if parent_hwnd else 'None (顶层窗口 ✅)'}")
	# 		print(f"  - Owner HWND: {owner_hwnd if owner_hwnd else 'None (独立窗口 ✅)'}")

	# 		# 检查 Extended Style
	# 		ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
	# 		is_layered = (ex_style & win32con.WS_EX_LAYERED) != 0
	# 		is_topmost_now = (ex_style & win32con.WS_EX_TOPMOST) != 0

	# 		print(f"  - Extended Style: {hex(ex_style)}")
	# 		print(f"    - LAYERED: {'是 ⚠️' if is_layered else '否 ✅'}")
	# 		print(f"    - TOPMOST (before set): {'是' if is_topmost_now else '否'}")

	# 	except Exception as e:
	# 		print(f"[FocusManager] ⚠️  窗口诊断失败: {e}")

	def stop(self):
		"""停止焦点管理"""
		if not self.running and not self._browser_hwnd:
			return

		print(f"[FocusManager] Stopping...")

		# 停止焦点守护线程
		if self.running:
			self.running = False
			if self._thread:
				self._thread.join(timeout=3)
			print(f"[FocusManager] Focus keeper stopped")

		# 取消 TOPMOST
		if self.keep_topmost and self._browser_hwnd:
			self._set_topmost(False)
			print(f"[FocusManager] ✅ TOPMOST removed")

		self._browser_hwnd = None
		print(f"[FocusManager] Stopped")

	def _find_browser_window(self) -> Optional[int]:
		"""
		查找浏览器窗口句柄

		Returns:
			窗口句柄 (hwnd)，如果未找到则返回 None
		"""
		try:
			UIAutomationClient = _get_uia_client()
			uia = comtypes.client.CreateObject(
				"{ff48dba4-60ef-4201-aa87-54103eef594e}",
				interface=UIAutomationClient.IUIAutomation
			)
			root = uia.GetRootElement()

			# 查找所有 Chrome_WidgetWin_1 窗口（Chrome/Edge/Opera 等都用这个类名）
			class_condition = uia.CreatePropertyCondition(
				UIAutomationClient.UIA_ClassNamePropertyId,
				"Chrome_WidgetWin_1"
			)
			windows = root.FindAll(UIAutomationClient.TreeScope_Children, class_condition)

			print(f"[FocusManager] Found {windows.Length} Chrome-based windows, searching for {self.browser_process_name}...")

			# 通过进程名匹配浏览器窗口
			for i in range(windows.Length):
				window = windows.GetElement(i)
				try:
					hwnd = window.CurrentNativeWindowHandle
					_, pid = win32process.GetWindowThreadProcessId(hwnd)
					process = psutil.Process(pid)

					if process.name().lower() == self.browser_process_name:
						name = window.CurrentName
						print(f"[FocusManager] ✅ Found browser: '{name}' (hwnd={hwnd}, pid={pid})")
						return hwnd
				except:
					continue

			print(f"[FocusManager] ⚠️  No window found for process: {self.browser_process_name}")
			return None

		except Exception as e:
			print(f"[FocusManager] ❌ Error finding browser: {e}")
			import traceback
			traceback.print_exc()
			return None

	def _set_topmost(self, topmost: bool):
		"""
		设置/取消 TOPMOST 状态（模拟任务管理器的实现）

		Args:
			topmost: True=设置为 TOPMOST, False=取消 TOPMOST
		"""
		if not self._browser_hwnd:
			return

		try:
			# 确保操作的是真正的顶层窗口（root window），而不是子窗口
			root_hwnd = win32gui.GetAncestor(self._browser_hwnd, win32con.GA_ROOT)

			# 标志位：NOACTIVATE 防止 DWM 重新排序 inactive topmost 窗口
			flags = (win32con.SWP_NOMOVE |
			         win32con.SWP_NOSIZE |
			         win32con.SWP_NOACTIVATE)

			if topmost:
				# 先移除再设置，强制刷新 Z-order（解决 layered 窗口和 DWM 问题）
				win32gui.SetWindowPos(
					root_hwnd,
					win32con.HWND_NOTOPMOST,
					0, 0, 0, 0,
					flags
				)

				win32gui.SetWindowPos(
					root_hwnd,
					win32con.HWND_TOPMOST,
					0, 0, 0, 0,
					flags
				)
				print(f"[FocusManager] Set TOPMOST for browser (root hwnd={root_hwnd}, original={self._browser_hwnd})")
			else:
				# 取消 TOPMOST
				win32gui.SetWindowPos(
					root_hwnd,
					win32con.HWND_NOTOPMOST,
					0, 0, 0, 0,
					flags
				)
				print(f"[FocusManager] Removed TOPMOST for browser (root hwnd={root_hwnd})")

		except Exception as e:
			print(f"[FocusManager] ⚠️  Error setting TOPMOST={topmost}: {e}")

	def _restore_focus_in_new_thread(self) -> bool:
		"""
		在新线程中恢复窗口焦点

		使用新线程的原因：
		- 兼容 tscon 后的 Desktop 切换
		- 新线程会自动绑定到当前的 Input Desktop (Console)
		- SetForegroundWindow 在新线程中能够成功

		Returns:
			True if focus restored successfully, False otherwise
		"""
		success = [False]

		def _focus_worker():
			"""工作线程 - 在新 Desktop 中设置焦点"""
			try:
				# Step 1: SetWindowPos 置顶（不带 SWP_NOACTIVATE）
				win32gui.SetWindowPos(
					self._browser_hwnd,
					win32con.HWND_TOP,
					0, 0, 0, 0,
					win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
				)

				# Step 2: SetForegroundWindow
				try:
					win32gui.SetForegroundWindow(self._browser_hwnd)
					success[0] = True
				except Exception as e:
					# 在某些环境下可能失败，但 SetWindowPos 已经足够
					success[0] = False
			except Exception as e:
				success[0] = False

		# 创建新线程执行焦点设置
		worker = threading.Thread(target=_focus_worker, daemon=True)
		worker.start()
		worker.join(timeout=1)

		return success[0]

	def _focus_keeper_loop(self):
		"""焦点守护循环（定期检查并恢复焦点）"""
		print(f"[FocusManager] Focus keeper loop started")

		while self.running:
			try:
				# 检查窗口是否在前台
				foreground = win32gui.GetForegroundWindow()

				if foreground != self._browser_hwnd:
					# 浏览器失去焦点，恢复
					print(f"[FocusManager] Browser lost focus (foreground={foreground}), restoring...")
					self._restore_focus_in_new_thread()

			except Exception as e:
				print(f"[FocusManager] ⚠️  Error in focus keeper: {e}")

			time.sleep(self.check_interval)

		print(f"[FocusManager] Focus keeper loop stopped")
