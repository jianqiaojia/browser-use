"""
Test script to verify remote desktop disconnect/minimize causes GetCursorPos access denied errors

This script will:
1. Check if RDP minimize fix is already applied
2. Optionally apply the fix (requires admin)
3. Test GetCursorPos continuously
4. You can minimize RDP to verify the fix works

Usage:
	python test_agent\test_cursor_access.py
"""
import win32api
import winreg
import ctypes
import time
from datetime import datetime

def is_admin():
	"""Check if script is running with admin privileges"""
	try:
		return ctypes.windll.shell32.IsUserAnAdmin()
	except:
		return False

def check_rdp_fix():
	"""Check if RDP minimize fix is already applied"""
	try:
		key = winreg.OpenKey(
			winreg.HKEY_LOCAL_MACHINE,
			r"Software\Microsoft\Terminal Server Client",
			0,
			winreg.KEY_READ
		)
		value, type = winreg.QueryValueEx(key, "RemoteDesktop_SuppressWhenMinimized")
		winreg.CloseKey(key)
		return value == 2
	except FileNotFoundError:
		return False
	except Exception:
		return False

def apply_rdp_fix():
	"""Apply RDP minimize fix to registry"""
	if not is_admin():
		print("❌ Cannot apply fix: requires administrator privileges")
		return False

	try:
		key_path = r"Software\Microsoft\Terminal Server Client"
		key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path)
		winreg.SetValueEx(key, "RemoteDesktop_SuppressWhenMinimized", 0, winreg.REG_DWORD, 2)
		winreg.CloseKey(key)
		print("✅ RDP minimize fix applied successfully")
		print("   Note: You may need to reconnect your RDP session")
		return True
	except Exception as e:
		print(f"❌ Failed to apply fix: {e}")
		return False

def test_cursor_access():
	"""Continuously test GetCursorPos access"""
	print("=" * 60)
	print("Testing GetCursorPos Access (RDP Minimize Test)")
	print("=" * 60)

	# Check if fix is applied
	fix_applied = check_rdp_fix()
	if fix_applied:
		print("✅ RDP minimize fix is already applied")
		print("   RemoteDesktop_SuppressWhenMinimized = 2")
	else:
		print("⚠️  RDP minimize fix is NOT applied")
		print("   Without the fix, GetCursorPos will fail when RDP is minimized")

		if is_admin():
			print("\n   This script is running with admin privileges")
			response = input("   Apply the fix now? (yes/no): ")
			if response.lower() == 'yes':
				if apply_rdp_fix():
					print("\n   Fix applied! Please reconnect your RDP session")
					print("   Then run this script again to verify\n")
					return
		else:
			print("\n   To apply the fix, run this script as administrator:")
			print("   1. Right-click PowerShell/cmd -> 'Run as administrator'")
			print("   2. Run: python test_agent\\test_cursor_access.py")

	print("\n" + "=" * 60)
	print("Starting continuous GetCursorPos test...")
	print("=" * 60)
	print("Script will call GetCursorPos every 1 second")
	print("Minimize the remote desktop window to test if access is denied")
	print("Press Ctrl+C to stop\n")

	success_count = 0
	error_count = 0

	try:
		while True:
			timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
			try:
				pos = win32api.GetCursorPos()
				success_count += 1
				print(f"[{timestamp}] ✅ GetCursorPos success #{success_count}: {pos}")
			except Exception as e:
				error_count += 1
				print(f"[{timestamp}] ❌ GetCursorPos FAILED #{error_count}: {e}")
				print(f"[{timestamp}]    Error type: {type(e).__name__}")
				print(f"[{timestamp}]    Error details: {str(e)}")

				if not fix_applied:
					print(f"[{timestamp}]    💡 Hint: Run this script as admin to apply RDP fix")

			time.sleep(1)

	except KeyboardInterrupt:
		print("\n" + "=" * 60)
		print("Test stopped by user")
		print(f"Success: {success_count}, Errors: {error_count}")
		if error_count > 0 and not fix_applied:
			print("\n💡 To fix RDP minimize issues:")
			print("   Run this script as administrator and apply the registry fix")
		print("=" * 60)

if __name__ == "__main__":
	test_cursor_access()
