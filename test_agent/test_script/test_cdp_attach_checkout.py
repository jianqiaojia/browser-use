"""
完整测试脚本：CDP 连接 + CDP Click + UIA 检测 + 日志监控
使用 Playwright 直接连接到已启动的浏览器（不需要 browser-use）

测试流程：
1. 连接到浏览器并找到 email input
2. 自动启动 tscon 辅助脚本（PowerShell）切换到 Console Session
3. 循环执行：设置焦点 → CDP 点击 → 检测 popup
4. 每次循环间隔 10 秒
5. 监控日志和 UIA 检测

使用场景：
- 测试 RDP Session 切换到 Console Session 后的效果
- 验证 tscon + AllowSetForegroundWindow 是否解决了 popup 显示问题
- 使用独立的 PowerShell 脚本自动化 tscon 执行流程
"""

import asyncio
import sys
import os
import time
import re
from pathlib import Path
from typing import Optional, List, Dict
from playwright.async_api import async_playwright
import win32gui
import win32con
import win32process
import win32api
import psutil
import comtypes.client

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入 UIA Helper
from uia_helper.uia_server import UIAHelper

# 导入 cdp_click 中的简化版焦点设置函数
from custom_actions.cdp_click import bring_window_to_foreground


# ============================================================================
# tscon 辅助脚本路径
# ============================================================================

# PowerShell 脚本路径（与当前 Python 脚本在同一目录）
TSCON_SCRIPT_PATH = Path(__file__).parent / "tscon_with_allow.ps1"


# ============================================================================
# 日志监控器
# ============================================================================

class EdgeLogMonitor:
	"""Edge 日志文件监控器"""

	def __init__(self, log_file_path: str):
		"""初始化日志监控器"""
		self.log_file_path = log_file_path
		self.last_position = 0
		self.show_logs = []
		self.hide_logs = []

		# 初始化：跳过已有内容
		if os.path.exists(log_file_path):
			try:
				with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
					f.seek(0, 2)  # 跳到文件末尾
					self.last_position = f.tell()
					print(f"[LogMonitor] 初始化完成，当前位置: {self.last_position}")
			except Exception as e:
				print(f"[LogMonitor] ⚠️  初始化失败: {e}")

	def check_new_logs(self) -> Dict[str, List[Dict]]:
		"""检查新的日志条目"""
		if not os.path.exists(self.log_file_path):
			return {'show': [], 'hide': []}

		new_show_logs = []
		new_hide_logs = []

		try:
			with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
				f.seek(self.last_position)
				new_lines = f.readlines()
				self.last_position = f.tell()

				for line in new_lines:
					# 检测 Show 日志
					show_match = re.search(r'\[haha\]EdgeExpressCheckoutCompositorViews::Show result=(\w+)', line)
					if show_match:
						result = show_match.group(1)
						time_match = re.search(r'\[.*?(\d{6}\.\d{3}):', line)
						timestamp = time_match.group(1) if time_match else 'unknown'

						log_entry = {
							'timestamp': timestamp,
							'result': result,
							'line': line.strip()
						}
						new_show_logs.append(log_entry)
						self.show_logs.append(log_entry)
						print(f"[LogMonitor] 📝 Show: result={result} @ {timestamp}")

					# 检测 Hide 日志
					hide_match = re.search(r'\[haha\]EdgeExpressCheckoutCompositorViews::Hide called', line)
					if hide_match:
						time_match = re.search(r'\[.*?(\d{6}\.\d{3}):', line)
						timestamp = time_match.group(1) if time_match else 'unknown'

						log_entry = {
							'timestamp': timestamp,
							'line': line.strip()
						}
						new_hide_logs.append(log_entry)
						self.hide_logs.append(log_entry)
						print(f"[LogMonitor] 📝 Hide: @ {timestamp}")

		except Exception as e:
			print(f"[LogMonitor] ⚠️  读取日志失败: {e}")

		return {'show': new_show_logs, 'hide': new_hide_logs}


# ============================================================================
# UIA 检测器
# ============================================================================

# def _get_uia_client():
# 	"""获取 UIAutomationClient 模块"""
# 	try:
# 		from comtypes.gen import UIAutomationClient
# 		return UIAutomationClient
# 	except ImportError:
# 		print("[UIA] 正在生成 UI Automation 类型库...")
# 		comtypes.client.GetModule("UIAutomationCore.dll")
# 		from comtypes.gen import UIAutomationClient
# 		print("[UIA] 类型库生成完成")
# 		return UIAutomationClient


