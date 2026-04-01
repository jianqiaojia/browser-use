"""
Test runner using Claude via MicrosoftAI LLM Proxy

Auto-discovers and runs all *.test.json files in test_case/ directory.
"""
import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Any, Optional

# Fix UTF-8 encoding for stdout/stderr on Windows BEFORE imports
# This ensures all print() and logging output uses UTF-8 (including emoji)
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
	sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
	sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Apply patches FIRST
import test_agent.llm.strip_patch  # noqa: F401
import test_agent.llm.litellm_patch  # noqa: F401

from browser_use import BrowserProfile
from test_agent.llm.llm_config import get_claude_sonnet as get_claude
from test_agent.config import config
from test_agent.models import TestCase, SiteTest
from test_agent.register_custom_actions import register_custom_actions
from test_agent.scripts.browser_focus_manager import BrowserFocusManager
from test_agent.scripts.windows_helper import kill_edge_processes
from test_agent.replay.replay_manager import ReplayManager


def _load_preamble() -> str | None:
	"""Load the global task preamble from task_preamble.txt."""
	path = Path(__file__).parent / "test_case" / "task_preamble.txt"
	return path.read_text(encoding="utf-8").strip() if path.exists() else None


def build_task(
	test: TestCase,
	preamble: str | None,
	site_guidance: str | None,
	domain: str | None = None,
) -> str:
	"""
	Build the task string passed to the LLM agent.

	preamble is a markdown template with placeholders:
	  {--Domain--}       — replaced with domain URL
	  {--Instructions--} — replaced with test.instructions
	  {--Guidance--}     — replaced with site_guidance + test.guidance as bullet list
	"""
	if not preamble:
		return ""

	text = preamble

	# Replace {--Domain--}
	text = text.replace("{--Domain--}", domain or "")

	# Replace {--Instructions--}
	if test.instructions:
		if isinstance(test.instructions, list):
			inst_items = "\n".join(f"- {l}" for l in test.instructions)
		else:
			inst_items = f"- {test.instructions}"
		text = text.replace("{--Instructions--}", inst_items)
	else:
		text = text.replace("{--Instructions--}", "")

	# Replace {--Guidance--} with bullet list
	if site_guidance or test.guidance:
		if isinstance(site_guidance, list):
			sg_lines: list[str] = site_guidance
		elif site_guidance:
			sg_lines = [site_guidance]
		else:
			sg_lines = []
		if isinstance(test.guidance, list):
			tg_lines: list[str] = test.guidance
		elif test.guidance:
			tg_lines = [test.guidance]
		else:
			tg_lines = []
		all_lines = sg_lines + tg_lines
		guidance_items = "\n".join(f"- {l}" for l in all_lines)
	else:
		guidance_items = ""
	text = text.replace("{--Guidance--}", guidance_items)

	return text


def load_test_file(test_file: str) -> SiteTest:
	"""Load a *.test.json file into a SiteTest object."""
	test_path = Path(test_file)
	if not test_path.exists():
		raise FileNotFoundError(f"Test file not found: {test_file}")
	data = json.loads(test_path.read_text(encoding="utf-8"))
	return SiteTest(**data)


