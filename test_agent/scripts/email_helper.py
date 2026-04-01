"""
Email Helper - 通过 Outlook 桌面版 COM/MAPI 读取邮件

使用 win32com.client 访问已登录的 Outlook 桌面版（经典版）邮箱，
无需任何 OAuth/API 注册，无需密码，直接读本地已认证的邮件数据。

前提：机器上已安装 Outlook 经典版，且 happyautoec@outlook.com 已登录。

设计：
- 两阶段 API：get_baseline_entry_id() + get_verification_code()
  在触发登录前调用 get_baseline_entry_id() 记录当前收件箱最新邮件的 EntryID，
  之后只看比这个 ID 更新的邮件，与时钟完全无关。
  如果未传入 baseline，则回退到最近 2 分钟的时间窗口。
- COM 调用放线程池：不阻塞 asyncio event loop。
"""

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional


_TARGET_EMAIL = "happyautoec@outlook.com"


# ---------------------------------------------------------------------------
# Outlook COM helpers (all synchronous, intended to run in a thread executor)
# ---------------------------------------------------------------------------

def _ensure_outlook_running() -> None:
    """Launch Outlook if it's not already running. Waits up to 15s for it to start."""
    import subprocess

    # Check if outlook.exe process is alive
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE", "/NH"],
        capture_output=True, text=True
    )
    if "OUTLOOK.EXE" in result.stdout:
        return  # already running

    print("[EmailHelper] Outlook not running, attempting to launch...")
    outlook_paths = [
        r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
        r"C:\Program Files\Microsoft Office\Office16\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\Office16\OUTLOOK.EXE",
    ]
    launched = False
    for path in outlook_paths:
        if os.path.exists(path):
            subprocess.Popen([path])
            launched = True
            print(f"[EmailHelper] Launched Outlook from {path}")
            break

    if not launched:
        # Try via shell association
        try:
            subprocess.Popen(["start", "outlook"], shell=True)
            launched = True
            print("[EmailHelper] Launched Outlook via shell")
        except Exception as e:
            print(f"[EmailHelper] Failed to launch Outlook: {e}")
            return

    # Wait for Outlook to initialize (up to 15s)
    for i in range(15):
        time.sleep(1)
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE", "/NH"],
            capture_output=True, text=True
        )
        if "OUTLOOK.EXE" in result.stdout:
            print(f"[EmailHelper] Outlook started after {i+1}s")
            time.sleep(3)  # extra wait for COM registration
            return
    print("[EmailHelper] Warning: Outlook may not have started correctly")


def _get_outlook_inbox():
    """Return the Inbox folder for _TARGET_EMAIL via COM. Raises on failure."""
    import win32com.client

    try:
        outlook = win32com.client.GetActiveObject("Outlook.Application")
    except Exception:
        # Outlook not running — launch it and retry once
        _ensure_outlook_running()
        try:
            outlook = win32com.client.GetActiveObject("Outlook.Application")
        except Exception:
            outlook = win32com.client.Dispatch("Outlook.Application")

    namespace = outlook.GetNamespace("MAPI")
    try:
        namespace.Logon(ShowDialog=False, NewSession=False)
    except Exception:
        pass

    inbox = _get_inbox_for_account(namespace, _TARGET_EMAIL)
    if inbox is None:
        raise RuntimeError(
            f"Could not find inbox for {_TARGET_EMAIL}. "
            "Make sure Outlook is running and the account is signed in."
        )
    return inbox


def get_baseline_entry_id() -> Optional[str]:
    """
    Record the current newest email's EntryID in the inbox.
    Call this BEFORE triggering any login flow that sends a verification email.
    Pass the returned value to get_verification_code() so only emails that
    arrive after this point are considered.
    Returns None if the inbox is empty (get_verification_code will fall back
    to a 2-minute recency window).
    """
    try:
        inbox = _get_outlook_inbox()
        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)  # newest first
        msg = messages.GetFirst()
        if msg is None:
            return None
        return str(msg.EntryID)
    except Exception as e:
        print(f"[EmailHelper] get_baseline_entry_id failed: {e}")
        return None


