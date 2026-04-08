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

from browser_use import BrowserProfile, BrowserSession, Tools
from test_agent.llm.llm_config import get_claude_sonnet as get_claude
from test_agent.config import config, PROFILE_ALIASES
from test_agent.models import TestCase, SiteTest
from test_agent.register_custom_actions import register_custom_actions
from test_agent.scripts.proxy_manager import ProxyAuthWatcher, init_proxy, get_proxy, mark_proxy_result
from test_agent.scripts.browser_focus_manager import BrowserFocusManager
from test_agent.scripts.windows_helper import kill_edge_processes
from test_agent.scripts.task_builder import load_prompt_templates, build_pre_checkout_task, build_checkout_task
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

		# Per-test profile override (supports aliases from PROFILE_ALIASES)
		if test.profile:
			browser_config['profile_directory'] = PROFILE_ALIASES.get(test.profile, test.profile)

		# Get proxy if enabled
		proxy_settings = await get_proxy()
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

		runner = ReplayManager(
			pre_checkout_task=pre_checkout_task,
			checkout_task=checkout_task,
			replay_path=replay_path,
			llm=llm,
			browser_profile=browser_profile,
			tools=tools,
		)

		# Start focus manager if provided (in background thread, non-blocking)
		if focus_manager:
			print("[FocusManager] Starting browser focus management in background...")
			loop = asyncio.get_event_loop()
			loop.run_in_executor(None, focus_manager.start_sync)
			print("[FocusManager] Focus manager starting in background (non-blocking)...")

		# Start shared browser session (keep_alive so Phase 1 → Phase 2 share the same session)
		keep_alive_profile = browser_profile.model_copy(update={'keep_alive': True})
		browser_session = BrowserSession(browser_profile=keep_alive_profile)

		if proxy_settings:
			ProxyAuthWatcher(proxy_settings)

		await browser_session.start()

		t0 = time.perf_counter()
		success = False
		try:
			success = await runner.run(browser_session)
		finally:
			try:
				await browser_session.stop()
			except Exception:
				pass
		print(f"[TestRunner] ⏱️⏱️⏱️  {time.perf_counter()-t0:.1f}s — {'✅ PASS' if success else '❌ FAIL'}")

		if focus_manager:
			focus_manager.stop()
			print("[FocusManager] Focus manager stopped")

		# Mark proxy result if used
		if proxy_settings:
			await mark_proxy_result(success=bool(success), response_time=0.0)

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
) -> bool | None:
	"""Run all test cases from a *.test.json file."""
	print(f"\n{'='*60}")
	print(f"Loading test file: {test_file}")
	print(f"{'='*60}")

	site_test = load_test_file(test_file)
	pre_checkout_preamble, checkout_preamble = load_prompt_templates()

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

	return total > 0 and (total - passed) == 0 if total > 0 else None


async def main():
	"""Main entry point for the test runner."""
	parser = argparse.ArgumentParser(
		description="Run browser automation tests with Claude (auto-discovers *.test.json)"
	)
	parser.add_argument("--model", default="claude-opus-4-5")
	parser.add_argument("--proxy", default="http://localhost:5000")
	parser.add_argument("--use-proxy", action="store_true", help="Enable proxy (Webshare primary, free pool fallback)")
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
	if args.use_proxy:
		from test_agent.scripts.proxy_manager import WEBSHARE_API_KEY, WEBSHARE_PROXY_USERNAME, WEBSHARE_PROXY_PASSWORD
		print(f"\n[Init] Initializing proxy pool...")
		await init_proxy(
			webshare_api_key=WEBSHARE_API_KEY,
			webshare_username=WEBSHARE_PROXY_USERNAME,
			webshare_password=WEBSHARE_PROXY_PASSWORD,
		)

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
	ran_any = False
	for test_file in test_files:
		result = await run_test_file(
			str(test_file),
			llm,
			enable_focus_manager=enable_focus_manager,
			test_case_filter=args.test_case,
		)
		if result is None:
			continue  # all cases filtered out — do not count as failure
		ran_any = True
		if not result:
			all_success = False

	# Overall summary
	print(f"\n{'='*60}")
	print("Overall Test Run Summary")
	print(f"{'='*60}")
	print(f"Files: {len(test_files)}")
	print(f"Status: {'[OK] ALL PASSED' if (all_success and ran_any) else '[FAIL] SOME FAILED'}")

	return 0 if (all_success and ran_any) else 1


if __name__ == "__main__":
	import warnings
	import gc
	warnings.filterwarnings("ignore", category=ResourceWarning)

	loop = asyncio.ProactorEventLoop()
	asyncio.set_event_loop(loop)
	try:
		exit_code = loop.run_until_complete(main())
	finally:
		# Drain all remaining callbacks so transports can close cleanly.
		# This fixes the Windows ProactorEventLoop pipe-transport __del__ warning
		# (Python issue #86817): GC runs after the loop is closed and the transport's
		# __repr__ tries to call fileno() on an already-closed pipe.
		try:
			loop.run_until_complete(asyncio.sleep(0))
			gc.collect()
			loop.run_until_complete(asyncio.sleep(0))
		except Exception:
			pass
		loop.close()

	sys.exit(exit_code)