def take_screenshot(prefix: str = "screenshot") -> str | None:
	"""
	截取整个屏幕并保存

	Args:
		prefix: 文件名前缀

	Returns:
		截图文件路径，失败返回 None
	"""
	try:
		import pyautogui
		from datetime import datetime
		from pathlib import Path

		# 创建截图目录
		screenshot_dir = Path("screenshots")
		screenshot_dir.mkdir(exist_ok=True)

		# 生成文件名（带时间戳）
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
		screenshot_path = screenshot_dir / f"{prefix}_{timestamp}.png"

		# 截取整个屏幕
		screenshot = pyautogui.screenshot()
		screenshot.save(str(screenshot_path))

		print(f"[Screenshot] 📸 已保存: {screenshot_path}", flush=True)
		return str(screenshot_path)

	except Exception as e:
		print(f"[Screenshot] ⚠️  截图失败: {e}", flush=True)
		return None


def detect_popup_with_uia(timeout: float = 5.0) -> bool:
	"""
	使用 UIA 检测 Express Checkout Popup 是否出现
	直接调用 UIAHelper.get_popup_state()

	Args:
		timeout: 超时时间（秒）

	Returns:
		True if popup detected, False otherwise
	"""
	try:
		print(f"[UIA] 开始检测，超时时间: {timeout}s", flush=True)
		uia_helper = UIAHelper()

		start_time = time.time()
		check_count = 0

		while time.time() - start_time < timeout:
			check_count += 1
			print(f"[UIA] 检测第 {check_count} 次...", flush=True)

			# 调用 get_popup_state 检测 popup
			result = uia_helper.get_popup_state()

			print(f"[UIA] get_popup_state 返回: success={result.get('success')}, visible={result.get('visible')}", flush=True)

			if result.get('success') and result.get('visible'):
				item_count = result.get('item_count', 0)
				items = result.get('items', [])
				print(f"[UIA] ✅ 检测到 Express Checkout Popup!", flush=True)
				print(f"[UIA]   - 选项数量: {item_count}", flush=True)
				if items:
					print(f"[UIA]   - 选项内容: {items[:3]}", flush=True)

				# 截图保存
				take_screenshot("popup_detected")

				return True

			# 稍微等待后重试
			time.sleep(0.1)

		print(f"[UIA] ⏱️  超时 ({timeout}s)，未检测到 Popup（共检测 {check_count} 次）", flush=True)
		return False

	except Exception as e:
		print(f"[UIA] ⚠️  检测失败: {e}", flush=True)
		import traceback
		traceback.print_exc()
		return False


def verify_popup_dismissed(timeout: float = 2.0) -> bool:
	"""
	验证 Popup 是否已消失

	Args:
		timeout: 超时时间（秒）

	Returns:
		True if popup dismissed, False if still visible
	"""
	try:
		print(f"[UIA] 验证 Popup 是否已消失（超时: {timeout}s）", flush=True)
		uia_helper = UIAHelper()

		start_time = time.time()
		check_count = 0

		while time.time() - start_time < timeout:
			check_count += 1

			# 调用 get_popup_state 检测 popup
			result = uia_helper.get_popup_state()

			if not result.get('success') or not result.get('visible'):
				print(f"[UIA] ✅ Popup 已消失（检测 {check_count} 次后确认）", flush=True)
				return True

			# 稍微等待后重试
			time.sleep(0.1)

		print(f"[UIA] ⚠️  超时 ({timeout}s)，Popup 仍然可见", flush=True)
		return False

	except Exception as e:
		print(f"[UIA] ⚠️  验证失败: {e}", flush=True)
		return False


