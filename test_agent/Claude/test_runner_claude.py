"""
Test runner using Claude Sonnet via MicrosoftAI LLM Proxy

Auto-discovers and runs all *.test.json files in test_case/ directory.
Uses Claude Sonnet instead of Azure OpenAI for better JSON output reliability.
"""
import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Any, Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Apply patches FIRST
import test_agent.Claude.integration.strip_patch  # noqa: F401
import test_agent.Claude.integration.litellm_patch  # noqa: F401

from browser_use import Agent, BrowserProfile
from test_agent.Claude.integration.llm_config import get_claude_sonnet
from test_agent.config import config
from test_agent.view import TestCase, ECTest, TestStep
from test_agent.register_custom_actions import register_custom_actions
from test_agent.utils.browser_focus_manager import BrowserFocusManager


def build_task_from_steps(steps: list[TestStep]) -> str:
	"""Build task description from test steps.

	Args:
		steps: List of test steps

	Returns:
		Task description string
	"""
	task_parts = []
	for step in steps:
		task_parts.append(f"{step.step_name}: {step.step_description}")
	return "\n".join(task_parts)


async def run_test_case(
	llm: Any,
	test: TestCase,
	trigger_id: str,
	run_id: int,
	focus_manager: Optional[BrowserFocusManager] = None
) -> bool:
	"""Execute a test case using Claude.

	Args:
		llm: Language model to use for the agent
		test: Test case to execute
		trigger_id: Identifier for the test trigger
		run_id: Run identifier
		focus_manager: Optional browser focus manager instance

	Returns:
		True if test passed, False otherwise
	"""
	print(f"\n{'='*60}")
	print(f"Test Case: {test.test_case_name}")
	print(f"Description: {test.test_case_description}")
	print(f"Trigger ID: {trigger_id}, Run ID: {run_id}")
	print(f"{'='*60}")

	try:
		# Build task from steps
		task = build_task_from_steps(test.steps)
		print(f"\n[Task]\n{task}\n")

		# Get browser config
		browser_config = config.get_browser_profile_config()

		# Get proxy if enabled
		proxy_settings = await config.get_proxy_for_browser()
		if proxy_settings:
			browser_config['proxy'] = proxy_settings
			print(f"[Proxy] Using proxy: {proxy_settings.server}")

		# Create Browser Profile
		browser_profile = BrowserProfile(**browser_config)

		# Create Tools and register custom actions BEFORE creating Agent
		print("[Tools] Registering custom actions...")
		from browser_use import Tools
		tools = Tools()
		register_custom_actions(tools)

		# Create and run Agent with pre-configured tools
		print("[Agent] Creating agent with Claude Sonnet...")
		agent = Agent(
			task=task,
			llm=llm,
			browser_profile=browser_profile,
			tools=tools,  # Pass tools with custom actions
			max_actions_per_step=config.max_actions_per_step,
			use_vision=config.vision_enabled,
		)

		# Start focus manager if provided (in background thread, non-blocking)
		if focus_manager:
			print("[FocusManager] Starting browser focus management in background...")
			# 在后台线程启动，不阻塞主流程
			import concurrent.futures
			loop = asyncio.get_event_loop()
			focus_task = loop.run_in_executor(
				None,  # 使用默认 ThreadPoolExecutor
				focus_manager.start_sync  # 同步版本的 start
			)
			# 不等待完成，让它在后台运行
			print("[FocusManager] Focus manager starting in background (non-blocking)...")

		# Run test
		print("[Run] Executing test...")
		history = await agent.run(max_steps=config.max_steps)

		# Stop focus manager after test completes
		if focus_manager:
			focus_manager.stop()
			print("[FocusManager] Focus manager stopped")

		# Save history IMMEDIATELY after test completes, before any other operations
		safe_name = test.test_case_name.replace(" ", "_").replace("-", "_").lower()
		history_file = f"test_case/{safe_name}_claude.history.json"

		print(f"\n[Save] Saving history to {history_file}")
		try:
			agent.save_history(history_file)
			print(f"[Save] ✅ History saved successfully")
		except Exception as save_error:
			print(f"[Save] ⚠️ Error saving history: {save_error}")
			# Try to save with error information
			try:
				import json
				from pathlib import Path
				Path(history_file).parent.mkdir(parents=True, exist_ok=True)
				with open(history_file, 'w', encoding='utf-8') as f:
					json.dump({
						"error": f"Failed to save full history: {save_error}",
						"partial_history": str(history)[:10000]  # Save first 10k chars as fallback
					}, f, indent=2)
				print(f"[Save] ⚠️ Saved partial history as fallback")
			except Exception as fallback_error:
				print(f"[Save] ❌ Could not save even partial history: {fallback_error}")

		# Check results
		success = history.is_successful()

		# Mark proxy result if used
		if config.use_proxy and config._current_proxy:
			# Simple success/failure based on test result
			await config.mark_proxy_result(success=bool(success), response_time=0.0)
			print(f"[Proxy] Marked result: {'success' if success else 'failure'}")

		# Print statistics
		print(f"\n[Stats] Test Statistics:")
		print(f"  Total steps: {len(history.history)}")
		print(f"  Total actions: {len(history.action_names())}")
		print(f"  Action types: {set(history.action_names())}")

		if success:
			print("\n[OK] Test PASSED")
		else:
			print("\n[WARN] Test completed with warnings")
			if history.errors():
				print("  Errors:")
				for error in history.errors():
					if error:
						print(f"    - {error}")

		return success if success is not None else False

	except Exception as e:
		print(f"\n[FAIL] Error running test: {str(e)}")
		import traceback
		traceback.print_exc()
		return False


