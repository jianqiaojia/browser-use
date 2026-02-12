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
from typing import Any

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
	repeat_num: int = 1
) -> bool:
	"""Execute a test case using Claude.

	Args:
		llm: Language model to use for the agent
		test: Test case to execute
		trigger_id: Identifier for the test trigger
		run_id: Run identifier
		repeat_num: Repeat number for multiple runs

	Returns:
		True if test passed, False otherwise
	"""
	print(f"\n{'='*60}")
	print(f"Test Case: {test.test_case_name}")
	print(f"Description: {test.test_case_description}")
	print(f"Trigger ID: {trigger_id}, Run ID: {run_id}, Repeat: {repeat_num}")
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

		# Run test
		print("[Run] Executing test...")
		history = await agent.run(max_steps=config.max_steps)

		# Save history IMMEDIATELY after test completes, before any other operations
		safe_name = test.test_case_name.replace(" ", "_").replace("-", "_").lower()

		# Add timestamp and repeat number to filename to avoid overwriting
		from datetime import datetime
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
		if repeat_num > 1:
			history_file = f"test_case/{safe_name}_claude_run{repeat_num}_{timestamp}.history.json"
		else:
			history_file = f"test_case/{safe_name}_claude_{timestamp}.history.json"

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
	repeat_num: int = 1
) -> bool:
	"""Run tests from a test file.

	Args:
		test_file: Path to test JSON file
		llm: Language model to use
		trigger_id: Identifier for the test trigger
		run_id: Run identifier
		repeat_num: Repeat number for multiple runs

	Returns:
		True if all tests passed, False otherwise
	"""
	ec_test = load_test_file(test_file)

	# Run tests
	results = []
	for test_case in ec_test.test_cases:
		success = await run_test_case(
			llm,
			test_case,
			trigger_id,
			run_id,
			repeat_num
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
		"--repeat",
		type=int,
		default=1,
		help="Number of times to repeat all tests (default: 1)"
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

	# Repeat tests if requested
	repeat_count = args.repeat
	if repeat_count > 1:
		print(f"\n[Repeat] Will run tests {repeat_count} times")

	all_results = []
	run_durations = []
	from datetime import datetime
	import time

	for run_num in range(1, repeat_count + 1):
		run_start_time = time.time()
		run_start_datetime = datetime.now()

		if repeat_count > 1:
			print(f"\n{'='*60}")
			print(f"Run {run_num}/{repeat_count}")
			print(f"Start time: {run_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
			print(f"{'='*60}")

		# Run all test files
		run_success = True
		for test_file in test_files:
			success = await run_test_file(
				str(test_file),
				llm,
				args.trigger_id,
				args.run_id,
				run_num  # Pass repeat number
			)
			if not success:
				run_success = False

		all_results.append(run_success)

		# Calculate run duration
		run_duration = time.time() - run_start_time
		run_end_datetime = datetime.now()
		run_durations.append(run_duration)

		if repeat_count > 1:
			print(f"\n[Run {run_num}] Completed in {run_duration:.1f} seconds")
			print(f"  End time: {run_end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

		# Wait between runs
		if run_num < repeat_count:
			print(f"\n[Wait] Waiting 2 seconds before next run...")
			time.sleep(2)

	# Overall summary
	print(f"\n{'='*60}")
	print("Overall Test Run Summary")
	print(f"{'='*60}")
	print(f"Files: {len(test_files)}")
	if repeat_count > 1:
		success_count = sum(1 for r in all_results if r)
		total_duration = sum(run_durations)
		avg_duration = total_duration / len(run_durations) if run_durations else 0

		print(f"Runs: {repeat_count}")
		print(f"Success: {success_count}/{repeat_count} ({success_count/repeat_count*100:.1f}%)")
		print(f"Total duration: {total_duration:.1f}s ({total_duration/60:.1f} minutes)")
		print(f"Average duration: {avg_duration:.1f}s per run")

		# Show individual run times
		print(f"\nRun durations:")
		for i, duration in enumerate(run_durations, 1):
			status = "✅" if all_results[i-1] else "❌"
			print(f"  Run {i:2d}: {status} {duration:6.1f}s")

		print(f"\nStatus: {'[OK] ALL PASSED' if success_count == repeat_count else '[FAIL] SOME FAILED'}")
		all_success = success_count == repeat_count
	else:
		all_success = all_results[0] if all_results else False
		print(f"Status: {'[OK] ALL PASSED' if all_success else '[FAIL] SOME FAILED'}")

	sys.exit(0 if all_success else 1)


if __name__ == "__main__":
	asyncio.run(main())