async def click_blank_to_dismiss_popup(page, box: dict) -> bool:
	"""
	点击空白处让 popup 消失，并验证 popup 已消失

	Args:
		page: Playwright page 对象
		box: Email input 元素的边界框信息

	Returns:
		True if popup dismissed successfully, False otherwise
	"""
	try:
		print(f"[Dismiss] 点击空白处让 popup 消失", flush=True)

		# 点击 email input box 左侧 5px 的空白位置
		blank_x = box['x'] - 5
		blank_y = box['y'] + box['height'] / 2  # 垂直居中

		print(f"[Dismiss] 点击位置: ({blank_x:.1f}, {blank_y:.1f})", flush=True)
		await page.mouse.click(blank_x, blank_y)
		print(f"[Dismiss] ✅ 已点击空白处", flush=True)

		# 等待一下让焦点转移
		await asyncio.sleep(0.3)

		# 验证 popup 是否消失
		dismissed = verify_popup_dismissed(timeout=2.0)

		if dismissed:
			print(f"[Dismiss] ✅ Popup 已成功消失", flush=True)
		else:
			print(f"[Dismiss] ⚠️  Popup 未消失", flush=True)

		return dismissed

	except Exception as e:
		print(f"[Dismiss] ❌ 点击空白处失败: {e}", flush=True)
		import traceback
		traceback.print_exc()
		return False


# ============================================================================
# 窗口焦点管理
# ============================================================================
# NOTE: 现在使用从 cdp_click.py 导入的简化版 bring_window_to_foreground()
# 该版本只使用 SetWindowPos（不带 SWP_NOACTIVATE），在 Console Session 中足够触发 Edge 焦点检查


# def bring_window_to_foreground_good() -> bool:
# 	"""
# 	使用 UIA + Win32 API 将浏览器窗口置于前台并设置焦点

# 	Returns:
# 		True if success, False otherwise
# 	"""
# 	try:
# 		UIAutomationClient = _get_uia_client()
# 		uia = comtypes.client.CreateObject(
# 			"{ff48dba4-60ef-4201-aa87-54103eef594e}",
# 			interface=UIAutomationClient.IUIAutomation
# 		)
# 		root = uia.GetRootElement()

# 		# 查找 Chrome/Edge 窗口
# 		class_condition = uia.CreatePropertyCondition(
# 			UIAutomationClient.UIA_ClassNamePropertyId,
# 			"Chrome_WidgetWin_1"
# 		)
# 		windows = root.FindAll(
# 			UIAutomationClient.TreeScope_Children,
# 			class_condition
# 		)

# 		# 找到 Edge 浏览器窗口（通过进程名）
# 		edge_hwnd = None
# 		print(f"[Focus] 查找浏览器窗口，共发现 {windows.Length} 个 Chrome_WidgetWin_1 窗口:")
# 		for i in range(windows.Length):
# 			window = windows.GetElement(i)
# 			try:
# 				name = window.CurrentName
# 				hwnd = window.CurrentNativeWindowHandle

# 				# Get process ID and name
# 				try:
# 					_, pid = win32process.GetWindowThreadProcessId(hwnd)
# 					process = psutil.Process(pid)
# 					process_name = process.name().lower()

# 					print(f"[Focus]   窗口 {i+1}: '{name[:60]}...' (hwnd={hwnd}, pid={pid}, process={process_name})")

# 					# Check if it's Edge browser process
# 					if process_name == 'msedge.exe':
# 						edge_hwnd = hwnd
# 						print(f"[Focus]   ✅ 匹配到 Edge 浏览器窗口: '{name}'")
# 						break
# 				except Exception as e:
# 					# Skip windows where we can't get process info
# 					print(f"[Focus]   窗口 {i+1}: 无法获取进程信息 ({e})")
# 					continue
# 			except Exception as e:
# 				print(f"[Focus]   窗口 {i+1}: 无法读取 ({e})")
# 				continue

# 		if not edge_hwnd:
# 			print(f"[Focus] ⚠️  未找到浏览器窗口")
# 			return False

# 		# 多步骤设置焦点
# 		try:
# 			# 1. 如果最小化，先恢复
# 			if win32gui.IsIconic(edge_hwnd):
# 				print(f"[Focus] 恢复最小化窗口...")
# 				win32gui.ShowWindow(edge_hwnd, win32con.SW_RESTORE)
# 				time.sleep(0.1)

