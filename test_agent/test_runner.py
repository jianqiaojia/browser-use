"""
Test runner using Claude via MicrosoftAI LLM Proxy

Auto-discovers and runs all *.test.json files in test_case/ directory.
"""
import argparse
import asyncio
import sys
import os
import time
import traceback
from pathlib import Path
from typing import Any

# Fix UTF-8 encoding for stdout/stderr on Windows BEFORE imports
# This ensures all print() and logging output uses UTF-8 (including emoji)
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
	sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
	sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Silence noisy third-party loggers
import logging
logging.getLogger('comtypes').setLevel(logging.WARNING)

# Apply patches FIRST
import test_agent.llm.strip_patch  # noqa: F401
import test_agent.llm.litellm_patch  # noqa: F401

from browser_use import Agent, BrowserProfile, BrowserSession, Tools
from test_agent.llm.llm_config import get_claude_sonnet as get_claude
from test_agent.config import config
from test_agent.models import TestCase, SiteTest
from test_agent.register_custom_actions import register_custom_actions
from test_agent.scripts.browser_focus_manager import BrowserFocusManager
from test_agent.scripts.windows_helper import kill_edge_processes
from test_agent.scripts.task_builder import load_preambles, build_pre_checkout_task, build_checkout_task
from test_agent.replay.replay_manager import ReplayManager


def load_test_file(test_file: str) -> SiteTest:
	"""Load a *.test.json file into a SiteTest object."""
	test_path = Path(test_file)
	if not test_path.exists():
		raise FileNotFoundError(f"Test file not found: {test_file}")
	return SiteTest.model_validate_json(test_path.read_text(encoding="utf-8"))


async def run_test_case(
	llm: Any,
	test: TestCase,
	pre_checkout_task: str,
	checkout_task: str,
	replay_dir: Path,
	focus_manager: BrowserFocusManager | None = None,
) -> bool:
	"""Execute a single test case."""

	try:
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
		tools = Tools()
		register_custom_actions(tools)

		safe_name = test.name.replace(" ", "_").replace("-", "_").lower()
		replay_path = replay_dir / f"{safe_name}.replay.json"

		# Start focus manager if provided (in background thread, non-blocking)
		if focus_manager:
			print("[FocusManager] Starting browser focus management in background...")
			loop = asyncio.get_event_loop()
			loop.run_in_executor(None, focus_manager.start_sync)
			print("[FocusManager] Focus manager starting in background (non-blocking)...")

		# Start shared browser session (keep_alive so Phase 1 → Phase 2 share the same session)
		keep_alive_profile = browser_profile.model_copy(update={'keep_alive': True})
		browser_session = BrowserSession(browser_profile=keep_alive_profile)
		await browser_session.start()

		success = False
		try:
			# Phase 1: pre-checkout (LLM, fresh each run, not recorded)
			t0 = time.perf_counter()
			print(f"\n[Phase 1] pre-checkout...")
			pre_checkout_agent = Agent(
				task=pre_checkout_task,
				llm=llm,
				browser_profile=browser_profile,
				browser_session=browser_session,
				tools=tools,
				max_actions_per_step=config.max_actions_per_step,
			)
			pre_history = await pre_checkout_agent.run(max_steps=config.max_steps)
			if not pre_history or not pre_history.is_successful():
				print(f"\n[Phase 1] ❌ pre-checkout failed")
				return False
			print(f"[Phase 1] ✅ done ({len(pre_history.history)} steps, {time.perf_counter()-t0:.1f}s)")

			# Phase 2: checkout via ReplayManager (replay or explore)
			manager = ReplayManager(
				replay_path=replay_path,
				checkout_task=checkout_task,
				llm=llm,
				browser_profile=browser_profile,
				tools=tools,
			)

			t0 = time.perf_counter()
			print(f"\n[Phase 2] {replay_path.name}")
			success = await manager.run(browser_session)
			elapsed = time.perf_counter() - t0
			print(f"\n⏱️  {elapsed:.1f}s — {'✅ PASS' if success else '❌ FAIL'}")
		finally:
			try:
				await browser_session.stop()
			except Exception:
				pass

		if focus_manager:
			focus_manager.stop()
			print("[FocusManager] Focus manager stopped")

		# Mark proxy result if used
		if config.use_proxy and config._current_proxy:
			await config.mark_proxy_result(success=bool(success), response_time=0.0)

		return success

	except Exception as e:
		print(f"\n[FAIL] Error running test: {str(e)}")
		traceback.print_exc()
		print("[Cleanup] Killing Edge processes after exception...")
		kill_edge_processes()
		return False


