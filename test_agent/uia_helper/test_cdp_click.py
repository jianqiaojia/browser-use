"""
测试 browser-use 标准 CDP click 方案

这个脚本使用 browser-use 相同的 CDP click 实现方式
来测试是否能触发 Edge 的 autofill popup
"""

import asyncio
import sys
import os
from playwright.async_api import async_playwright

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_agent.config import config

async def test_cdp_click():
	print("="*60)
	print("测试 browser-use 标准 CDP Click")
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
		print("  3. 确保 Edge 已保存至少一个地址")
		print("  4. 等待页面完全加载")
		print("  5. 确保停留在包含 email input 的页面上 (不要刷新页面)")
		input("\n完成后按 Enter 继续测试...")

		# 重新获取当前激活的页面（因为用户可能打开了新标签页）
		pages = context.pages
		if pages:
			# 获取最后一个页面（通常是用户当前正在查看的页面）
			page = pages[-1]

		# 等待页面稳定
		print("\n等待页面稳定...")
		await asyncio.sleep(1)

		# 查找 email input - 支持多种选择器
		email_selectors = [
			'[data-attr*=AddressForm] input#email',  # 用户提供的精确选择器
			'input[type="email"]',
			'input#email',
			'input[name="email"]',
		]

		email_input = None
		email_selector = None

		print("\n正在查找 email input...")
		for selector in email_selectors:
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
			print("提示: 请确保:")
			print("  1. 页面已完全加载")
			print("  2. email input 元素在当前页面中可见")
			print("  3. 没有发生页面跳转或刷新")
			await context.close()
			return

		print(f"\n✅ 使用选择器: {email_selector}")

		# 获取元素的位置信息
		try:
			box = await email_input.bounding_box()
			if not box:
				print("\n❌ 元素没有边界框 (可能不可见)")
				await context.close()
				return

			print(f"\n元素位置:")
			print(f"  x: {box['x']:.1f}, y: {box['y']:.1f}")
			print(f"  width: {box['width']:.1f}, height: {box['height']:.1f}")
			print(f"  center: ({box['x'] + box['width']/2:.1f}, {box['y'] + box['height']/2:.1f})")
		except Exception as e:
			print(f"\n❌ 获取元素位置失败: {e}")
			await context.close()
			return

		# 测试方法：browser-use 标准 CDP click
		print(f"\n{'='*60}")
		print("开始测试: browser-use 标准 CDP Click")
		print(f"{'='*60}")

		try:
			# 获取 CDP session
			cdp = await context.new_cdp_session(page)

			# 计算点击位置（元素中心）
			center_x = box['x'] + box['width'] / 2
			center_y = box['y'] + box['height'] / 2

			print(f"\n步骤 1: 滚动元素到视野内")
			# 使用 Playwright 的滚动功能
			await email_input.scroll_into_view_if_needed()
			await asyncio.sleep(0.05)

			print(f"步骤 2: 移动鼠标到元素中心 ({center_x:.1f}, {center_y:.1f})")
			await cdp.send('Input.dispatchMouseEvent', {
				'type': 'mouseMoved',
				'x': center_x,
				'y': center_y,
			})
			await asyncio.sleep(0.05)

			print(f"步骤 3: 鼠标按下 (mousePressed)")
			try:
				await asyncio.wait_for(
					cdp.send('Input.dispatchMouseEvent', {
						'type': 'mousePressed',
						'x': center_x,
						'y': center_y,
						'button': 'left',
						'clickCount': 1,
						'modifiers': 0,
					}),
					timeout=1.0
				)
				await asyncio.sleep(0.08)
			except asyncio.TimeoutError:
				print("  ⚠️  mousePressed 超时，继续执行")

			print(f"步骤 4: 鼠标释放 (mouseReleased)")
			try:
				await asyncio.wait_for(
					cdp.send('Input.dispatchMouseEvent', {
						'type': 'mouseReleased',
						'x': center_x,
						'y': center_y,
						'button': 'left',
						'clickCount': 1,
						'modifiers': 0,
					}),
					timeout=3.0
				)
			except asyncio.TimeoutError:
				print("  ⚠️  mouseReleased 超时")

			print(f"\n✅ browser-use 标准 CDP click 完成")

			# 等待用户观察
			print(f"\n{'='*60}")
			print("请观察:")
			print("  1. Email input 是否获得了焦点（有光标闪烁）")
			print("  2. Edge 的 Express Checkout popup 是否出现")
			print(f"{'='*60}")

			wait_result = input("\nPopup 是否出现了? (y/n): ").strip().lower()

			if wait_result == 'y':
				print("\n✅ 成功! browser-use 标准 CDP click 方法有效!")
			else:
				print("\n❌ 失败: browser-use 标准 CDP click 没有触发 popup")
				print("\n可能的原因:")
				print("  1. 标准 CDP click 不会触发浏览器 autofill (需要 OS 级别点击)")
				print("  2. 需要在 mousePressed 和 mouseReleased 之间调用 element.focus()")
				print("  3. 页面检测到了自动化行为")

		except Exception as e:
			print(f"\n❌ 执行出错: {str(e)}")
			import traceback
			traceback.print_exc()

		print("\n按 Enter 关闭浏览器...")
		input()

		await context.close()

if __name__ == '__main__':
	asyncio.run(test_cdp_click())
