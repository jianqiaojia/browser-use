"""
Batch test runner wrapper for Claude tests.

Simplified wrapper that delegates to test_runner_claude.py with --repeat parameter.
Adds system-level features like sleep prevention and Edge process cleanup.
"""
import sys
import ctypes
import subprocess
from pathlib import Path


# Windows API constants for preventing sleep
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def prevent_sleep():
	"""Prevent system from entering sleep/low-power state during tests."""
	try:
		ctypes.windll.kernel32.SetThreadExecutionState(
			ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
		)
		print("[Sleep Prevention] ✅ System sleep disabled for test duration")
		return True
	except Exception as e:
		print(f"[Sleep Prevention] ⚠️ Could not disable sleep: {e}")
		return False


def allow_sleep():
	"""Re-enable system sleep after tests complete."""
	try:
		ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
		print("[Sleep Prevention] ✅ System sleep re-enabled")
	except Exception as e:
		print(f"[Sleep Prevention] ⚠️ Could not re-enable sleep: {e}")


def kill_edge_processes():
	"""Kill all Edge browser processes to ensure clean state."""
	import time

	try:
		print("[Cleanup] Checking for Edge browser processes...")

		# Find all msedge.exe processes
		result = subprocess.run(
			['tasklist', '/FI', 'IMAGENAME eq msedge.exe', '/FO', 'CSV'],
			capture_output=True,
			text=True,
			timeout=5
		)

		# Check if any Edge processes are running
		if 'msedge.exe' in result.stdout:
			lines = result.stdout.strip().split('\n')
			process_count = len(lines) - 1
			print(f"[Cleanup] Found {process_count} Edge process(es), terminating...")

			# Kill all Edge processes forcefully
			subprocess.run(
				['taskkill', '/F', '/IM', 'msedge.exe', '/T'],
				capture_output=True,
				timeout=10
			)

			# Wait for processes to fully terminate
			print("[Cleanup] Waiting 3 seconds for processes to terminate...")
			time.sleep(3)

			# Verify processes are gone
			verify = subprocess.run(
				['tasklist', '/FI', 'IMAGENAME eq msedge.exe', '/FO', 'CSV'],
				capture_output=True,
				text=True,
				timeout=5
			)

			if 'msedge.exe' not in verify.stdout:
				print("[Cleanup] ✅ All Edge processes terminated successfully")
			else:
				remaining = len(verify.stdout.strip().split('\n')) - 1
				print(f"[Cleanup] ⚠️ Warning: {remaining} Edge process(es) still running")
		else:
			print("[Cleanup] ✅ No Edge processes found")

		return True

	except subprocess.TimeoutExpired:
		print("[Cleanup] ⚠️ Timeout while checking/killing Edge processes")
		return False
	except Exception as e:
		print(f"[Cleanup] ⚠️ Error during cleanup: {e}")
		return False