def load_test_file(test_file: str) -> ECTest:
	"""Load test case from JSON file.

	Args:
		test_file: Path to test JSON file

	Returns:
		ECTest object

	Raises:
		FileNotFoundError: If test file not found
	"""
	print(f"\n{'='*60}")
	print(f"Loading test file: {test_file}")
	print(f"{'='*60}")

	test_path = Path(test_file)
	if not test_path.exists():
		raise FileNotFoundError(f"Test file not found: {test_file}")

	with open(test_path, 'r', encoding='utf-8') as f:
		test_data = json.load(f)

	return ECTest(**test_data)


async def run_test_file(
	test_file: str,
	llm: Any,
	trigger_id: str = "manual",
	run_id: int = 1,
	enable_focus_manager: bool = False
) -> bool:
	"""Run tests from a test file.

	Args:
		test_file: Path to test JSON file
		llm: Language model to use
		trigger_id: Identifier for the test trigger
		run_id: Run identifier
		enable_focus_manager: Enable browser focus manager (TOPMOST + auto restore)

	Returns:
		True if all tests passed, False otherwise
	"""
	ec_test = load_test_file(test_file)

	# Create focus manager if enabled
	focus_manager = None
	if enable_focus_manager:
		print("\n[FocusManager] Initializing browser focus manager...")
		focus_manager = BrowserFocusManager(
			browser_process_name='msedge.exe',  # TODO: make configurable
			keep_topmost=True,                  # Always on top
			auto_restore_focus=False,           # Only set once, don't continuously restore
			check_interval=2.0                  # Not used when auto_restore_focus=False
		)
		print("[FocusManager] Focus manager created (will start after browser launch)")

	# Run tests
	results = []
	for test_case in ec_test.test_cases:
		success = await run_test_case(
			llm,
			test_case,
			trigger_id,
			run_id,
			focus_manager  # Pass focus manager to test case
		)

		results.append({
			"test_case": test_case.test_case_name,
			"success": success
		})

	# Print summary for this file
	print(f"\n{'='*60}")
	print(f"Test Summary for {Path(test_file).name}")
	print(f"{'='*60}")
	for result in results:
		status = "[OK] PASS" if result["success"] else "[FAIL] FAIL"
		print(f"{status} {result['test_case']}")

	total = len(results)
	passed = sum(1 for r in results if r["success"])
	failed = total - passed

	print(f"\n[Stats] File Results:")
	print(f"  Total: {total}")
	print(f"  Passed: {passed}")
	print(f"  Failed: {failed}")
	print(f"  Success Rate: {passed/total*100:.1f}%")

	return failed == 0


