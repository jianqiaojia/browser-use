"""
Email Helper - 通过 Outlook 桌面版 COM/MAPI 读取邮件

使用 win32com.client 访问已登录的 Outlook 桌面版（经典版）邮箱，
无需任何 OAuth/API 注册，无需密码，直接读本地已认证的邮件数据。

前提：机器上已安装 Outlook 经典版，且 happyautoec@outlook.com 已登录。
"""

import re
import time
from datetime import datetime, timezone
from typing import Optional


_TARGET_EMAIL = "happyautoec@outlook.com"


def get_verification_code(
    sender_filter: str = "nike",
    subject_filter: str = "",
    not_before: float = 0.0,
    timeout_seconds: int = 60,
    poll_interval_seconds: float = 5.0,
) -> Optional[str]:
    """
    Poll Outlook inbox for a verification code email and extract the code.

    Uses Outlook desktop COM/MAPI - no OAuth or credentials needed,
    Outlook must already be running and signed in to happyautoec@outlook.com.

    Args:
        sender_filter: Case-insensitive substring to match sender address/name (default: "nike")
        subject_filter: Case-insensitive substring to match subject (default: "" = any)
        not_before: Unix timestamp (time.time()) — only accept emails received AFTER this time.
                    Defaults to 0 (no lower bound). Pass time.time() just before triggering
                    the login to avoid picking up stale verification emails.
        timeout_seconds: How long to poll before giving up
        poll_interval_seconds: How often to check for new emails

    Returns:
        Verification code string (e.g. "123456"), or None if not found
    """
    # If caller didn't specify not_before, default to "now minus 2 minutes" to
    # avoid picking up old codes that happen to still be in the inbox.
    if not_before == 0.0:
        not_before = time.time() - 120.0

    start_time = time.time()
    print(f"[EmailHelper] Polling for verification code via Outlook COM (timeout={timeout_seconds}s, not_before={not_before:.0f})...")

    while time.time() - start_time < timeout_seconds:
        try:
            code = _check_inbox_once(sender_filter, subject_filter, not_before)
            if code:
                return code
        except Exception as e:
            print(f"[EmailHelper] Outlook COM error: {e}")

        elapsed = time.time() - start_time
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            break
        print(f"[EmailHelper] Code not found, retrying in {poll_interval_seconds}s... ({elapsed:.0f}s elapsed)")
        time.sleep(min(poll_interval_seconds, remaining))

    print(f"[EmailHelper] Timed out, verification code not found")
    return None


def _check_inbox_once(
    sender_filter: str,
    subject_filter: str,
    not_before: float,
) -> Optional[str]:
    """Connect to Outlook via COM, search recent inbox emails, extract code."""
    import win32com.client

    # Use GetActiveObject to attach to the already-running Outlook instance.
    # This avoids triggering a fresh Exchange login (which fails on corp machines).
    # Falls back to Dispatch if Outlook is not running yet.
    try:
        outlook = win32com.client.GetActiveObject("Outlook.Application")
    except Exception:
        outlook = win32com.client.Dispatch("Outlook.Application")

    namespace = outlook.GetNamespace("MAPI")
    # Logon with ShowDialog=False, NewSession=False — reuse existing session,
    # don't pop up any auth dialogs, don't force a new MAPI session.
    try:
        namespace.Logon(ShowDialog=False, NewSession=False)
    except Exception:
        pass  # Already logged in, or non-Exchange account — ignore

    # Find the target account's inbox
    inbox = _get_inbox_for_account(namespace, _TARGET_EMAIL)
    if inbox is None:
        raise RuntimeError(
            f"Could not find inbox for {_TARGET_EMAIL}. "
            "Make sure Outlook is running and the account is signed in."
        )

    # Get messages sorted newest first
    messages = inbox.Items
    messages.Sort("[ReceivedTime]", True)  # True = descending

    cutoff_dt = datetime.fromtimestamp(not_before, tz=timezone.utc)

    checked = 0
    max_check = 50  # Don't iterate the whole inbox

    msg = messages.GetFirst()
    while msg is not None and checked < max_check:
        checked += 1
        try:
            # ReceivedTime is a pywintypes.datetime (timezone-naive, local time)
            received = msg.ReceivedTime
            # Convert to UTC-aware for comparison
            received_dt = _to_utc(received)
            if received_dt < cutoff_dt:
                break  # Sorted descending, so all following are older

            sender_addr = (getattr(msg, "SenderEmailAddress", "") or "").lower()
            sender_name = (getattr(msg, "SenderName", "") or "").lower()
            subject = (getattr(msg, "Subject", "") or "").lower()

            # Filter by sender
            if sender_filter:
                sf = sender_filter.lower()
                if sf not in sender_addr and sf not in sender_name and sf not in subject:
                    msg = messages.GetNext()
                    continue

            # Filter by subject
            if subject_filter and subject_filter.lower() not in subject:
                msg = messages.GetNext()
                continue

            print(f"[EmailHelper] Matched: '{msg.Subject}' from {msg.SenderEmailAddress} at {received_dt}")

            # Try plain text body first, fall back to HTML body
            body = getattr(msg, "Body", "") or ""
            if not body.strip():
                body = getattr(msg, "HTMLBody", "") or ""

            code = _extract_verification_code(body)
            if code:
                print(f"[EmailHelper] Extracted verification code: {code}")
                return code
            else:
                print(f"[EmailHelper] No code found in body preview: {body[:100]}")

        except Exception as e:
            print(f"[EmailHelper] Error reading message: {e}")

        msg = messages.GetNext()

    print(f"[EmailHelper] Checked {checked} message(s), no matching code found")
    return None


