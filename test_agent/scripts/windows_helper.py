"""
Windows system helper utilities.

Provides Windows-specific system operations like sleep prevention and process management.
"""
import ctypes
import subprocess
import time


# Windows API constants for preventing sleep
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def prevent_sleep() -> bool:
	"""Prevent system from entering sleep/low-power state during tests.

	Returns:
		True if successful, False otherwise
	"""
	try:
		ctypes.windll.kernel32.SetThreadExecutionState(
			ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
		)
		print("[Sleep Prevention] ✅ System sleep disabled for test duration")
		return True
	except Exception as e:
		print(f"[Sleep Prevention] ⚠️ Could not disable sleep: {e}")
		return False


def allow_sleep() -> None:
	"""Re-enable system sleep after tests complete."""
	try:
		ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
		print("[Sleep Prevention] ✅ System sleep re-enabled")
	except Exception as e:
		print(f"[Sleep Prevention] ⚠️ Could not re-enable sleep: {e}")


def kill_processes_by_name(process_name: str, wait_time: int = 3) -> bool:
	"""Kill all processes matching the given name.

	Args:
		process_name: Process executable name (e.g., "msedge.exe")
		wait_time: Time to wait for processes to terminate (seconds)

	Returns:
		True if processes were found and killed, False if no processes or error
	"""
	try:
		print(f"[Cleanup] Checking for {process_name} processes...")

		# Find all matching processes
		result = subprocess.run(
			['tasklist', '/FI', f'IMAGENAME eq {process_name}', '/FO', 'CSV'],
			capture_output=True,
			text=True,
			timeout=5
		)

		# Check if any processes are running
		if process_name in result.stdout:
			lines = result.stdout.strip().split('\n')
			process_count = len(lines) - 1
			print(f"[Cleanup] Found {process_count} {process_name} process(es), terminating...")

			# Kill all processes forcefully
			subprocess.run(
				['taskkill', '/F', '/IM', process_name, '/T'],
				capture_output=True,
				timeout=10
			)

			# Wait for processes to fully terminate
			print(f"[Cleanup] Waiting {wait_time} seconds for processes to terminate...")
			time.sleep(wait_time)

			# Verify processes are gone
			verify = subprocess.run(
				['tasklist', '/FI', f'IMAGENAME eq {process_name}', '/FO', 'CSV'],
				capture_output=True,
				text=True,
				timeout=5
			)

			if process_name not in verify.stdout:
				print(f"[Cleanup] ✅ All {process_name} processes terminated successfully")
			else:
				remaining = len(verify.stdout.strip().split('\n')) - 1
				print(f"[Cleanup] ⚠️ Warning: {remaining} {process_name} process(es) still running")

			return True  # Processes were killed
		else:
			print(f"[Cleanup] ✅ No {process_name} processes found")
			return False  # No processes to kill

	except subprocess.TimeoutExpired:
		print(f"[Cleanup] ⚠️ Timeout while checking/killing {process_name} processes")
		return False
	except Exception as e:
		print(f"[Cleanup] ⚠️ Error during cleanup: {e}")
		return False


def kill_edge_processes(wait_time: int = 3) -> bool:
	"""Kill all Edge browser processes to ensure clean state.

	Args:
		wait_time: Time to wait for processes to terminate (seconds, default: 3)

	Returns:
		True if processes were found and killed, False if no processes or error
	"""
	return kill_processes_by_name("msedge.exe", wait_time=wait_time)


def kill_chrome_processes(wait_time: int = 3) -> bool:
	"""Kill all Chrome browser processes to ensure clean state.

	Args:
		wait_time: Time to wait for processes to terminate (seconds, default: 3)

	Returns:
		True if processes were found and killed, False if no processes or error
	"""
	return kill_processes_by_name("chrome.exe", wait_time=wait_time)