async def main():
	"""Main entry point for the test runner."""
	import argparse

	parser = argparse.ArgumentParser(
		description="Run browser automation tests with Claude (auto-discovers *.test.json)"
	)
	parser.add_argument(
		"--trigger-id",
		default="manual",
		help="Test trigger identifier (default: manual)"
	)
	parser.add_argument(
		"--run-id",
		type=int,
		default=1,
		help="Test run identifier (default: 1)"
	)
	parser.add_argument(
		"--model",
		default="claude-sonnet-4-20250514",
		help="Claude model name (default: claude-sonnet-4-20250514)"
	)
	parser.add_argument(
		"--proxy",
		default="http://localhost:5000",
		help="Proxy endpoint (default: http://localhost:5000)"
	)
	parser.add_argument(
		"--use-proxy-pool",
		action="store_true",
		help="Enable free proxy pool for anti-bot (rotates IPs)"
	)
	parser.add_argument(
		"--max-proxies",
		type=int,
		default=30,
		help="Maximum proxies to scrape (default: 30)"
	)
	parser.add_argument(
		"--disable-browser-focus",
		action="store_true",
		help="Disable browser focus management (browser won't stay TOPMOST by default)"
	)

	args = parser.parse_args()

	# Initialize proxy pool if requested
	if args.use_proxy_pool:
		print(f"\n[Init] Initializing free proxy pool...")
		print(f"  Target proxies: {args.max_proxies}")
		await config.init_proxy_pool(max_proxies=args.max_proxies)
		if config.proxy_pool:
			stats = config.proxy_pool.get_stats()
			print(f"  [OK] Proxy pool ready: {stats['available']}/{stats['total']} proxies available")
		else:
			print(f"  [WARN] Proxy pool initialization failed, continuing without proxies")

	# Initialize Claude LLM
	print("\n[Init] Initializing Claude Sonnet via MicrosoftAI LLM Proxy...")
	print(f"  Model: {args.model}")
	print(f"  Proxy: {args.proxy}")

	llm = get_claude_sonnet(
		model=args.model,
		base_url=args.proxy,
	)

	# Auto-discover test files
	script_dir = Path(__file__).parent
	# Navigate to repository root, then to test_agent/test_case
	repo_root = script_dir.parent.parent  # Claude/ -> test_agent/ -> browser-use/
	test_case_dir = repo_root / 'test_agent' / 'test_case'
	test_files = list(test_case_dir.glob('**/*.test.json'))

	if not test_files:
		print(f"\n[FAIL] No test files found in {test_case_dir}/")
		print("  Looking for: **/*.test.json")
		sys.exit(1)

	print(f"\n[Discovery] Found {len(test_files)} test file(s):")
	for tf in test_files:
		print(f"  - {tf.relative_to(repo_root)}")

	# Show focus manager status
	enable_focus_manager = not args.disable_browser_focus  # Enabled by default
	if enable_focus_manager:
		print(f"\n[FocusManager] Browser focus management: ENABLED (default)")
		print(f"  - TOPMOST: Browser will be set on top once at startup")
		print(f"  (use --disable-browser-focus to turn off)")
	else:
		print(f"\n[FocusManager] Browser focus management: DISABLED")
		print(f"  (focus management turned off by --disable-browser-focus flag)")

	# Run all test files
	all_success = True
	for test_file in test_files:
		success = await run_test_file(
			str(test_file),
			llm,
			args.trigger_id,
			args.run_id,
			enable_focus_manager=enable_focus_manager  # Enabled by default
		)
		if not success:
			all_success = False

	# Overall summary
	print(f"\n{'='*60}")
	print("Overall Test Run Summary")
	print(f"{'='*60}")
	print(f"Files: {len(test_files)}")
	print(f"Status: {'[OK] ALL PASSED' if all_success else '[FAIL] SOME FAILED'}")

	sys.exit(0 if all_success else 1)


if __name__ == "__main__":
	asyncio.run(main())
