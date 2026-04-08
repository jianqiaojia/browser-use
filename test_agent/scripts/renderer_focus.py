"""
PostMessage helpers — 向 Chrome_RenderWidgetHostHWND 发送 Win32 消息。

用于在 CDP click 之前确保 renderer 获得焦点，触发 Edge autofill popup。
"""

import win32gui
import win32con
import win32process
import psutil


def _get_edge_pid() -> int | None:
	"""找到当前运行的 msedge.exe 主进程 PID。"""
	result = [None]

	def enum_cb(hwnd, _):
		if result[0]:
			return
		try:
			if win32gui.GetClassName(hwnd) != 'Chrome_WidgetWin_1':
				return
			if not win32gui.GetWindowText(hwnd):
				return
			_, pid = win32process.GetWindowThreadProcessId(hwnd)
			if psutil.Process(pid).name().lower() == 'msedge.exe':
				result[0] = pid
		except Exception:
			pass

	win32gui.EnumWindows(enum_cb, None)
	return result[0]


def _find_render_widget_hwnd(edge_pid: int) -> int | None:
	"""在 edge_pid 进程中找到 Chrome_RenderWidgetHostHWND 子窗口。"""
	render_hwnd: list[int | None] = [None]

	def enum_top(hwnd, _):
		try:
			_, pid = win32process.GetWindowThreadProcessId(hwnd)
			if pid != edge_pid or win32gui.GetClassName(hwnd) != 'Chrome_WidgetWin_1':
				return
			if not win32gui.GetWindowText(hwnd):
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


def postmsg_lbuttondown(vx: float, vy: float) -> bool:
	"""
	向 Chrome_RenderWidgetHostHWND 发送 WM_SETFOCUS + WM_LBUTTONDOWN/UP。
	绕开 CDP 合成事件，直接投递到 renderer 消息队列，确保 rwhv->HasFocus()。
	"""
	pid = _get_edge_pid()
	if not pid:
		print('[PostMsg] Edge PID not found')
		return False
	hwnd = _find_render_widget_hwnd(pid)
	if not hwnd:
		print('[PostMsg] Chrome_RenderWidgetHostHWND not found')
		return False

	left, top, _, _ = win32gui.GetWindowRect(hwnd)
	cx = int(vx) + left
	cy = int(vy) + top
	client_x, client_y = win32gui.ScreenToClient(hwnd, (cx, cy))
	lparam = client_x | (client_y << 16)

	win32gui.PostMessage(hwnd, win32con.WM_SETFOCUS, 0, 0)
	win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
	win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
	print(f'[PostMsg] WM_SETFOCUS + WM_LBUTTONDOWN → HWND={hwnd} client=({client_x}, {client_y})')
	return True
