"""
Terminal Services Console (tscon) helper utilities.

Provides utilities for switching RDP sessions to Console Session,
which is necessary for proper UI automation (e.g., popup display).
"""
import os
import asyncio
import subprocess
from pathlib import Path


# tscon PowerShell script path
TSCON_SCRIPT_PATH = Path(__file__).parent / "tscon_worker.ps1"


async def execute_tscon_script(wait_time: int = 15, script_path: Path | None = None) -> bool:
	"""Execute tscon helper script to switch to Console Session.

	This is useful for RDP scenarios where UI elements (like popups) may not
	display correctly in the RDP session. Switching to Console Session resolves
	this issue.

	Args:
		wait_time: Time to wait for Console Session to stabilize (seconds, default: 15)
		script_path: Optional custom path to tscon PowerShell script

	Returns:
		True if successful, False otherwise

	Note:
		- Requires administrator privileges (will prompt for UAC)
		- RDP connection will disconnect after tscon execution
		- This function blocks until completion (including user input and wait time)
	"""
	try:
		# Use custom script path if provided
		script = script_path or TSCON_SCRIPT_PATH

		# Get current Python process PID
		current_pid = os.getpid()

		# Check if PowerShell script exists
		if not script.exists():
			print(f"\n❌ Error: tscon helper script not found: {script}")
			print("   Please ensure tscon_worker.ps1 exists in test_agent/utils/ directory")
			return False

		# Display info
		print("\n" + "=" * 80)
		print("Executing tscon helper script")
		print("=" * 80)
		print("")
		print("The script will automatically:")
		print(f"  ✅ Allow Python process (PID: {current_pid}) to set foreground window")
		print("  ✅ Auto-detect current RDP Session ID")
		print("  ✅ Execute tscon to switch to Console Session")
		print("  ⚠️  RDP connection will disconnect immediately")
		print("")
		print("=" * 80)

		input("\nPress Enter to launch script (UAC prompt will appear for admin rights)...")

		# Use PowerShell Start-Process with admin elevation
		print("\n[Execute] Launching PowerShell script with admin rights...")
		print(f"  Script path: {script.absolute()}")
		print(f"  Arguments: -PythonPid {current_pid}")

		try:
			# Use Start-Process -Verb RunAs to request admin rights
			# Use -Wait to wait for script completion
			powershell_cmd = [
				"powershell",
				"-Command",
				f'Start-Process powershell -ArgumentList \'-ExecutionPolicy Bypass -File "{script.absolute()}" -PythonPid {current_pid}\' -Verb RunAs -Wait'
			]

			print("[Execute] Starting script...")
			print("[Execute] ⚠️  Please click 'Yes' in the UAC window to grant admin rights")
			print("")

			# Launch script and wait for completion
			result = subprocess.run(powershell_cmd, capture_output=False)

			if result.returncode == 0:
				print("[Execute] ✅ Script execution completed")
			else:
				print(f"[Execute] ⚠️  Script return code: {result.returncode}")
			print("")

		except Exception as e:
			print(f"[Execute] ❌ Failed to launch script: {e}")
			print("")
			print("Please manually execute the following steps:")
			print("1. [In the VM] Open PowerShell as Administrator")
			print(f"2. Run the command: .\\{script.name} -PythonPid {current_pid}")
			print("")
			return False

		# Note: After tscon execution, RDP will disconnect - cannot manually press keys
		# Script will automatically wait for Console Session to stabilize
		print("\n⚠️  Note: After tscon executes, RDP connection will disconnect")
		print("     Script will automatically wait for Console Session to stabilize...")

		# Wait for Console Session to stabilize
		print(f"\nWaiting {wait_time} seconds for Console Session to stabilize...")
		for i in range(wait_time, 0, -1):
			print(f"  Countdown: {i} seconds", end='\r')
			await asyncio.sleep(1)
		print("\n")

		return True

	except Exception as e:
		print(f"\n❌ Failed to execute tscon script: {e}")
		import traceback
		traceback.print_exc()
		return False