async def run_test_case(
	llm: Any,
	test: TestCase,
	site_guidance: str | None,
	preamble: str | None,
	trigger_id: str,
	run_id: int,
	replay_dir: Path,
	focus_manager: Optional[BrowserFocusManager] = None,
	explore: bool = False,
	explore_and_refine: bool = False,
	domain: str | None = None,
) -> bool:
	"""Execute a single test case."""
	print(f"\n{'='*60}")
	print(f"Test Case: {test.name}")
	if test.instructions:
		print(f"Instructions: {test.instructions}")
	if test.guidance:
		print(f"Guidance: {test.guidance}")
	print(f"Trigger ID: {trigger_id}, Run ID: {run_id}")
	print(f"{'='*60}")

	try:
		task = build_task(test, preamble, site_guidance, domain)
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
		print("[Agent] Creating agent with Claude Opus...")
		safe_name = test.name.replace(" ", "_").replace("-", "_").lower()
		replay_path = replay_dir / f"{safe_name}.replay.json"

		# Start focus manager if provided (in background thread, non-blocking)
		if focus_manager:
			print("[FocusManager] Starting browser focus management in background...")
			# 在后台线程启动，不阻塞主流程
			import concurrent.futures
			loop = asyncio.get_event_loop()
			loop.run_in_executor(None, focus_manager.start_sync)
			print("[FocusManager] Focus manager starting in background (non-blocking)...")

		# Run test
		manager = ReplayManager(
			replay_path=replay_path,
			task=task,
			llm=llm,
			browser_profile=browser_profile,
			tools=tools,
		)

		import time
		t0 = time.perf_counter()
		if explore or explore_and_refine:
			mode = "explore" if explore else "explore-and-refine"
			dry_run = explore
			print(f"[ReplayManager] replay path: {replay_path} (mode={mode})")
			success = await manager.explore(dry_run=dry_run)
		else:
			mode = "replay" if replay_path.exists() else "explore"
			print(f"[ReplayManager] replay path: {replay_path} (mode={mode})")
			success = await manager.run()
		elapsed = time.perf_counter() - t0
		print(f"\n⏱️  [{mode}] {elapsed:.1f}s — {'✅ PASS' if success else '❌ FAIL'}")

		if focus_manager:
			focus_manager.stop()
			print("[FocusManager] Focus manager stopped")

		# Mark proxy result if used
		if config.use_proxy and config._current_proxy:
			await config.mark_proxy_result(success=bool(success), response_time=0.0)

		return success

	except Exception as e:
		print(f"\n[FAIL] Error running test: {str(e)}")
		import traceback
		traceback.print_exc()
		# Kill Edge in case it didn't close cleanly after the exception
		print("[Cleanup] Killing Edge processes after exception...")
		kill_edge_processes()
		return False


async def run_test_file(
	test_file: str,
	llm: Any,
	trigger_id: str = "manual",
	run_id: int = 1,
	enable_focus_manager: bool = False,
	test_case_filter: Optional[str] = None,
	explore: bool = False,
	explore_and_refine: bool = False,
) -> bool:
	"""Run all test cases from a *.test.json file."""
	print(f"\n{'='*60}")
	print(f"Loading test file: {test_file}")
	print(f"{'='*60}")

	site_test = load_test_file(test_file)
	preamble = _load_preamble()

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

		success = await run_test_case(
			llm=llm,
			test=test_case,
			site_guidance=site_test.site_guidance,
			preamble=preamble,
			trigger_id=trigger_id,
			run_id=run_id,
			replay_dir=replay_dir,
			focus_manager=focus_manager,
			explore=explore,
			explore_and_refine=explore_and_refine,
			domain=site_test.domain,
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
	import argparse

	parser = argparse.ArgumentParser(
		description="Run browser automation tests with Claude (auto-discovers *.test.json)"
	)
	parser.add_argument("--trigger-id", default="manual")
	parser.add_argument("--run-id", type=int, default=1)
	parser.add_argument("--model", default="claude-opus-4-5")
	parser.add_argument("--proxy", default="http://localhost:5000")
	parser.add_argument("--use-proxy-pool", action="store_true")
	parser.add_argument("--max-proxies", type=int, default=30)
	parser.add_argument("--disable-browser-focus", action="store_true")
	parser.add_argument("--test-case", default=None,
		help="Only run test cases whose name contains this substring (case-insensitive)")
	parser.add_argument("--explore", action="store_true",
		help="LLM explore only, save to .draft.json (does not touch replay.json)")
	parser.add_argument("--explore-and-refine", action="store_true",
		help="LLM explore + refine, directly overwrite replay.json")

	args = parser.parse_args()

	# Kill all Edge processes before starting (ensures clean state)
	print("\n[Init] Killing Edge processes before starting...")
	processes_killed = kill_edge_processes()
	if processes_killed:
		import time
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
			args.trigger_id,
			args.run_id,
			enable_focus_manager=enable_focus_manager,
			test_case_filter=args.test_case,
			explore=args.explore,
			explore_and_refine=args.explore_and_refine,
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
