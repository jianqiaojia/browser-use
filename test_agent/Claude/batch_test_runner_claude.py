"""
Batch test runner wrapper for Claude tests.

Simplified wrapper that delegates to test_runner_claude.py with --repeat parameter.
Adds system-level features like sleep prevention and Edge process cleanup.
Supports optional tscon execution for RDP session switching.
"""
import sys
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from test_agent.utils.log_helper import setup_logging
from test_agent.utils.windows_helper import prevent_sleep, allow_sleep, kill_edge_processes
from test_agent.utils.tscon_helper import execute_tscon_script


def main():
	"""Main entry point - wraps test_runner_claude.py with system-level features."""
	import argparse
	import time

	parser = argparse.ArgumentParser(
		description="Batch test runner wrapper - prevents sleep and manages Edge processes"
	)
	parser.add_argument(
		"--repeat",
		type=int,
		default=5,
		help="Number of times to repeat all tests (default: 5)"
	)
	# Pass-through args for test_runner_claude.py
	parser.add_argument("--trigger-id", default="batch", help="Test trigger ID")
	parser.add_argument("--run-id", type=int, default=1, help="Test run ID")
	parser.add_argument("--model", default="claude-sonnet-4-20250514", help="Claude model")
	parser.add_argument("--proxy", default="http://localhost:5000", help="Proxy endpoint")
	parser.add_argument("--use-proxy-pool", action="store_true", help="Enable proxy pool")
	parser.add_argument("--max-proxies", type=int, default=30, help="Max proxies to scrape")
	parser.add_argument("--disable-browser-focus", action="store_true", help="Disable TOPMOST focus")
	parser.add_argument(
		"--enable-tscon",
		action="store_true",
		help="Enable tscon helper script execution (switch to Console Session before each run)"
	)
	parser.add_argument(
		"--tscon-wait-time",
		type=int,
		default=15,
		help="Wait time after tscon execution (seconds, default: 15)"
	)

	args = parser.parse_args()

	# Setup logging to BOTH file AND console (using TeeLogger)
	script_dir = Path(__file__).parent
	log_dir = script_dir.parent.parent / 'test_agent' / 'Claude' / 'test_case_log'
	tee, log_file = setup_logging(log_dir)

	# Redirect stdout/stderr - TeeLogger will write to BOTH console AND file
	original_stdout = sys.stdout
	original_stderr = sys.stderr
	sys.stdout = tee
	sys.stderr = tee

	print(f"[Log] Batch run log saved to: {log_file}")
	print("[Log] All console output will be duplicated to log file")

	# Prevent system sleep during batch testing
	print("\n[Init] Preventing system sleep during batch testing...")
	prevent_sleep()

	try:
		# Build command to run test_runner_claude.py
		test_runner_script = script_dir / "test_runner_claude.py"

		if not test_runner_script.exists():
			print(f"[FAIL] test_runner_claude.py not found at {test_runner_script}")
			return 1

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

		# Show tscon status
		print(f"\n[Tscon] tscon execution: {'✅ ENABLED' if args.enable_tscon else '❌ DISABLED (skipped)'}")
		if args.enable_tscon:
			print(f"[Tscon] Wait time: {args.tscon_wait_time} seconds")
			print(f"[Tscon] Will execute ONCE before all test runs (not before each run)")

		# Repeat tests
		repeat_count = args.repeat
		print(f"\n[Batch] Will run test_runner_claude.py {repeat_count} times")
		print(f"[Command] {' '.join(cmd)}\n")

		# Execute tscon ONCE before all test runs (if enabled)
		if args.enable_tscon:
			print("\n[Tscon] Executing tscon helper script before starting batch tests...")
			tscon_success = asyncio.run(execute_tscon_script(wait_time=args.tscon_wait_time))
			if not tscon_success:
				print("\n⚠️  tscon script execution failed, but continuing with tests...")
			print("")

		all_results = []
		run_durations = []

		for run_num in range(1, repeat_count + 1):
			run_start_time = time.time()
			run_start_datetime = datetime.now()

			print(f"\n{'='*60}")
			print(f"Batch Run {run_num}/{repeat_count}")
			print(f"Start time: {run_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
			print(f"{'='*60}\n")

			# Kill all Edge processes BEFORE starting agent (ensures clean state)
			print(f"[Cleanup] Killing Edge processes before run {run_num}...")
			processes_killed = kill_edge_processes()

			# Only wait if processes were actually killed
			if processes_killed:
				print(f"[Wait] Waiting 2 seconds for cleanup to complete...")
				time.sleep(2)

			# Run test_runner_claude.py with real-time output streaming
			print(f"[Batch] Starting test_runner_claude.py...\n")
			sys.stdout.flush()  # Ensure header is written before subprocess output

			# Use Popen to stream output in real-time
			process = subprocess.Popen(
				cmd,
				cwd=script_dir.parent.parent,
				stdout=subprocess.PIPE,
				stderr=subprocess.STDOUT,  # Merge stderr into stdout
				text=True,
				encoding='utf-8',  # Use UTF-8 for subprocess output
				bufsize=1  # Line buffered
			)

			# Stream output line by line (will go through TeeLogger)
			if process.stdout:
				for line in process.stdout:
					print(line, end='')  # Print without adding extra newline

			# Wait for process to complete
			returncode = process.wait()
			result = subprocess.CompletedProcess(cmd, returncode)

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

		# Restore original stdout/stderr and close log file
		sys.stdout = original_stdout
		sys.stderr = original_stderr
		tee.close()
		print(f"\n[Log] Batch run log saved to: {log_file}", file=original_stdout)


if __name__ == "__main__":
	exit_code = main()
	sys.exit(exit_code)