async def run_test_file(
	test_file: str,
	llm: Any,
	enable_focus_manager: bool = False,
	test_case_filter: str | None = None,
) -> bool:
	"""Run all test cases from a *.test.json file."""
	print(f"\n{'='*60}")
	print(f"Loading test file: {test_file}")
	print(f"{'='*60}")

	site_test = load_test_file(test_file)
	pre_checkout_preamble, checkout_preamble = load_preambles()

	# replay files live next to the test file
	replay_dir = Path(test_file).parent

	focus_manager = None
	if enable_focus_manager:
		print("\n[FocusManager] Initializing browser focus manager...")
		focus_manager = BrowserFocusManager(
			browser_process_name='msedge.exe',
			keep_topmost=True,
			auto_restore_focus=False,
			check_interval=2.0,
		)
		print("[FocusManager] Focus manager created (will start after browser launch)")

	results = []
	for test_case in site_test.test_cases:
		if test_case_filter and test_case_filter.lower() not in test_case.name.lower():
			print(f"\n[Filter] Skipping: {test_case.name}")
			continue

		pre_checkout_task = build_pre_checkout_task(
			test_case, pre_checkout_preamble, site_test.site_pre_checkout_guidance, site_test.domain
		)
		checkout_task = build_checkout_task(
			test_case, checkout_preamble, site_test.site_checkout_guidance, site_test.domain
		)

		success = await run_test_case(
			llm=llm,
			test=test_case,
			pre_checkout_task=pre_checkout_task,
			checkout_task=checkout_task,
			replay_dir=replay_dir,
			focus_manager=focus_manager,
		)
		results.append({"test_case": test_case.name, "success": success})

	print(f"\n{'='*60}")
	print(f"Test Summary for {Path(test_file).name}")
	print(f"{'='*60}")
	for result in results:
		status = "[OK] PASS" if result["success"] else "[FAIL] FAIL"
		print(f"{status} {result['test_case']}")

	total = len(results)
	passed = sum(1 for r in results if r["success"])
	print(f"\n[Stats] Total: {total}  Passed: {passed}  Failed: {total - passed}")
	if total:
		print(f"  Success Rate: {passed/total*100:.1f}%")

	return total > 0 and (total - passed) == 0


async def main():
	"""Main entry point for the test runner."""
	parser = argparse.ArgumentParser(
		description="Run browser automation tests with Claude (auto-discovers *.test.json)"
	)
	parser.add_argument("--model", default="claude-opus-4-5")
	parser.add_argument("--proxy", default="http://localhost:5000")
	parser.add_argument("--use-proxy-pool", action="store_true")
	parser.add_argument("--max-proxies", type=int, default=30)
	parser.add_argument("--disable-browser-focus", action="store_true")
	parser.add_argument("--test-case", default=None,
		help="Only run test cases whose name contains this substring (case-insensitive)")

	args = parser.parse_args()

	# Kill all Edge processes before starting (ensures clean state)
	print("\n[Init] Killing Edge processes before starting...")
	processes_killed = kill_edge_processes()
	if processes_killed:
		print("[Init] Waiting 2 seconds for cleanup...")
		time.sleep(2)

	# Initialize proxy pool if requested
	if args.use_proxy_pool:
		print(f"\n[Init] Initializing free proxy pool (target={args.max_proxies})...")
		await config.init_proxy_pool(max_proxies=args.max_proxies)
		if config.proxy_pool:
			stats = config.proxy_pool.get_stats()
			print(f"  [OK] {stats['available']}/{stats['total']} proxies available")

	# Initialize LLM
	print(f"\n[Init] Model: {args.model}  Proxy: {args.proxy}")
	llm = get_claude(model=args.model, base_url=args.proxy)

	# Auto-discover test files
	test_case_dir = Path(__file__).parent / "test_case"
	test_files = list(test_case_dir.glob("**/*.test.json"))

	if not test_files:
		print(f"\n[FAIL] No *.test.json files found in {test_case_dir}/")
		sys.exit(1)

	print(f"\n[Discovery] Found {len(test_files)} test file(s):")
	for tf in test_files:
		print(f"  - {tf.relative_to(Path(__file__).parent.parent)}")

	# Show focus manager status
	enable_focus_manager = not args.disable_browser_focus
	print(f"\n[FocusManager] {'ENABLED' if enable_focus_manager else 'DISABLED'}")

	# Run all test files
	all_success = True
	for test_file in test_files:
		success = await run_test_file(
			str(test_file),
			llm,
			enable_focus_manager=enable_focus_manager,
			test_case_filter=args.test_case,
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
