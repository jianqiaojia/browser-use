"""
Quick Manual Click Test - 快速手动测试

使用你已经运行的 browser-use Agent 浏览器进行测试
"""

import asyncio
import ctypes
import win32gui
import win32con
import win32process
import win32api
import comtypes.client
from playwright.async_api import async_playwright


# 动态加载 UI Automation 类型库
def _get_uia_client():
	"""获取 UIAutomationClient 模块"""
	try:
		# 尝试导入已生成的模块
		from comtypes.gen import UIAutomationClient
		return UIAutomationClient
	except ImportError:
		# 如果没有生成，则动态生成
		print("正在生成 UI Automation 类型库...")
		import comtypes.client
		uia = comtypes.client.GetModule("UIAutomationCore.dll")
		from comtypes.gen import UIAutomationClient
		print("类型库生成完成")
		return UIAutomationClient


def bring_window_to_foreground(window_title_part: str = "Microsoft Edge"):
	"""
	Bring Edge window to foreground using UIA to find it reliably.

	This is CRITICAL! Edge checks HasFocus() before showing autofill popup:
	  if ((!rwhv || !rwhv->HasFocus()) && IsRootPopup()) {
	    Hide(SuggestionHidingReason::kNoFrameHasFocus);
	    return;
	  }
	"""
	try:
		# Initialize UI Automation
		UIAutomationClient = _get_uia_client()
		uia = comtypes.client.CreateObject(
			"{ff48dba4-60ef-4201-aa87-54103eef594e}",
			interface=UIAutomationClient.IUIAutomation
		)
		root = uia.GetRootElement()

		# Find all Chrome windows (Edge uses Chrome class)
		class_condition = uia.CreatePropertyCondition(
			UIAutomationClient.UIA_ClassNamePropertyId,
			"Chrome_WidgetWin_1"
		)
		windows = root.FindAll(
			UIAutomationClient.TreeScope_Children,
			class_condition
		)

		print(f"[Focus] Found {windows.Length} Chrome-based windows")

		# Find Edge window
		edge_hwnd = None
		for i in range(windows.Length):
			window = windows.GetElement(i)
			try:
				name = window.CurrentName
				print(f"[Focus] Window {i}: {name}")

				# Check if it's Edge
				if 'edge' in name.lower() or 'microsoft' in name.lower() or 'nike' in name.lower():
					edge_hwnd = window.CurrentNativeWindowHandle
					print(f"[Focus] ✅ Found Edge window: {name} (hwnd={edge_hwnd})")
					break
			except Exception as e:
				print(f"[Focus] Error checking window {i}: {e}")
				continue

		if not edge_hwnd:
			print(f"[Focus] ⚠️  Edge window not found")
			return False

		# Multi-step aggressive focus setting
		try:
			# Step 1: Restore if minimized
			if win32gui.IsIconic(edge_hwnd):
				print(f"[Focus] Restoring minimized window...")
				win32gui.ShowWindow(edge_hwnd, win32con.SW_RESTORE)

			# Step 2: Bring to top without activating
			print(f"[Focus] Bringing to top...")
			win32gui.SetWindowPos(edge_hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
			                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

			# Step 3: Attach to foreground thread to bypass restrictions
			print(f"[Focus] Attaching to foreground thread...")
			foreground_hwnd = win32gui.GetForegroundWindow()
			foreground_thread = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
			current_thread = win32api.GetCurrentThreadId()

			if foreground_thread != current_thread:
				win32process.AttachThreadInput(foreground_thread, current_thread, True)

			# Step 4: Actually set foreground
			print(f"[Focus] Setting foreground...")
			win32gui.SetForegroundWindow(edge_hwnd)
			win32gui.SetFocus(edge_hwnd)

			# Step 5: Detach threads
			if foreground_thread != current_thread:
				win32process.AttachThreadInput(foreground_thread, current_thread, False)

			print(f"[Focus] ✅ Edge window brought to foreground")
			return True

		except Exception as e:
			print(f"[Focus] ⚠️  Advanced focus setting failed: {e}")
			import traceback
			traceback.print_exc()
			return False

	except Exception as e:
		print(f"[Focus] ⚠️  Failed to set focus: {e}")
		import traceback
		traceback.print_exc()
		return False


async def main():
	print("\n" + "=" * 60)
	print("Quick Manual Click Test")
	print("=" * 60 + "\n")

	async with async_playwright() as p:
		# 连接到 CDP 端口 9222
		print("[Connect] Connecting to CDP port 9222...")
		browser = await p.chromium.connect_over_cdp("http://localhost:9222")
		page = browser.contexts[0].pages[0]
		print(f"[Connect] ✅ Connected to: {page.url}\n")

		# 简单的测试命令
		while True:
			print("\n" + "=" * 60)
			print("Commands:")
			print("  1 - Playwright click")
			print("  2 - CDP click (full sequence)")
			print("  3 - Show current URL")
			print("  q - Quit")
			print("=" * 60)

			cmd = input("\nEnter command: ").strip()

			if cmd == 'q':
				break

			elif cmd == '1':
				# selector = input("CSS selector (default: input[name='address.email']): ").strip()
				# if not selector:
				selector = 'input[name="address.email"]'

				print(f"\n[Click] Playwright clicking: {selector}")
				try:
					# CRITICAL: Bring window to foreground first!
					print("[Focus] Setting window focus...")
					bring_window_to_foreground()
					await asyncio.sleep(0.2)  # Wait for focus to settle

					element = page.locator(selector)

					await element.click(no_wait_after=True)
					print("[Click] ✅ Click done")

					await element.focus()
					print("[Focus] ✅ Element focused")

					print("[Info] 👀 Check if autofill popup appeared!")
				except Exception as e:
					print(f"[Click] ❌ Error: {e}")

			elif cmd == '2':
				# selector = input("CSS selector (default: input[name='address.email']): ").strip()
				# if not selector:
				selector = 'input[name="address.email"]'

				print(f"\n[Click] CDP clicking: {selector}")
				try:
					# CRITICAL: Bring window to foreground first!
					print("[Focus] Setting window focus...")
					bring_window_to_foreground()
					await asyncio.sleep(3)  # Wait for focus to settle

					element = page.locator(selector)

					box = await element.bounding_box()
					x = box['x'] + box['width'] / 2
					y = box['y'] + box['height'] / 2

					cdp = await page.context.new_cdp_session(page)

					print(f"[Click] mouseMoved to ({x:.1f}, {y:.1f})")
					await cdp.send('Input.dispatchMouseEvent', {
						'type': 'mouseMoved',
						'x': x,
						'y': y
					})

					print(f"[Click] mousePressed at ({x:.1f}, {y:.1f})")
					await cdp.send('Input.dispatchMouseEvent', {
						'type': 'mousePressed',
						'x': x,
						'y': y,
						'button': 'left',
						'clickCount': 1
					})

					print(f"[Click] mouseReleased at ({x:.1f}, {y:.1f})")
					await cdp.send('Input.dispatchMouseEvent', {
						'type': 'mouseReleased',
						'x': x,
						'y': y,
						'button': 'left',
						'clickCount': 1
					})

					print("[Click] ✅ CDP sequence done")

					print("[Info] 👀 Check if autofill popup appeared!")
				except Exception as e:
					print(f"[Click] ❌ Error: {e}")

			elif cmd == '3':
				print(f"\n[URL] {page.url}")

			else:
				print("\n⚠️  Invalid command")

	print("\n[Exit] Bye! 👋\n")


if __name__ == '__main__':
	asyncio.run(main())
