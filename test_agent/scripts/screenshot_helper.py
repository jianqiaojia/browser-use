"""
Screenshot helper utilities for test execution.

Provides utilities for capturing screenshots during test automation.
"""
from pathlib import Path
from datetime import datetime


def take_screenshot(
	prefix: str = "screenshot",
	output_dir: Path | str | None = None
) -> str | None:
	"""Take a screenshot of the entire screen and save to file.

	Args:
		prefix: Filename prefix (default: "screenshot")
		output_dir: Directory to save screenshots (default: "./screenshots")

	Returns:
		Screenshot file path if successful, None if failed

	Example:
		>>> path = take_screenshot(prefix="popup_detected")
		[Screenshot] 📸 Saved: screenshots/popup_detected_20250227_143022_123.png
		>>> print(path)
		screenshots/popup_detected_20250227_143022_123.png
	"""
	try:
		import pyautogui

		# Create screenshot directory
		if output_dir is None:
			screenshot_dir = Path("screenshots")
		else:
			screenshot_dir = Path(output_dir)

		screenshot_dir.mkdir(parents=True, exist_ok=True)

		# Generate filename with timestamp
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
		screenshot_path = screenshot_dir / f"{prefix}_{timestamp}.png"

		# Capture entire screen
		screenshot = pyautogui.screenshot()
		screenshot.save(str(screenshot_path))

		print(f"[Screenshot] 📸 Saved: {screenshot_path}", flush=True)
		return str(screenshot_path)

	except Exception as e:
		print(f"[Screenshot] ⚠️  Failed to capture screenshot: {e}", flush=True)
		return None


def take_screenshot_region(
	x: int,
	y: int,
	width: int,
	height: int,
	prefix: str = "region",
	output_dir: Path | str | None = None
) -> str | None:
	"""Take a screenshot of a specific region and save to file.

	Args:
		x: Left coordinate of region
		y: Top coordinate of region
		width: Width of region
		height: Height of region
		prefix: Filename prefix (default: "region")
		output_dir: Directory to save screenshots (default: "./screenshots")

	Returns:
		Screenshot file path if successful, None if failed

	Example:
		>>> path = take_screenshot_region(100, 100, 800, 600, prefix="popup")
		[Screenshot] 📸 Saved (region 100,100 800x600): screenshots/popup_20250227_143022_123.png
	"""
	try:
		import pyautogui

		# Create screenshot directory
		if output_dir is None:
			screenshot_dir = Path("screenshots")
		else:
			screenshot_dir = Path(output_dir)

		screenshot_dir.mkdir(parents=True, exist_ok=True)

		# Generate filename with timestamp
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
		screenshot_path = screenshot_dir / f"{prefix}_{timestamp}.png"

		# Capture specific region
		screenshot = pyautogui.screenshot(region=(x, y, width, height))
		screenshot.save(str(screenshot_path))

		print(f"[Screenshot] 📸 Saved (region {x},{y} {width}x{height}): {screenshot_path}", flush=True)
		return str(screenshot_path)

	except Exception as e:
		print(f"[Screenshot] ⚠️  Failed to capture screenshot: {e}", flush=True)
		return None