# 			# 2. 置顶（尝试带激活标志）
# 			print(f"[Focus] 尝试 SetWindowPos 置顶并激活...")
# 			try:
# 				# 方法 A: 不带 SWP_NOACTIVATE（尝试激活）
# 				win32gui.SetWindowPos(
# 					edge_hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
# 					win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
# 				)
# 				print(f"[Focus] ✅ SetWindowPos 成功（带激活）")
# 			except Exception as e:
# 				print(f"[Focus] ⚠️  SetWindowPos 带激活失败: {e}")
# 				# 降级：不激活
# 				win32gui.SetWindowPos(
# 					edge_hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
# 					win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
# 				)
# 				print(f"[Focus] ✅ SetWindowPos 成功（不激活）")

# 			# 3. 获取线程信息
# 			foreground_hwnd = win32gui.GetForegroundWindow()
# 			print(f"[Focus] 当前前台窗口: {foreground_hwnd}")

# 			if foreground_hwnd == 0:
# 				print(f"[Focus] ⚠️  没有前台窗口，直接设置焦点")
# 				# 没有前台窗口，直接设置
# 				win32gui.SetForegroundWindow(edge_hwnd)
# 				print(f"[Focus] ✅ 浏览器窗口已置于前台（方法1）")
# 				return True

# 			# 获取线程 ID
# 			try:
# 				foreground_thread = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
# 				current_thread = win32api.GetCurrentThreadId()
# 				target_thread = win32process.GetWindowThreadProcessId(edge_hwnd)[0]

# 				print(f"[Focus] 线程信息:")
# 				print(f"  - 前台窗口线程: {foreground_thread}")
# 				print(f"  - 当前线程: {current_thread}")
# 				print(f"  - 目标窗口线程: {target_thread}")

# 				# 检查是否需要 AttachThreadInput
# 				if foreground_thread == current_thread:
# 					print(f"[Focus] 前台窗口已在当前线程，直接设置焦点")
# 					win32gui.SetForegroundWindow(edge_hwnd)
# 					print(f"[Focus] ✅ 浏览器窗口已置于前台（方法2）")
# 					return True

# 				# 使用 AttachThreadInput
# 				print(f"[Focus] 尝试 AttachThreadInput...")
# 				try:
# 					win32process.AttachThreadInput(foreground_thread, current_thread, True)
# 					print(f"[Focus] ✅ AttachThreadInput 成功")

# 					# 设置前台窗口
# 					win32gui.SetForegroundWindow(edge_hwnd)

# 					# 解除绑定
# 					win32process.AttachThreadInput(foreground_thread, current_thread, False)

# 					print(f"[Focus] ✅ 浏览器窗口已置于前台（方法3）")
# 					return True

# 				except Exception as attach_error:
# 					print(f"[Focus] ⚠️  AttachThreadInput 失败: {attach_error}")
# 					print(f"[Focus] 尝试方法4: 直接 SetForegroundWindow...")

# 					# 尝试直接设置（在 Console Session 可能可以）
# 					try:
# 						win32gui.SetForegroundWindow(edge_hwnd)
# 						print(f"[Focus] ✅ 浏览器窗口已置于前台（方法4 - 直接设置）")
# 						return True
# 					except Exception as direct_error:
# 						print(f"[Focus] ❌ 直接 SetForegroundWindow 也失败: {direct_error}")
# 						return False

# 			except Exception as thread_error:
# 				print(f"[Focus] ⚠️  获取线程信息失败: {thread_error}")
# 				print(f"[Focus] 尝试方法5: 强制设置焦点")

# 				# 最后尝试：强制设置
# 				try:
# 					win32gui.SetForegroundWindow(edge_hwnd)
# 					print(f"[Focus] ✅ 浏览器窗口已置于前台（方法5 - 强制设置）")
# 					return True
# 				except Exception as force_error:
# 					print(f"[Focus] ❌ 所有方法均失败: {force_error}")
# 					return False

# 		except Exception as e:
# 			print(f"[Focus] ❌ 设置焦点失败: {e}")
# 			import traceback
# 			traceback.print_exc()
# 			return False

# 	except Exception as e:
# 		print(f"[Focus] ❌ 失败: {e}")
# 		return False

# ============================================================================
# CDP 点击函数
# ============================================================================