def main():
	"""Main entry point - wraps test_runner_claude.py with system-level features."""
	import argparse
	import time
	from datetime import datetime

	parser = argparse.ArgumentParser(
		description="Batch test runner wrapper - prevents sleep and manages Edge processes"
	)
	parser.add_argument(
		"--repeat",
		type=int,
		default=5,
		help="Number of times to repeat all tests (default: 5)"
	)
	parser.add_argument(
		"--cleanup-after-each",
		action="store_true",
		help="Kill Edge processes after each test run (default: only at end)"
	)
	# Pass-through args for test_runner_claude.py
	parser.add_argument("--trigger-id", default="batch", help="Test trigger ID")
	parser.add_argument("--run-id", type=int, default=1, help="Test run ID")
	parser.add_argument("--model", default="claude-sonnet-4-20250514", help="Claude model")
	parser.add_argument("--proxy", default="http://localhost:5000", help="Proxy endpoint")
	parser.add_argument("--use-proxy-pool", action="store_true", help="Enable proxy pool")
	parser.add_argument("--max-proxies", type=int, default=30, help="Max proxies to scrape")
	parser.add_argument("--disable-browser-focus", action="store_true", help="Disable TOPMOST focus")

	args = parser.parse_args()

	# Prevent system sleep during batch testing
	print("\n[Init] Preventing system sleep during batch testing...")
	prevent_sleep()

	try:
		# Build command to run test_runner_claude.py
		script_dir = Path(__file__).parent
		test_runner_script = script_dir / "test_runner_claude.py"

		if not test_runner_script.exists():
			print(f"[FAIL] test_runner_claude.py not found at {test_runner_script}")
			sys.exit(1)

		# Build base command with all arguments (NO --repeat)
		cmd = [
			sys.executable,  # Use same Python interpreter
			str(test_runner_script),
			f"--trigger-id={args.trigger_id}",
			f"--run-id={args.run_id}",
			f"--model={args.model}",
			f"--proxy={args.proxy}",
		]

		if args.use_proxy_pool:
			cmd.append("--use-proxy-pool")
			cmd.append(f"--max-proxies={args.max_proxies}")

		if args.disable_browser_focus:
			cmd.append("--disable-browser-focus")

		# Repeat tests
		repeat_count = args.repeat
		print(f"\n[Batch] Will run test_runner_claude.py {repeat_count} times")
		print(f"[Command] {' '.join(cmd)}\n")

		all_results = []
		run_durations = []

		for run_num in range(1, repeat_count + 1):
			run_start_time = time.time()
			run_start_datetime = datetime.now()

			print(f"\n{'='*60}")
			print(f"Batch Run {run_num}/{repeat_count}")
			print(f"Start time: {run_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
			print(f"{'='*60}\n")

			# Run test_runner_claude.py
			result = subprocess.run(cmd, cwd=script_dir.parent.parent)

			# Track result
			run_success = (result.returncode == 0)
			all_results.append(run_success)

			# Calculate run duration
			run_duration = time.time() - run_start_time
			run_end_datetime = datetime.now()
			run_durations.append(run_duration)

			print(f"\n[Run {run_num}] Completed in {run_duration:.1f} seconds")
			print(f"  End time: {run_end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
			print(f"  Status: {'✅ PASSED' if run_success else '❌ FAILED'}")

			# Cleanup Edge processes after each run if requested
			if args.cleanup_after_each and run_num < repeat_count:
				print(f"\n[Cleanup] Killing Edge processes between runs...")
				kill_edge_processes()
				print(f"[Wait] Waiting 2 seconds before next run...")
				time.sleep(2)

		# Overall summary
		print(f"\n{'='*60}")
		print("Batch Test Run Summary")
		print(f"{'='*60}")

		success_count = sum(1 for r in all_results if r)
		total_duration = sum(run_durations)
		avg_duration = total_duration / len(run_durations) if run_durations else 0

		print(f"Total runs: {repeat_count}")
		print(f"Success: {success_count}/{repeat_count} ({success_count/repeat_count*100:.1f}%)")
		print(f"Total duration: {total_duration:.1f}s ({total_duration/60:.1f} minutes)")
		print(f"Average duration: {avg_duration:.1f}s per run")

		# Show individual run times
		print(f"\nRun durations:")
		for i, duration in enumerate(run_durations, 1):
			status = "✅" if all_results[i-1] else "❌"
			print(f"  Run {i:2d}: {status} {duration:6.1f}s")

		all_success = (success_count == repeat_count)
		print(f"\nStatus: {'[OK] ALL PASSED' if all_success else '[FAIL] SOME FAILED'}")

		# Final cleanup
		print("\n[Cleanup] Final Edge process cleanup...")
		kill_edge_processes()

		return 0 if all_success else 1

	finally:
		# Always re-enable sleep when done
		allow_sleep()


if __name__ == "__main__":
	exit_code = main()
	sys.exit(exit_code)