def get_verification_code(
    baseline_entry_id: Optional[str] = None,
    sender_filter: str = "nike",
    subject_filter: str = "",
    timeout_seconds: int = 60,
    poll_interval_seconds: float = 3.0,
) -> Optional[str]:
    """
    Poll Outlook inbox for a verification code email newer than baseline_entry_id.

    Args:
        baseline_entry_id: EntryID returned by get_baseline_entry_id(), called
                           just before triggering the login. Only emails that
                           arrived AFTER this message are considered.
                           If None, falls back to emails from the last 2 minutes.
        sender_filter: Case-insensitive substring to match sender (default: "nike")
        subject_filter: Case-insensitive substring to match subject (default: "" = any)
        timeout_seconds: How long to poll before giving up
        poll_interval_seconds: How often to re-check

    Returns:
        Verification code string, or None if not found within timeout
    """
    start_time = time.time()
    print(
        f"[EmailHelper] Polling for code "
        f"(baseline={'set' if baseline_entry_id else 'unset, using 2-min window'}, "
        f"timeout={timeout_seconds}s)..."
    )

    # Connect once and reuse across all poll iterations
    try:
        inbox = _get_outlook_inbox()
    except Exception as e:
        print(f"[EmailHelper] Failed to open inbox: {e}")
        return None

    while time.time() - start_time < timeout_seconds:
        try:
            code = _check_inbox_once(inbox, sender_filter, subject_filter, baseline_entry_id)
            if code:
                return code
        except Exception as e:
            print(f"[EmailHelper] Outlook COM error: {e}, reconnecting...")
            # COM object may have gone stale — reconnect once
            try:
                inbox = _get_outlook_inbox()
            except Exception as e2:
                print(f"[EmailHelper] Reconnect failed: {e2}")

        elapsed = time.time() - start_time
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            break
        print(f"[EmailHelper] Not found yet, retrying in {poll_interval_seconds}s... ({elapsed:.0f}s elapsed)")
        time.sleep(min(poll_interval_seconds, remaining))

    print("[EmailHelper] Timed out, verification code not found")
    return None


def _check_inbox_once(
    inbox,
    sender_filter: str,
    subject_filter: str,
    baseline_entry_id: Optional[str] = None,
) -> Optional[str]:
    """Single pass over inbox messages newer than baseline_entry_id (or last 2 min if None)."""
    messages = inbox.Items
    messages.Sort("[ReceivedTime]", True)  # newest first

    # Fallback cutoff when no baseline is provided
    fallback_cutoff_dt: Optional[datetime] = None
    if baseline_entry_id is None:
        fallback_cutoff_dt = datetime.fromtimestamp(time.time() - 120.0, tz=timezone.utc)

    checked = 0
    max_check = 100

    msg = messages.GetFirst()
    while msg is not None and checked < max_check:
        checked += 1
        try:
            entry_id = str(msg.EntryID)

            # Stop when we reach the baseline message (inclusive — it's a pre-existing email)
            if baseline_entry_id and entry_id == baseline_entry_id:
                break

            # Fallback: stop at the time-based cutoff
            if fallback_cutoff_dt is not None:
                received_dt = _to_utc(msg.ReceivedTime)
                if received_dt < fallback_cutoff_dt:
                    break

            sender_addr = (getattr(msg, "SenderEmailAddress", "") or "").lower()
            sender_name = (getattr(msg, "SenderName", "") or "").lower()
            subject = (getattr(msg, "Subject", "") or "").lower()

            if sender_filter:
                sf = sender_filter.lower()
                if sf not in sender_addr and sf not in sender_name and sf not in subject:
                    msg = messages.GetNext()
                    continue

            if subject_filter and subject_filter.lower() not in subject:
                msg = messages.GetNext()
                continue

            received_dt = _to_utc(msg.ReceivedTime)
            print(f"[EmailHelper] Matched: '{msg.Subject}' from {msg.SenderEmailAddress} at {received_dt}")

            body = getattr(msg, "Body", "") or ""
            if not body.strip():
                body = getattr(msg, "HTMLBody", "") or ""

            code = _extract_verification_code(body)
            if code:
                print(f"[EmailHelper] Extracted verification code: {code}")
                return code
            else:
                print(f"[EmailHelper] No code in body: {body[:120]!r}")

        except Exception as e:
            print(f"[EmailHelper] Error reading message: {e}")

        msg = messages.GetNext()

    print(f"[EmailHelper] Checked {checked} new message(s), no matching code found")
    return None


