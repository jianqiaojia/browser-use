"""
手动测试 Phase 2 Replay

用法：
  1. 手动在浏览器里导航到 Nike checkout 页面（payment 步骤）
  2. 运行此脚本
  3. 按 Enter 开始 Phase 2 replay

这样可以绕过 Phase 1，直接测试 ReplayManager 的 replay/heal 逻辑。
"""

import asyncio
import sys
import os
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)-8s [%(name)s] %(message)s')

# Fix UTF-8 on Windows
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
	sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
	sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

# 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import test_agent.llm.strip_patch   # noqa: F401
import test_agent.llm.litellm_patch  # noqa: F401

from pathlib import Path
from browser_use import BrowserProfile, BrowserSession, Tools
from test_agent.config import config
from test_agent.llm.llm_config import get_claude_sonnet as get_claude
from test_agent.register_custom_actions import register_custom_actions
from test_agent.scripts.task_builder import load_preambles, build_checkout_task
from test_agent.scripts.browser_focus_manager import BrowserFocusManager
from test_agent.replay.replay_manager import ReplayManager
from test_agent.models import TestCase


async def main():
	print('=' * 60)
	print('Phase 2 Replay 调试脚本')
	print('=' * 60)

	# 固定测试用例名，对应 nike_autofill_signed_in.replay.json
	test_case_name = 'Nike_autofill_Signed_In'
	replay_path = Path(__file__).parent.parent.parent / 'test_case' / 'nike_autofill_signed_in.replay.json'

	print(f'\nReplay 文件: {replay_path}')
	print(f'存在: {replay_path.exists()}')

	# 构造 checkout task
	_, checkout_preamble = load_preambles()
	test_case = TestCase(
		name=test_case_name,
		checkout_guidance=(
			'To trigger the autofill popup, focus the email or firstName field (do not use payment/card fields). '
			'Nike may show a saved address summary with the form collapsed — click Edit on the existing address to expand it, do not add a new one.'
		),
	)

	# 需要 site_test 的 site_checkout_guidance 和 domain，从 nike.test.json 读取
	import json
	nike_test_path = Path(__file__).parent.parent.parent / 'test_case' / 'nike.test.json'
	nike_data = json.loads(nike_test_path.read_text(encoding='utf-8'))
	site_checkout_guidance = nike_data.get('site_checkout_guidance', '')
	domain = nike_data.get('domain', 'nike.com')

	checkout_task = build_checkout_task(test_case, checkout_preamble, site_checkout_guidance, domain)

	print(f'\nCheckout task 已构建（{len(checkout_task)} 字符）')

	# 初始化 LLM 和工具
	print('\n[Init] 初始化 LLM...')
	llm = get_claude(model='claude-opus-4-5', base_url='http://localhost:5000')

	print('[Tools] 注册 custom actions...')
	tools = Tools()
	register_custom_actions(tools)

	# 浏览器配置（keep_alive=True，因为我们要附着到已有窗口）
	browser_config = config.get_browser_profile_config()
	browser_profile = BrowserProfile(**browser_config)

	# 启动浏览器 session（脚本自己开浏览器）
	keep_alive_profile = browser_profile.model_copy(update={'keep_alive': True})
	browser_session = BrowserSession(browser_profile=keep_alive_profile)
	await browser_session.start()

	# 启动 FocusManager（后台线程，保持 Edge 窗口置顶）
	focus_manager = BrowserFocusManager(
		browser_process_name='msedge.exe',
		keep_topmost=True,
		auto_restore_focus=False,
		check_interval=2.0,
	)
	loop = asyncio.get_event_loop()
	loop.run_in_executor(None, focus_manager.start_sync)
	print('[FocusManager] 已在后台启动')

	print('\n' + '=' * 60)
	print('浏览器已启动，请手动操作：')
	print('  1. 登录 Nike 并导航到 checkout 页面')
	print('  2. 页面应处于 Payment 步骤（Delivery Options 已完成）')
	print('  3. 不要点击任何东西')
	print('=' * 60)
	# input('\n准备好后按 Enter 开始 Phase 2 replay...')

	try:
		manager = ReplayManager(
			replay_path=replay_path,
			checkout_task=checkout_task,
			llm=llm,
			browser_profile=browser_profile,
			tools=tools,
		)

		print(f'\n[Phase 2] 开始 replay: {replay_path.name}')
		import time
		t0 = time.perf_counter()
		success = await manager.run(browser_session)
		elapsed = time.perf_counter() - t0

		print(f'\n{"=" * 60}')
		print(f'结果: {"✅ PASS" if success else "❌ FAIL"}')
		print(f'耗时: {elapsed:.1f}s')
		print('=' * 60)

	finally:
		try:
			await browser_session.stop()
		except Exception:
			pass
		focus_manager.stop()
		print('[FocusManager] 已停止')


if __name__ == '__main__':
	import warnings
	warnings.filterwarnings('ignore', category=ResourceWarning)
	asyncio.run(main())
