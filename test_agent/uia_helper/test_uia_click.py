"""
测试 UIA Click 坐标计算

直接调用 uia_click.py 的坐标计算和点击逻辑来验证是否正确
"""

import asyncio
import sys
import os
import requests
from playwright.async_api import async_playwright

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_agent.config import config

async def test_uia_click():
	print("="*60)
	print("测试 UIA Click 坐标计算")
	print("="*60)

	async with async_playwright() as p:
		# 使用和项目一样的 Edge 启动配置
		print(f"\n使用 Edge 配置:")
		print(f"  User data dir: {config.user_data_dir}")
		print(f"  Profile: {config.profile}")
		print(f"  Edge path: {config.edge_path}")

		# 使用 launch_persistent_context 来支持 user_data_dir
		context = await p.chromium.launch_persistent_context(
			user_data_dir=config.user_data_dir,
			channel="msedge",
			headless=False,
			executable_path=config.edge_path,
			args=[
				'--start-maximized',
				f'--profile-directory={config.profile}',
				'--disable-blink-features=AutomationControlled',
			],
			no_viewport=True,
			ignore_https_errors=True,
			# 移除 --enable-automation 标志以隐藏 automation banner
			ignore_default_args=['--enable-automation'],
		)
		# 获取已经打开的第一个页面（launch_persistent_context 会自动打开一个页面）
		pages = context.pages
		if pages:
			page = pages[0]
		else:
			page = await context.new_page()

		print("\n请手动操作:")
		print("  1. 在打开的浏览器中导航到 Nike checkout 页面")
		print("  2. 确保浏览器窗口已最大化")
		print("  3. 等待页面完全加载")
		input("\n完成后按 Enter 继续...")

		# 重新获取当前激活的页面（因为用户可能打开了新标签页）
		pages = context.pages
		if pages:
			# 获取最后一个页面（通常是用户当前正在查看的页面）
			page = pages[-1]

		# 等待页面稳定
		await asyncio.sleep(0.5)

		# 确保页面已加载
		try:
			await page.wait_for_load_state('domcontentloaded', timeout=5000)
		except:
			pass  # 如果页面已经加载完成，忽略超时错误

		# 查找 email input 元素
		print("\n查找 email input 元素...")
		email_selector = 'input[type="email"]'

		# 获取元素的 id 或 name 属性（uia_click 需要这些）
		element_info = await page.evaluate(f'''() => {{
			const element = document.querySelector('{email_selector}');
			if (!element) return null;

			return {{
				id: element.id || '',
				name: element.name || '',
				tag: element.tagName.toLowerCase()
			}};
		}}''')

		if not element_info or (not element_info['id'] and not element_info['name']):
			print("\n❌ 未找到 email input 或元素缺少 id/name 属性")
			await context.close()
			return

		print(f"✅ 找到元素: {element_info['tag']}")
		if element_info['id']:
			print(f"  id: {element_info['id']}")
			selector = f"#{element_info['id']}"
		else:
			print(f"  name: {element_info['name']}")
			selector = f"[name=\"{element_info['name']}\"]"

		# 执行和 uia_click.py 一样的坐标计算
		print(f"\n{'='*60}")
		print("执行 UIA Click 坐标计算（与 uia_click.py 相同的逻辑）")
		print(f"{'='*60}")

		try:
			# 和 uia_click.py 一样的 JavaScript 评估
			js_data = await page.evaluate(f'''() => {{
				const element = document.querySelector('{selector}');
				if (!element) {{
					return {{ error: 'Element not found with selector: {selector}' }};
				}}

				const rect = element.getBoundingClientRect();

				// Get automation info bar height if it exists
				let automationBarHeight = 0;
				try {{
					const viewportTop = document.documentElement.clientTop || 0;
					automationBarHeight = viewportTop;
				}} catch (e) {{
					// Ignore errors
				}}

				return {{
					// Element viewport-relative coordinates
					rect: {{
						left: rect.left,
						top: rect.top,
						width: rect.width,
						height: rect.height,
						centerX: rect.left + rect.width / 2,
						centerY: rect.top + rect.height / 2
					}},
					// Window position on screen
					screenX: window.screenX,
					screenY: window.screenY,
					screenLeft: window.screenLeft,
					screenTop: window.screenTop,
					// Window dimensions
					outerHeight: window.outerHeight,
					innerHeight: window.innerHeight,
					outerWidth: window.outerWidth,
					innerWidth: window.innerWidth,
					// Page scroll position
					scrollX: window.scrollX || window.pageXOffset || 0,
					scrollY: window.scrollY || window.pageYOffset || 0,
					// Screen info
					screenWidth: window.screen.width,
					screenHeight: window.screen.height,
					devicePixelRatio: window.devicePixelRatio,
					// Automation bar height
					automationBarHeight: automationBarHeight,
				}};
			}}''')

			if 'error' in js_data:
				print(f"\n❌ {js_data['error']}")
				await context.close()
				return

			# 和 uia_click.py 一样的坐标计算
			js_rect = js_data['rect']
			viewport_x = js_rect['centerX']
			viewport_y = js_rect['centerY']

			scroll_x = float(js_data.get('scrollX', 0))
			scroll_y = float(js_data.get('scrollY', 0))

			window_x = float(js_data.get('screenLeft', js_data.get('screenX', 0)))
			window_y = float(js_data.get('screenTop', js_data.get('screenY', 0)))

			top_chrome_height = float(js_data['outerHeight']) - float(js_data['innerHeight'])
			automation_bar_height = float(js_data.get('automationBarHeight', 0))

			# 计算屏幕坐标（与 uia_click.py 完全相同）
			if window_x < 0:
				# Maximized window
				screen_x = int(abs(window_x) + viewport_x)
			else:
				# Non-maximized window
				screen_x = int(window_x + viewport_x)

			# Y coordinate
			screen_y = int(window_y + top_chrome_height + viewport_y)

			# 输出调试信息（与 uia_click.py 相同格式）
			is_maximized = window_x < 0
			border_offset = abs(window_x) if is_maximized else 0

			debug_info = f'''
UIA Click 坐标计算:
  Element: {element_info['tag']} id={element_info.get('id', '')} name={element_info.get('name', '')}

  Viewport Coordinates (from getBoundingClientRect):
    Center: ({viewport_x:.1f}, {viewport_y:.1f})
    Full rect: {js_rect}
    NOTE: These are relative to VISIBLE viewport (scroll already accounted for)

  Window Info:
    Position: screenLeft={window_x:.1f}, screenTop={window_y:.1f}
    Is Maximized: {is_maximized} (detected from screenLeft < 0)
    Border Offset: {border_offset:.1f}
    Window size: outer=({js_data.get('outerWidth', 0):.1f}, {js_data.get('outerHeight', 0):.1f}), inner=({js_data.get('innerWidth', 0):.1f}, {js_data.get('innerHeight', 0):.1f})
    Screen size: {js_data.get('screenWidth', 0):.0f}x{js_data.get('screenHeight', 0):.0f}
    DPI scaling: {js_data.get('devicePixelRatio', 1):.2f}x
    Top chrome height: {top_chrome_height:.1f}
    Automation bar height: {automation_bar_height:.1f}
    Page scroll: ({scroll_x:.1f}, {scroll_y:.1f}) [for info only - not used in calculation]

  Calculation:
    {'Maximized window:' if is_maximized else 'Normal window:'}
    screen_x = {'abs(' + f'{window_x:.1f}' + ')' if is_maximized else f'{window_x:.1f}'} + {viewport_x:.1f} = {screen_x}
    screen_y = {window_y:.1f} + {top_chrome_height:.1f} + {viewport_y:.1f} = {screen_y}

  Result:
    Final screen coords: ({screen_x}, {screen_y})
'''
			print(debug_info)

			# 调用 UIA Helper 执行真实点击
			print(f"\n{'='*60}")
			print("调用 UIA Helper 执行 OS 级别点击")
			print(f"{'='*60}")

			# 确保 UIA Helper 服务器正在运行
			try:
				response = requests.post(
					'http://localhost:3333/uia/click_at_position',
					json={
						'x': screen_x,
						'y': screen_y
					},
					timeout=5
				)
				response.raise_for_status()
				result = response.json()

				if result.get('success'):
					print(f"\n✅ UIA Click 成功!")
					print(f"   点击位置: ({screen_x}, {screen_y})")
					print(f"\n请观察:")
					print(f"  1. 鼠标是否移动到了 email input 的中心位置")
					print(f"  2. email input 是否获得了焦点")
					print(f"  3. Edge 的 Express Checkout popup 是否出现")
				else:
					print(f"\n❌ UIA Click 失败: {result.get('error', 'Unknown error')}")

			except requests.exceptions.ConnectionError:
				print("\n❌ 无法连接到 UIA Helper 服务器")
				print("   请确保 uia_server.py 正在运行在 http://localhost:3333")
			except Exception as e:
				print(f"\n❌ 调用 UIA Helper 出错: {str(e)}")

		except Exception as e:
			print(f"\n❌ 执行出错: {str(e)}")
			import traceback
			traceback.print_exc()

		print("\n按 Enter 关闭浏览器...")
		input()

		await context.close()

if __name__ == '__main__':
	asyncio.run(test_uia_click())
