"""
CDP Click Action with Window Focus Management

This action uses CDP mouse events with automatic window focus management
to reliably trigger browser autofill popups. This is the solution that
works reliably for Edge autofill.

Key features:
1. Uses UIA to find and bring browser window to foreground
2. Executes complete CDP mouse sequence (mouseMoved → mousePressed → mouseReleased)
3. Ensures window has focus before click (required for Edge autofill)
"""

import asyncio
import win32gui
import win32con
import win32process
import win32api
import comtypes.client
from typing import Optional
from pydantic import BaseModel, Field
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.agent.views import ActionResult


# 动态加载 UI Automation 类型库
def _get_uia_client():
	"""获取 UIAutomationClient 模块"""
	try:
		# 尝试导入已生成的模块
		from comtypes.gen import UIAutomationClient
		return UIAutomationClient
	except ImportError:
		# 如果没有生成，则动态生成
		print("[UIA] 正在生成 UI Automation 类型库...")
		uia = comtypes.client.GetModule("UIAutomationCore.dll")
		from comtypes.gen import UIAutomationClient
		print("[UIA] 类型库生成完成")
		return UIAutomationClient


def bring_window_to_foreground() -> bool:
	"""
	Bring browser window to foreground using UIA.

	This is CRITICAL! Edge checks HasFocus() before showing autofill popup:
	  if ((!rwhv || !rwhv->HasFocus()) && IsRootPopup()) {
	    Hide(SuggestionHidingReason::kNoFrameHasFocus);
	    return;
	  }

	Returns:
		True if window was brought to foreground, False otherwise
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
				# Check if it's Edge (look for common keywords)
				if any(keyword in name.lower() for keyword in ['edge', 'microsoft', 'chrome', 'checkout', 'nike']):
					edge_hwnd = window.CurrentNativeWindowHandle
					print(f"[Focus] ✅ Found browser window: {name} (hwnd={edge_hwnd})")
					break
			except Exception as e:
				continue

		if not edge_hwnd:
			print(f"[Focus] ⚠️  Browser window not found")
			return False

		# Multi-step aggressive focus setting
		try:
			# Step 1: Restore if minimized
			if win32gui.IsIconic(edge_hwnd):
				print(f"[Focus] Restoring minimized window...")
				win32gui.ShowWindow(edge_hwnd, win32con.SW_RESTORE)

			# Step 2: Bring to top
			win32gui.SetWindowPos(edge_hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
			                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

			# Step 3: Attach to foreground thread to bypass restrictions
			foreground_hwnd = win32gui.GetForegroundWindow()
			foreground_thread = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
			current_thread = win32api.GetCurrentThreadId()

			if foreground_thread != current_thread:
				win32process.AttachThreadInput(foreground_thread, current_thread, True)

			# Step 4: Set foreground
			win32gui.SetForegroundWindow(edge_hwnd)
			# win32gui.SetFocus(edge_hwnd)

			# Step 5: Detach threads
			if foreground_thread != current_thread:
				win32process.AttachThreadInput(foreground_thread, current_thread, False)

			print(f"[Focus] ✅ Browser window brought to foreground")
			return True

		except Exception as e:
			print(f"[Focus] ⚠️  Focus setting failed: {e}")
			return False

	except Exception as e:
		print(f"[Focus] ⚠️  Failed to bring window to foreground: {e}")
		return False


class CDPClickAction(BaseModel):
	"""CDP click action with window focus management."""

	index: int = Field(
		description='DOM element index to click via CDP with focus management'
	)


async def execute_cdp_click(
	params: CDPClickAction,
	browser_session: BrowserSession,
) -> ActionResult:
	"""
	Execute CDP click with automatic window focus management.

	This implementation:
	1. Brings browser window to foreground using UIA
	2. Gets element bounding box
	3. Executes complete CDP mouse sequence
	4. Triggers Edge autofill popup reliably

	Args:
		params: Click parameters (element index)
		browser_session: Browser session

	Returns:
		ActionResult with success/error message
	"""
	index = params.index

	# Get element from browser_session
	element = await browser_session.get_dom_element_by_index(index)
	if not element:
		return ActionResult(
			error=f'Element with index {index} not found',
			include_in_memory=True,
			success=False
		)

	# Get browser page
	page = await browser_session.get_current_page()
	if page is None:
		return ActionResult(
			error='Could not get current page from browser session',
			include_in_memory=True,
			success=False
		)

	# Build element description for logging
	tag = element.tag_name
	attrs = []
	if element.attributes.get('type'):
		attrs.append(f"type={element.attributes['type']}")
	if element.attributes.get('id'):
		attrs.append(f"id={element.attributes['id']}")
	if element.attributes.get('name'):
		attrs.append(f"name={element.attributes['name']}")
	attr_str = ' '.join(attrs) if attrs else ''

	print(f"\n[CDP Click] Target: {tag} {attr_str}")

	try:
		# CRITICAL Step 1: Bring window to foreground
		print(f"[CDP Click] Step 1: Setting window focus...")
		focus_success = bring_window_to_foreground()
		if not focus_success:
			print(f"[CDP Click] ⚠️  Warning: Failed to set window focus, click may not trigger autofill")

		# Wait for focus to settle
		await asyncio.sleep(0.3)

		# Step 2: Get element bounding box using JavaScript
		print(f"[CDP Click] Step 2: Getting element coordinates...")

		# Build selector - prefer id, fallback to name
		element_id = element.attributes.get('id', '')
		element_name = element.attributes.get('name', '')

		if element_id:
			selector = f'#{element_id}'
		elif element_name:
			selector = f'[name="{element_name}"]'
		else:
			return ActionResult(
				error='Element must have either id or name attribute for CDP click',
				include_in_memory=True,
				success=False
			)

		# Use JavaScript to get bounding box
		js_code = f'''() => {{
			const element = document.querySelector('{selector}');
			if (!element) {{
				return {{ error: 'Element not found' }};
			}}
			const rect = element.getBoundingClientRect();
			return {{
				x: rect.left + rect.width / 2,
				y: rect.top + rect.height / 2
			}};
		}}'''

		result = await page.evaluate(js_code)

		# Parse result
		if isinstance(result, str):
			import json
			box = json.loads(result)
		else:
			box = result

		if isinstance(box, dict) and 'error' in box:
			return ActionResult(
				error=f'Element not found with selector {selector}',
				include_in_memory=True,
				success=False
			)

		x = float(box['x'])
		y = float(box['y'])

		print(f"[CDP Click] Element center: ({x:.1f}, {y:.1f})")

		# Step 3: Execute CDP mouse sequence
		print(f"[CDP Click] Step 3: Executing CDP mouse sequence...")

		session_id = await page.session_id

		# mouseMoved
		await page._client.send.Input.dispatchMouseEvent(
			params={'type': 'mouseMoved', 'x': x, 'y': y},
			session_id=session_id
		)
		await asyncio.sleep(0.05)

		# mousePressed
		await page._client.send.Input.dispatchMouseEvent(
			params={'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1},
			session_id=session_id
		)
		await asyncio.sleep(0.08)

		# mouseReleased
		await page._client.send.Input.dispatchMouseEvent(
			params={'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1},
			session_id=session_id
		)

		print(f"[CDP Click] ✅ CDP click sequence completed")

		msg = f'✅ CDP click executed with focus: {tag} {attr_str} at viewport ({x:.1f}, {y:.1f})'

		return ActionResult(
			extracted_content=msg,
			include_in_memory=True,
		)

	except Exception as e:
		import traceback
		traceback.print_exc()
		return ActionResult(
			error=f'❌ CDP click failed: {str(e)}',
			include_in_memory=True,
			success=False
		)


def register_cdp_click(registry: Registry) -> None:
	"""
	Register the cdp_click action to the tools registry.

	Usage:
		from browser_use import Tools
		from test_agent.custom_actions.cdp_click import register_cdp_click

		tools = Tools()
		register_cdp_click(tools.registry)
	"""

	@registry.action(
		description='Click element using CDP with automatic window focus management (reliable for Edge autofill)',
		param_model=CDPClickAction,
	)
	async def cdp_click(
		params: CDPClickAction,
		browser_session: BrowserSession,
	) -> ActionResult:
		"""
		Execute CDP click with window focus management.

		This ensures the browser window has focus before clicking,
		which is required for Edge autofill popups to appear.

		Args:
			params: Click parameters (element index)
			browser_session: Browser session

		Returns:
			ActionResult with success/error
		"""
		return await execute_cdp_click(params, browser_session)