def _get_inbox_for_account(namespace, target_email: str):
    """Find the Inbox folder for the specified email account."""
    target_lower = target_email.lower()

    # Try all stores (each store = one account/mailbox)
    stores = namespace.Stores
    for i in range(1, stores.Count + 1):
        store = stores.Item(i)
        try:
            display_name = (store.DisplayName or "").lower()
            # Check if store name contains target email
            if target_lower in display_name:
                try:
                    return store.GetDefaultFolder(6)  # 6 = olFolderInbox
                except Exception:
                    pass
        except Exception:
            continue

    # Fallback: try ExchangeMailboxes or default inbox if only one account
    try:
        accounts = namespace.Accounts
        for i in range(1, accounts.Count + 1):
            acc = accounts.Item(i)
            try:
                addr = (acc.SmtpAddress or "").lower()
                if target_lower in addr:
                    # Use the account's delivery store
                    delivery_store = acc.DeliveryStore
                    return delivery_store.GetDefaultFolder(6)
            except Exception:
                continue
    except Exception:
        pass

    # Last resort: use the default inbox (works if there's only one account)
    try:
        return namespace.GetDefaultFolder(6)
    except Exception:
        return None


def _to_utc(pywintypes_dt) -> datetime:
    """Convert pywintypes.datetime (local time, no tzinfo) to UTC-aware datetime."""
    # pywintypes.datetime has tzinfo if Outlook provides it, otherwise naive local
    if hasattr(pywintypes_dt, 'tzinfo') and pywintypes_dt.tzinfo is not None:
        # Already has tzinfo - convert to UTC
        dt = datetime(
            pywintypes_dt.year, pywintypes_dt.month, pywintypes_dt.day,
            pywintypes_dt.hour, pywintypes_dt.minute, pywintypes_dt.second,
            tzinfo=pywintypes_dt.tzinfo
        )
        return dt.astimezone(timezone.utc)
    else:
        # Naive - assume local time, convert to UTC
        local_ts = time.mktime(pywintypes_dt.timetuple())
        return datetime.fromtimestamp(local_ts, tz=timezone.utc)


def _extract_verification_code(text: str) -> Optional[str]:
    """
    Extract a numeric verification code from email text.
    """
    if not text:
        return None

    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"&nbsp;|&#160;", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    # Pattern 1: "code" keyword followed by digits
    patterns = [
        r"(?:verification\s+code|your\s+code|enter\s+(?:the\s+)?code)[^\d]*(\d{4,8})",
        r"(\d{4,8})\s+is\s+your\s+(?:verification\s+)?code",
        r"(?:code|OTP|PIN)[:\s]+(\d{4,8})",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.IGNORECASE)
        if match:
            return match.group(1)

    # Pattern 2: standalone 6-or-8-digit number (Nike uses 8-digit codes)
    matches = re.findall(r"\b(\d{6,8})\b", clean)
    if matches:
        for m in matches:
            if not (2000 <= int(m) <= 2099):  # exclude years
                return m

    # Pattern 3: standalone 4-digit number
    matches = re.findall(r"\b(\d{4})\b", clean)
    if matches:
        return matches[0]

    return None


if __name__ == "__main__":
    # Quick test: fetch latest Nike email code
    print("Testing Outlook COM connection...")
    code = get_verification_code(timeout_seconds=10, poll_interval_seconds=2)
    if code:
        print(f"Found code: {code}")
    else:
        print("No code found (expected if no recent Nike email)")