# ---------------------------------------------------------------------------
# Async wrappers — run COM calls in thread pool so event loop isn't blocked
# ---------------------------------------------------------------------------

async def async_get_baseline_entry_id() -> Optional[str]:
    """Async wrapper for get_baseline_entry_id()."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_baseline_entry_id)


async def async_get_verification_code(
    baseline_entry_id: Optional[str] = None,
    sender_filter: str = "nike",
    subject_filter: str = "",
    timeout_seconds: int = 60,
    poll_interval_seconds: float = 3.0,
) -> Optional[str]:
    """Async wrapper for get_verification_code() — safe to await in action handlers."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: get_verification_code(
            baseline_entry_id=baseline_entry_id,
            sender_filter=sender_filter,
            subject_filter=subject_filter,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_inbox_for_account(namespace, target_email: str):
    """Find the Inbox folder for the specified email account."""
    target_lower = target_email.lower()

    stores = namespace.Stores
    for i in range(1, stores.Count + 1):
        store = stores.Item(i)
        try:
            display_name = (store.DisplayName or "").lower()
            if target_lower in display_name:
                try:
                    return store.GetDefaultFolder(6)  # olFolderInbox
                except Exception:
                    pass
        except Exception:
            continue

    try:
        accounts = namespace.Accounts
        for i in range(1, accounts.Count + 1):
            acc = accounts.Item(i)
            try:
                addr = (acc.SmtpAddress or "").lower()
                if target_lower in addr:
                    delivery_store = acc.DeliveryStore
                    return delivery_store.GetDefaultFolder(6)
            except Exception:
                continue
    except Exception:
        pass

    try:
        return namespace.GetDefaultFolder(6)
    except Exception:
        return None


def _to_utc(pywintypes_dt) -> datetime:
    """Convert pywintypes.datetime to UTC-aware datetime."""
    if hasattr(pywintypes_dt, "tzinfo") and pywintypes_dt.tzinfo is not None:
        dt = datetime(
            pywintypes_dt.year, pywintypes_dt.month, pywintypes_dt.day,
            pywintypes_dt.hour, pywintypes_dt.minute, pywintypes_dt.second,
            tzinfo=pywintypes_dt.tzinfo,
        )
        return dt.astimezone(timezone.utc)
    else:
        local_ts = time.mktime(pywintypes_dt.timetuple())
        return datetime.fromtimestamp(local_ts, tz=timezone.utc)


def _extract_verification_code(text: str) -> Optional[str]:
    """Extract a numeric verification code from email body text."""
    if not text:
        return None

    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"&nbsp;|&#160;", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    patterns = [
        r"(?:verification\s+code|your\s+code|enter\s+(?:the\s+)?code)[^\d]*(\d{4,8})",
        r"(\d{4,8})\s+is\s+your\s+(?:verification\s+)?code",
        r"(?:code|OTP|PIN)[:\s]+(\d{4,8})",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.IGNORECASE)
        if match:
            return match.group(1)

    # Standalone 6-8 digit number (Nike uses 8-digit codes)
    matches = re.findall(r"\b(\d{6,8})\b", clean)
    for m in matches:
        if not (2000 <= int(m) <= 2099):
            return m

    # Standalone 4-digit number
    matches = re.findall(r"\b(\d{4})\b", clean)
    if matches:
        return matches[0]

    return None


if __name__ == "__main__":
    print("Testing Outlook COM connection...")
    print("Polling verification code (last 2 min)...")
    code = get_verification_code(timeout_seconds=10, poll_interval_seconds=2)
    if code:
        print(f"Found code: {code}")
    else:
        print("No code found (expected if no recent Nike email)")