async def cdp_click_element(cdp, email_input, box):
	"""
	使用 CDP 点击元素

	Args:
		cdp: CDP session
		email_input: Email input 元素
		box: 元素边界框

	Returns:
		True if success, False otherwise
	"""
	try:
		# 计算点击位置（元素中心）
		center_x = box['x'] + box['width'] / 2
		center_y = box['y'] + box['height'] / 2

		print(f"[CDP] 步骤 1: 滚动元素到视野内")
		await email_input.scroll_into_view_if_needed()
		await asyncio.sleep(0.05)

		print(f"[CDP] 步骤 2: 移动鼠标到元素中心 ({center_x:.1f}, {center_y:.1f})")
		await cdp.send('Input.dispatchMouseEvent', {
			'type': 'mouseMoved',
			'x': center_x,
			'y': center_y,
		})
		await asyncio.sleep(0.05)

		print(f"[CDP] 步骤 3: 鼠标按下 (mousePressed)")
		await cdp.send('Input.dispatchMouseEvent', {
			'type': 'mousePressed',
			'x': center_x,
			'y': center_y,
			'button': 'left',
			'clickCount': 1,
		})
		await asyncio.sleep(0.08)

		print(f"[CDP] 步骤 4: 鼠标释放 (mouseReleased)")
		await cdp.send('Input.dispatchMouseEvent', {
			'type': 'mouseReleased',
			'x': center_x,
			'y': center_y,
			'button': 'left',
			'clickCount': 1,
		})

		print(f"[CDP] ✅ CDP 点击完成")
		return True

	except Exception as e:
		print(f"[CDP] ❌ 点击失败: {e}")
		return False


# ============================================================================
# 主测试流程
# ============================================================================

