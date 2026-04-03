"""
PostMessage Click Action

通过 PostMessage(WM_LBUTTONDOWN/UP) 发送鼠标消息到 Chrome_RenderWidgetHostHWND，
触发 Edge autofill popup。

原理：
- CDP dispatchMouseEvent 是合成事件，不经过真实 Win32 消息队列
- Edge autofill popup 在 ShowWalletECInlineExperience 里检查 rwhv->HasFocus()
- rwhv->HasFocus() 依赖 WM_SETFOCUS 发到 Chrome_RenderWidgetHostHWND
- PostMessage 直接投递到 renderer 子窗口的消息队列，绕开前台焦点限制
- 坐标使用 DOM element 的视口坐标，换算为 Chrome_RenderWidgetHostHWND 客户区坐标
"""

import asyncio
import ctypes
import win32gui
import win32con
import win32process
import psutil
from pydantic import BaseModel, Field
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.agent.views import ActionResult


class PostMsgClickAction(BaseModel):
	index: int = Field(description='DOM element index to click via PostMessage WM_LBUTTONDOWN to Chrome_RenderWidgetHostHWND')


def _find_render_widget_hwnd(edge_pid: int) -> int | None:
	"""
	在 edge_pid 进程的所有顶层 Chrome_WidgetWin_1 子窗口中，
	找到 Chrome_RenderWidgetHostHWND 子窗口并返回其 HWND。
	"""
	render_hwnd = [None]

	def enum_top(hwnd, _):
		try:
			_, pid = win32process.GetWindowThreadProcessId(hwnd)
			if pid != edge_pid:
				return
			if win32gui.GetClassName(hwnd) != 'Chrome_WidgetWin_1':
				return
			title = win32gui.GetWindowText(hwnd)
			if not title:
				return

			def enum_child(child_hwnd, __):
				if render_hwnd[0]:
					return
				try:
					if win32gui.GetClassName(child_hwnd) == 'Chrome_RenderWidgetHostHWND':
						render_hwnd[0] = child_hwnd
				except Exception:
					pass

			win32gui.EnumChildWindows(hwnd, enum_child, None)
		except Exception:
			pass

	win32gui.EnumWindows(enum_top, None)
	return render_hwnd[0]


def _get_edge_pid() -> int | None:
	"""找到当前运行的 msedge.exe 主进程 PID（有标题的窗口对应的进程）。"""
	result = [None]

	def enum_cb(hwnd, _):
		if result[0]:
			return
		try:
			if win32gui.GetClassName(hwnd) != 'Chrome_WidgetWin_1':
				return
			title = win32gui.GetWindowText(hwnd)
			if not title:
				return
			_, pid = win32process.GetWindowThreadProcessId(hwnd)
			if psutil.Process(pid).name().lower() == 'msedge.exe':
				result[0] = pid
		except Exception:
			pass

	win32gui.EnumWindows(enum_cb, None)
	return result[0]


def _viewport_to_client(hwnd: int, vx: float, vy: float) -> tuple[int, int]:
	"""
	将视口坐标转换为 hwnd 的客户区坐标。
	视口坐标已经是相对于浏览器内容区域的，需要映射到 hwnd 的客户区。
	"""
	# 获取 hwnd 的屏幕坐标
	left, top, right, bottom = win32gui.GetWindowRect(hwnd)
	# Chrome_RenderWidgetHostHWND 的左上角即为视口原点
	cx = int(vx) + left
	cy = int(vy) + top
	# 转为客户区坐标
	client_x, client_y = win32gui.ScreenToClient(hwnd, (cx, cy))
	return client_x, client_y


async def execute_postmsg_click(
	params: PostMsgClickAction,
	browser_session: BrowserSession,
) -> ActionResult:
	index = params.index

	element = await browser_session.get_dom_element_by_index(index)
	if not element:
		return ActionResult(error=f'Element {index} not found', include_in_memory=True, success=False)

	page = await browser_session.get_current_page()
	if page is None:
		return ActionResult(error='Could not get current page', include_in_memory=True, success=False)

	tag = element.tag_name
	attrs = []
	for k in ('type', 'id', 'name'):
		if element.attributes.get(k):
			attrs.append(f'{k}={element.attributes[k]}')
	attr_str = ' '.join(attrs)
	print(f'\n[PostMsg Click] Target: {tag} {attr_str}')

	try:
		# 获取元素视口坐标
		element_id = element.attributes.get('id', '')
		element_name = element.attributes.get('name', '')
		if element_id:
			selector = f'#{element_id}'
		elif element_name:
			selector = f'[name="{element_name}"]'
		else:
			return ActionResult(error='Element must have id or name', include_in_memory=True, success=False)

		box = await page.evaluate(f'''() => {{
			const el = document.querySelector('{selector}');
			if (!el) return {{error: 'not found'}};
			const r = el.getBoundingClientRect();
			return {{x: r.left + r.width / 2, y: r.top + r.height / 2}};
		}}''')
		if isinstance(box, dict) and 'error' in box:
			return ActionResult(error=f'Element not found: {selector}', include_in_memory=True, success=False)

		vx, vy = float(box['x']), float(box['y'])
		print(f'[PostMsg Click] Viewport coords: ({vx:.1f}, {vy:.1f})')

		# 找 Chrome_RenderWidgetHostHWND
		pid = _get_edge_pid()
		if not pid:
			return ActionResult(error='Edge process not found', include_in_memory=True, success=False)

		hwnd = _find_render_widget_hwnd(pid)
		if not hwnd:
			return ActionResult(error='Chrome_RenderWidgetHostHWND not found', include_in_memory=True, success=False)

		cx, cy = _viewport_to_client(hwnd, vx, vy)
		lparam = win32con.MAKELONG(cx, cy)
		print(f'[PostMsg Click] HWND={hwnd}, client coords: ({cx}, {cy})')

		# Blur 当前焦点元素，确保 mousedown 触发 focus change
		await page.evaluate("""() => {
			const a = document.activeElement;
			if (a && a !== document.body) a.blur();
		}""")
		await asyncio.sleep(0.05)

		# PostMessage WM_LBUTTONDOWN → WM_LBUTTONUP
		win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
		await asyncio.sleep(0.08)
		win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)

		print(f'[PostMsg Click] ✅ PostMessage sent')
		msg = f'✅ PostMessage click: {tag} {attr_str} at viewport ({vx:.1f}, {vy:.1f})'
		return ActionResult(extracted_content=msg, include_in_memory=True)

	except Exception as e:
		import traceback
		traceback.print_exc()
		return ActionResult(error=f'❌ PostMessage click failed: {e}', include_in_memory=True, success=False)


def register_postmsg_click(registry: Registry) -> None:
	@registry.action(
		description=(
			'Click an input field using Win32 PostMessage(WM_LBUTTONDOWN) to Chrome_RenderWidgetHostHWND. '
			'More reliable than cdp_click for triggering Edge autofill popup when focus is held by overlays. '
			'Use as fallback if cdp_click fails to trigger the popup.'
		),
		param_model=PostMsgClickAction,
	)
	async def postmsg_click(
		params: PostMsgClickAction,
		browser_session: BrowserSession,
	) -> ActionResult:
		return await execute_postmsg_click(params, browser_session)