async def main():
	print("=" * 80)
	print("CDP 连接 + 循环测试 + UIA 检测 + 日志监控 (Playwright)")
	print("=" * 80)

	# 配置参数
	CDP_URL = "http://localhost:9222"
	LOOP_INTERVAL = 30  # 循环间隔（秒）

	# Email input 选择器
	EMAIL_SELECTORS = [
		'[data-attr*=AddressForm] input#email',
		'input[type="email"]',
		'input#email',
		'input[name="email"]',
	]

	# Edge 日志文件路径
	edge_log_path = r"Q:\Edge\src\out\debug_x64\chrome_debug.log"

	# 初始化日志监控
	log_monitor = None
	if edge_log_path:
		log_monitor = EdgeLogMonitor(edge_log_path)
		print(f"\n[LogMonitor] 已初始化，监控文件: {edge_log_path}")

	# 提示用户准备
	print("\n" + "=" * 80)
	print("准备步骤：")
	print("1. 启动 Edge 并添加 CDP 参数：")
	print('   "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" \\')
	print('     --remote-debugging-port=9222 \\')
	print('     --enable-logging --v=1')
	print("")
	print("2. 在浏览器中手动导航到 Nike checkout 页面")
	print("3. 确保页面包含 email input 元素")
	print("4. 确保 Edge 已保存至少一个地址（用于 autofill）")
	print("=" * 80)

	# input("\n完成后按 Enter 继续...")

	try:
		async with async_playwright() as p:
			# 连接到已运行的浏览器
			print(f"\n[Playwright] 正在连接到 {CDP_URL}...")
			browser = await p.chromium.connect_over_cdp(CDP_URL)
			print("[Playwright] ✅ 已连接到浏览器")

			# 获取默认的 browser context
			contexts = browser.contexts
			if not contexts:
				print("[Playwright] ❌ 未找到 browser context")
				return

			context = contexts[0]
			print(f"[Playwright] 已连接到 context，有 {len(context.pages)} 个页面")

			# 获取当前激活的页面
			pages = context.pages
			if not pages:
				print("[Playwright] ❌ 未找到页面")
				return

			page = pages[-1]
			print(f"[Playwright] 使用页面: {page.url[:60]}...")

			# 等待页面稳定
			print("\n等待页面稳定...")
			await asyncio.sleep(1)

			# 查找 email input
			email_input = None
			email_selector = None

			print("\n正在查找 email input...")
			for selector in EMAIL_SELECTORS:
				try:
					print(f"  尝试选择器: {selector}")
					email_input = await page.query_selector(selector)
					if email_input:
						email_selector = selector
						print(f"  ✅ 找到元素!")
						break
				except Exception as e:
					print(f"  ⚠️  选择器失败: {e}")
					continue

			if not email_input:
				print("\n❌ 未找到 email input 元素")
				return

			print(f"\n✅ 使用选择器: {email_selector}")

			# 获取元素位置
			box = await email_input.bounding_box()
			if not box:
				print("\n❌ 元素没有边界框 (可能不可见)")
				return

			print(f"\n元素位置:")
			print(f"  x: {box['x']:.1f}, y: {box['y']:.1f}")
			print(f"  width: {box['width']:.1f}, height: {box['height']:.1f}")

			# 获取 CDP session
			cdp = await context.new_cdp_session(page)

			# 获取当前 Python 进程 PID
			current_pid = os.getpid()

			# 检查 PowerShell 脚本是否存在
			if not TSCON_SCRIPT_PATH.exists():
				print(f"\n❌ 错误: tscon 辅助脚本不存在: {TSCON_SCRIPT_PATH}")
				print("   请确保 tscon_with_allow.ps1 文件在当前目录下")
				return

			# 自动启动脚本（以管理员权限）
			print("\n" + "=" * 80)
			print("现在将自动执行 tscon 辅助脚本")
			print("=" * 80)
			print("")
			print("该脚本会自动:")
			print(f"  ✅ 允许 Python 进程 (PID: {current_pid}) 设置前台窗口")
			print("  ✅ 自动检测当前 RDP Session ID")
			print("  ✅ 执行 tscon 切换到 Console Session")
			print("  ⚠️  RDP 连接会立即断开")
			print("")
			print("=" * 80)

			input("\n按 Enter 启动脚本（将弹出 UAC 提示要求管理员权限）...")

			# 使用 PowerShell Start-Process 以管理员权限执行脚本
			print("\n[执行] 正在以管理员权限启动 PowerShell 脚本...")
			print(f"  脚本路径: {TSCON_SCRIPT_PATH.absolute()}")
			print(f"  参数: -PythonPid {current_pid}")

			try:
				import subprocess
				# 使用 Start-Process -Verb RunAs 来请求管理员权限
				# -NoExit 参数让窗口保持打开，方便查看执行结果
				powershell_cmd = [
					"powershell",
					"-Command",
					f"Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -NoExit -File \"{TSCON_SCRIPT_PATH.absolute()}\" -PythonPid {current_pid}' -Verb RunAs"
				]

				subprocess.Popen(powershell_cmd)

				print("[执行] ✅ 脚本已启动")
				print("[执行] ⚠️  请在弹出的 UAC 窗口中点击 '是' 来授予管理员权限")
				print("[执行] ⚠️  脚本执行后，RDP 连接会立即断开")
				print("")

			except Exception as e:
				print(f"[执行] ❌ 启动脚本失败: {e}")
				print("")
				print("请手动执行以下步骤：")
				print("1. 【在虚拟机里】打开管理员 PowerShell")
				print(f"2. 执行以下命令: .\\{TSCON_SCRIPT_PATH.name} -PythonPid {current_pid}")
				print("")

			# 注意: tscon 执行后 RDP 会断开，无法手动按键
			# 脚本将自动等待 Console Session 稳定后继续
			print("\n⚠️  注意: tscon 执行后，RDP 连接会断开，无法手动操作")
			print("     脚本将自动等待 Console Session 稳定后继续...")

			# 等待 30 秒让 Console Session 稳定
			wait_time = 30
			print(f"\n等待 {wait_time} 秒让 Console Session 稳定...")
			for i in range(wait_time, 0, -1):
				print(f"  倒计时: {i} 秒", end='\r')
				await asyncio.sleep(1)
			print("\n")

			# 循环测试
			loop_count = 0
			total_success = 0
			total_attempts = 0

			print("=" * 80)
			print(f"开始循环测试（每 {LOOP_INTERVAL} 秒一次，按 Ctrl+C 停止）")
			print("=" * 80)

			try:
				while True:
					loop_count += 1
					total_attempts += 1

					print(f"\n{'='*80}")
					print(f"第 {loop_count} 次测试 @ {time.strftime('%H:%M:%S')}")
					print(f"{'='*80}")

					# Step 1: 设置窗口焦点（使用 run_in_executor 在线程池中执行）
					print(f"\n[{loop_count}] Step 1: 设置浏览器窗口焦点")
					# import concurrent.futures
					# with concurrent.futures.ThreadPoolExecutor() as pool:
					# 	loop_ref = asyncio.get_event_loop()
					# 	focus_success = await loop_ref.run_in_executor(
					# 		pool, bring_window_to_foreground
					# 	)
					# if not focus_success:
					# 	print(f"[{loop_count}] ⚠️  警告: 未能设置窗口焦点")
					focus_success = bring_window_to_foreground()

					# 等待焦点传递完成
					await asyncio.sleep(0.3)

					# Step 2: 执行 CDP 点击
					print(f"\n[{loop_count}] Step 2: 执行 CDP 点击")
					click_success = await cdp_click_element(cdp, email_input, box)

					# Step 3: 检测 Popup（并行监控日志）
					print(f"\n[{loop_count}] Step 3: 检测 Popup (UIA + 日志)")

					popup_detected = False
					detection_duration = 3.0

					async def detect_popup_async():
						nonlocal popup_detected
						import concurrent.futures
						with concurrent.futures.ThreadPoolExecutor() as pool:
							loop = asyncio.get_event_loop()
							popup_detected = await loop.run_in_executor(
								pool, detect_popup_with_uia, detection_duration
							)

					detect_task = asyncio.create_task(detect_popup_async())

					# 日志监控循环
					start_time = time.time()
					log_show_detected = False
					log_hide_detected = False

					while time.time() - start_time < detection_duration:
						if log_monitor:
							new_logs = log_monitor.check_new_logs()
							if new_logs['show']:
								log_show_detected = True
							if new_logs['hide']:
								log_hide_detected = True
						await asyncio.sleep(0.1)

					await detect_task

					# Step 3.5: 点击空白处让 popup 消失并验证
					print(f"\n[{loop_count}] Step 3.5: 点击空白处让 popup 消失")
					popup_dismissed = await click_blank_to_dismiss_popup(page, box)

					# 检查 hide 日志
					if log_monitor:
						await asyncio.sleep(0.2)  # 等待日志写入
						new_logs = log_monitor.check_new_logs()
						if new_logs['hide']:
							log_hide_detected = True
							print(f"[{loop_count}] ✅ 检测到 Hide 日志")

					# Step 4: 总结本次结果
					print(f"\n[{loop_count}] 本次测试结果:")
					print(f"  - CDP 点击: {'✅' if click_success else '❌'}")
					print(f"  - 窗口焦点: {'✅' if focus_success else '❌'}")
					print(f"  - UIA 检测: {'✅ Popup 已显示' if popup_detected else '❌ Popup 未显示'}")
					print(f"  - UIA 消失: {'✅ Popup 已消失' if popup_dismissed else '❌ Popup 未消失'}")
					print(f"  - 日志 Show: {'✅' if log_show_detected else '❌'}")
					print(f"  - 日志 Hide: {'✅' if log_hide_detected else '❌'}")

					# 统计成功率
					if popup_detected or log_show_detected:
						total_success += 1
						print(f"\n  🎉 成功！")
					else:
						print(f"\n  ❌ 失败")

					print(f"\n  累计成功率: {total_success}/{total_attempts} ({total_success*100//total_attempts if total_attempts > 0 else 0}%)")

					# 等待下一次循环
					print(f"\n等待 {LOOP_INTERVAL} 秒后进行下一次测试...")
					for i in range(LOOP_INTERVAL, 0, -1):
						print(f"  倒计时: {i} 秒", end='\r')
						await asyncio.sleep(1)
					print()

			except KeyboardInterrupt:
				print("\n\n" + "=" * 80)
				print("测试已停止")
				print("=" * 80)

				print(f"\n最终统计:")
				print(f"  总测试次数: {total_attempts}")
				print(f"  成功次数: {total_success}")
				print(f"  失败次数: {total_attempts - total_success}")
				print(f"  成功率: {total_success*100//total_attempts if total_attempts > 0 else 0}%")

				if log_monitor:
					print(f"\n日志统计:")
					print(f"  Show 日志: {len(log_monitor.show_logs)} 条")
					print(f"  Hide 日志: {len(log_monitor.hide_logs)} 条")

			# 关闭连接
			await browser.close()
			print("\n[Playwright] 已断开连接")

	except Exception as e:
		print(f"\n❌ 测试出错: {e}")
		import traceback
		traceback.print_exc()


if __name__ == '__main__':
	asyncio.run(main())
