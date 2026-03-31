"""Custom actions registration for browser automation - MIGRATED to browser-use v0.11.8"""
import os
import sys
import time
import asyncio
from typing import Optional

from browser_use import BrowserSession, Tools
from browser_use.agent.views import ActionResult

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel

from test_agent.config import config
from test_agent.actions.os_click import register_os_click
from test_agent.actions.cdp_click import register_cdp_click
from test_agent.scripts.uia_helper import UIAHelper
from test_agent.scripts.email_helper import async_get_baseline_entry_id, async_get_verification_code

class UIASelectAutofillModel(BaseModel):
    profile_index: int = 0
    payment_index: int = 0

class UIAWaitForPopupModel(BaseModel):
    timeout: float = 10.0
    check_interval: float = 0.3

class LogMonitorWaitForStateModel(BaseModel):
    expected_state: str = "AutofillSucceeded"
    timeout: float = 30.0

class EmailMarkBaselineModel(BaseModel):
    pass  # no params needed

class GetEmailVerificationCodeModel(BaseModel):
    sender_filter: str = "nike"
    subject_filter: str = ""
    timeout_seconds: int = 60

class SetSessionStorageAction(BaseModel):
    key: str
    value: str

def register_custom_actions(tools: Tools):
    """Register custom actions for test automation."""

    # Register os_click for real OS-level mouse clicks
    register_os_click(tools.registry)

    # Register cdp_click for CDP clicks with window focus management
    register_cdp_click(tools.registry)

    # Initialize UIA Helper instance (shared across all actions)
    uia_helper = UIAHelper()

    async def refresh_page(browser_session: BrowserSession) -> ActionResult:
        """Refresh the current page."""
        page = await browser_session.get_current_page()
        await page.reload()
        msg = '🔗 Refreshed the page'
        return ActionResult(extracted_content=msg, include_in_memory=False)

    @tools.action(
        description='Clear all cookies and session storage for a given domain, then reload the page. Use this to ensure a clean unauthenticated state before a test (e.g., sign-out without relying on UI).',
    )
    async def clear_site_data(domain: str, browser_session: BrowserSession) -> ActionResult:
        """Delete all cookies matching the domain and clear sessionStorage/localStorage."""
        # Filter cookies belonging to the target domain
        all_cookies = await browser_session.cookies()
        target = [c for c in all_cookies if domain in c.get('domain', '')]
        if target:
            # Clear all, then restore cookies not belonging to the target domain
            await browser_session._cdp_clear_cookies()
            keep = [c for c in all_cookies if domain not in c.get('domain', '')]
            if keep:
                await browser_session._cdp_set_cookies(keep)

        # Clear storage on the current page (best-effort)
        try:
            page = await browser_session.get_current_page()
            await page.evaluate('''() => {
                try { sessionStorage.clear(); } catch(e) {}
                try { localStorage.clear(); } catch(e) {}
            }''')
        except Exception:
            pass

        msg = f'✅ Cleared {len(target)} cookies and storage for domain: {domain}'
        print(msg)
        return ActionResult(extracted_content=msg, include_in_memory=True)
        
    @tools.action(
        description='Set a value in sessionStorage for the current page',
        param_model=SetSessionStorageAction,
    )
    async def set_session_storage(
        params: SetSessionStorageAction,
        browser_session: BrowserSession  # 新版参数
    ) -> ActionResult:
        """Set a value in sessionStorage"""
        page = await browser_session.get_current_page()
        try:
            await page.evaluate(
                "(key, value) => { sessionStorage.setItem(key, value); }",
                [params.key, params.value]
            )
            msg = f'🔧 Set sessionStorage[{params.key}] = {params.value}'
            return ActionResult(extracted_content=msg, include_in_memory=True)
        except Exception as e:
            msg = f'Failed to set sessionStorage: {str(e)}'
            return ActionResult(error=msg, include_in_memory=True)

    @tools.action(
        description='Wait for the Edge Express Checkout autofill popup to become visible. Polls repeatedly until detected or timeout expires. Call this after focusing an input field to confirm the popup appeared before proceeding.',
        param_model=UIAWaitForPopupModel
    )
    async def uia_wait_for_popup(
        params: UIAWaitForPopupModel,
        browser_session: BrowserSession  # 新版参数
    ) -> ActionResult:
        """Wait for autofill popup to appear with continuous monitoring"""
        print(f'🔍 Waiting for autofill popup (timeout: {params.timeout}s, interval: {params.check_interval}s)...')

        start_time = time.time()
        check_count = 0

        while (time.time() - start_time) < params.timeout:
            check_count += 1

            try:
                # 直接调用 find_autofill_popup 检测是否存在
                result = uia_helper.find_autofill_popup()

                if result and result.get('success'):
                    elapsed = time.time() - start_time
                    msg = f'✅ Autofill popup detected after {elapsed:.1f}s ({check_count} checks)'
                    print(msg)
                    return ActionResult(
                        extracted_content=msg,
                        include_in_memory=True,
                    )
            except Exception as e:
                print(f'Check #{check_count} failed: {str(e)}')

            await asyncio.sleep(params.check_interval)  # 新版：使用 asyncio.sleep

        elapsed = time.time() - start_time
        msg = f'❌ Timeout: Autofill popup not detected after {elapsed:.1f}s ({check_count} checks)'
        print(msg)
        return ActionResult(
            error=msg,
            include_in_memory=True,
            success=False
        )
    
    @tools.action(
        description='Click the autofill button using UIA Helper - use this after popup is detected to trigger autofill and automatically fill the form',
        param_model=UIASelectAutofillModel
    )
    async def uia_select_autofill(
        params: UIASelectAutofillModel,
    ) -> ActionResult:
        """Click the autofill button via UIA Helper to trigger autofill"""
        print(f'⚡ Clicking autofill button via UIA (profile_index: {params.profile_index}, payment_index: {params.payment_index})...')

        try:
            result = uia_helper.select_and_confirm(
                profile_index=params.profile_index,
                payment_index=params.payment_index
            )

            if result.get('success'):
                msg = f'✅ Successfully selected autofill option at index {params.profile_index}'
                if result.get('warning'):
                    msg += f' (Warning: {result.get("warning")})'
                print(msg)
                return ActionResult(
                    extracted_content=msg,
                    include_in_memory=True,
                )
            else:
                error = result.get('error', 'Unknown error')
                msg = f'❌ Failed to select autofill option: {error}'
                print(msg)
                return ActionResult(
                    error=msg,
                    include_in_memory=True,
                    success=False
                )
        except Exception as e:
            msg = f'❌ Failed to execute UIA select operation: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)
    
    # @tools.action(
    #     description='Verify that all profiles shown in the autofill popup are valid.',
    # )
    # async def uia_verify_popup_profiles(browser_session: BrowserSession) -> ActionResult:
    #     """Check that no invalid profiles are shown in the autofill popup."""
    #     import sqlite3, os as _os, re as _re
    #     print('🔍 Verifying popup profiles (UIA + DB cross-check)...')
    #     try:
    #         # --- Step 1: read popup profiles via UIA ---
    #         uia_result = uia_helper.get_popup_profile_names()
    #         if not uia_result.get('success'):
    #             msg = f'❌ UIA failed to read popup: {uia_result.get("error")}'
    #             print(msg)
    #             return ActionResult(error=msg, include_in_memory=True, success=False)
    #
    #         popup_profiles = uia_result['profiles']
    #         print(f'  UIA: {len(popup_profiles)} profile(s) in popup')
    #
    #         # --- Step 2: load all addresses from Edge Web Data ---
    #         web_data_path = _os.path.join(config.user_data_dir, config.profile, 'Web Data')
    #         db_profiles: dict[str, dict] = {}
    #         if _os.path.exists(web_data_path):
    #             try:
    #                 conn = sqlite3.connect(f'file:{web_data_path}?mode=ro&immutable=1', uri=True)
    #                 FIELD_TYPES = {3: 'name', 9: 'email', 14: 'phone', 35: 'zip', 22: 'city'}
    #                 rows = conn.execute(
    #                     'SELECT guid, type, value FROM address_type_tokens WHERE type IN (3,9,14,35,22)'
    #                 ).fetchall()
    #                 conn.close()
    #                 for guid, type_code, value in rows:
    #                     if guid not in db_profiles:
    #                         db_profiles[guid] = {}
    #                     db_profiles[guid][FIELD_TYPES[type_code]] = value or ''
    #             except Exception as db_err:
    #                 print(f'  DB lookup error: {db_err}')
    #
    #         # --- Step 3: validity check helpers ---
    #         def _is_invalid_name(v: str) -> bool:
    #             return len(v.strip()) <= 2 or v.strip().isdigit()
    #         def _is_invalid_zip(v: str) -> bool:
    #             return len(v.strip()) <= 2 or v.strip().isdigit() and len(v.strip()) < 4
    #         def _is_invalid_phone(v: str) -> bool:
    #             digits = _re.sub(r'\D', '', v)
    #             return len(digits) < 7
    #         def _is_invalid_email(v: str) -> bool:
    #             return not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', v.strip())
    #         def _is_invalid_city(v: str) -> bool:
    #             return len(v.strip()) <= 2 or v.strip().isdigit()
    #         def _check_profile(fields: dict) -> list[str]:
    #             issues = []
    #             if _is_invalid_name(fields.get('name', '')):
    #                 issues.append(f"name={repr(fields.get('name', ''))}")
    #             if fields.get('zip') and _is_invalid_zip(fields.get('zip', '')):
    #                 issues.append(f"zip={repr(fields.get('zip', ''))}")
    #             if fields.get('phone') and _is_invalid_phone(fields.get('phone', '')):
    #                 issues.append(f"phone={repr(fields.get('phone', ''))}")
    #             if fields.get('email') and _is_invalid_email(fields.get('email', '')):
    #                 issues.append(f"email={repr(fields.get('email', ''))}")
    #             if fields.get('city') and _is_invalid_city(fields.get('city', '')):
    #                 issues.append(f"city={repr(fields.get('city', ''))}")
    #             return issues
    #
    #         # --- Step 4: get log monitor summary ---
    #         log_monitor_available = (
    #             hasattr(browser_session, '_custom_data')
    #             and 'log_monitor' in browser_session._custom_data
    #         )
    #         filtered_guids: set[str] = set()
    #         valid_guids: set[str] = set()
    #         if log_monitor_available:
    #             monitor = browser_session._custom_data['log_monitor']
    #             monitor.check_new_states()
    #             summary = monitor.get_filter_summary()
    #             filtered_guids = set(summary['failed'].keys())
    #             valid_guids = set(summary['valid'])
    #
    #         guid_to_name: dict[str, str] = {
    #             guid: fields.get('name', '').strip()
    #             for guid, fields in db_profiles.items()
    #             if fields.get('name', '').strip()
    #         }
    #
    #         # --- Step 5: match popup buttons to DB guids ---
    #         def _match_guid(raw: str) -> str | None:
    #             raw_lower = raw.lower()
    #             candidates = valid_guids if valid_guids else set(guid_to_name.keys())
    #             for guid in candidates:
    #                 name = guid_to_name.get(guid, '').lower()
    #                 if name and name in raw_lower:
    #                     return guid
    #             for guid, name in guid_to_name.items():
    #                 if name.lower() in raw_lower:
    #                     return guid
    #             return None
    #
    #         invalid_shown: list[str] = []
    #         valid_shown: list[str] = []
    #         skipped: list[str] = []
    #         for raw in popup_profiles:
    #             matched_guid = _match_guid(raw)
    #             if matched_guid is None:
    #                 skipped.append(f'  ⏭  skipped (no DB match): {raw[:60]!r}')
    #                 print(skipped[-1])
    #                 continue
    #             db_fields = db_profiles[matched_guid]
    #             issues = _check_profile(db_fields)
    #             guid_str = matched_guid[:8] + '...'
    #             if matched_guid in filtered_guids:
    #                 reason = summary['failed'][matched_guid] if log_monitor_available else '?'
    #                 msg_line = f'  ❌ INVALID (log filtered) guid={guid_str} reason={reason} name={repr(db_fields.get("name",""))}'
    #                 print(msg_line)
    #                 invalid_shown.append(msg_line)
    #             elif issues:
    #                 msg_line = f'  ❌ INVALID (DB check) guid={guid_str} issues: {", ".join(issues)}'
    #                 print(msg_line)
    #                 invalid_shown.append(msg_line)
    #             else:
    #                 msg_line = f'  ✅ valid  guid={guid_str} name={repr(db_fields.get("name", ""))}'
    #                 print(msg_line)
    #                 valid_shown.append(msg_line)
    #
    #         # --- Step 6: log/UIA cross-check ---
    #         log_cross_check = ''
    #         if log_monitor_available:
    #             popup_matched_guids = {_match_guid(raw) for raw in popup_profiles} - {None}
    #             leaked_filtered = filtered_guids & popup_matched_guids
    #             missing_valid = valid_guids - popup_matched_guids
    #             if leaked_filtered:
    #                 log_cross_check += f'\n  ⚠️  LOG/UIA MISMATCH: log filtered but shown in popup: {leaked_filtered}'
    #             if missing_valid:
    #                 log_cross_check += f'\n  ℹ️  Log-valid guid(s) not found in popup: {missing_valid}'
    #             if not leaked_filtered and not missing_valid:
    #                 log_cross_check += f'\n  ✅ Log/UIA consistent: {len(filtered_guids)} filtered, {len(valid_guids)} valid'
    #
    #         # --- Final verdict ---
    #         if invalid_shown:
    #             msg = (f'❌ FAIL: {len(invalid_shown)} invalid profile(s) shown in popup:\n'
    #                    + '\n'.join(invalid_shown)
    #                    + (f'\n{log_cross_check}' if log_cross_check else ''))
    #             print(msg)
    #             return ActionResult(error=msg, include_in_memory=True, success=False)
    #         else:
    #             msg = (f'✅ PASS: {len(valid_shown)} profile(s) in popup, all valid.\n'
    #                    + '\n'.join(valid_shown)
    #                    + (f'\n{log_cross_check}' if log_cross_check else ''))
    #             print(msg)
    #             return ActionResult(extracted_content=msg, include_in_memory=True)
    #
    #     except Exception as e:
    #         msg = f'❌ Error in uia_verify_popup_profiles: {str(e)}'
    #         print(msg)
    #         import traceback; traceback.print_exc()
    #         return ActionResult(error=msg, include_in_memory=True, success=False)

    @tools.action(
        description='Initialize log file monitor for tracking browser state changes. Call this before the action you want to monitor.',
    )
    async def logmonitor_init(browser_session: BrowserSession) -> ActionResult:
        """Initialize log file monitor for checkout state tracking"""
        try:
            print('🔧 Initializing log file monitor...')
            
            # Import LogFileMonitor
            from test_agent.scripts.log_file_monitor import LogFileMonitor
            
            # 新版：将监视器存储在 browser_session 的自定义属性中
            log_path = config.log_file_path
            
            # 创建自定义属性存储
            if not hasattr(browser_session, '_custom_data'):
                browser_session._custom_data = {}
            
            browser_session._custom_data['log_monitor'] = LogFileMonitor(log_file_path=log_path)
            
            # Initialize position (read to current end of file)
            browser_session._custom_data['log_monitor'].check_new_states()
            
            msg = f'✅ Log file monitor initialized. Monitoring: {log_path}'
            print(msg)
            return ActionResult(extracted_content=msg, include_in_memory=True)
            
        except Exception as e:
            msg = f'❌ Failed to initialize log monitor: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)
    
    @tools.action(
        description='Wait for a specific state to appear in the log file (e.g., AutofillSucceeded, AutofillFailed). Call logmonitor_init first.',
        param_model=LogMonitorWaitForStateModel
    )
    async def logmonitor_wait_for_state(
        params: LogMonitorWaitForStateModel,
        browser_session: BrowserSession
    ) -> ActionResult:
        """Wait for checkout state to reach expected value by monitoring log file"""
        try:
            if not hasattr(browser_session, '_custom_data') or 'log_monitor' not in browser_session._custom_data:
                msg = '❌ Log monitor not initialized. Call logmonitor_init first.'
                print(msg)
                return ActionResult(error=msg, include_in_memory=True, success=False)

            print(f'⏳ Waiting for checkout state: {params.expected_state} (timeout: {params.timeout}s)...')
            monitor = browser_session._custom_data['log_monitor']
            result = await monitor.wait_for_state(params.expected_state, params.timeout)

            if result['success']:
                msg = f'✅ Checkout state reached {params.expected_state} after {result["elapsed"]:.1f}s'
                print(msg)
                return ActionResult(extracted_content=msg, include_in_memory=True)
            else:
                msg = (f'❌ Timeout: {params.expected_state} not reached after {result["elapsed"]:.1f}s '
                       f'(checked {result["check_count"]} times). States: {result["states_seen"]}')
                print(msg)
                return ActionResult(error=msg, include_in_memory=True, success=False)

        except Exception as e:
            msg = f'❌ Failed to wait for checkout state: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)
    
    @tools.action(
        description='Get all state changes detected so far by the log file monitor.',
    )
    async def logmonitor_get_history(browser_session: BrowserSession) -> ActionResult:
        """Get checkout state change history from log file"""
        try:
            if not hasattr(browser_session, '_custom_data') or 'log_monitor' not in browser_session._custom_data:
                msg = 'Log monitor not initialized. No state history available.'
                return ActionResult(extracted_content=msg, include_in_memory=True)
            
            monitor = browser_session._custom_data['log_monitor']
            states = monitor.states_history
            
            if not states:
                msg = 'No checkout state changes detected in log file yet'
            else:
                states_list = [s['state_name'] for s in states]
                msg = f'Checkout state history ({len(states)} changes): {states_list}'
            
            print(msg)
            return ActionResult(extracted_content=msg, include_in_memory=True)
            
        except Exception as e:
            return ActionResult(error=f'❌ Error reading state history: {str(e)}', include_in_memory=True, success=False)

    @tools.action(
        description='Get profile filter results from the log monitor. Returns each profile GUID that was evaluated, whether it passed or failed the filter, the failed reason code, and the profile field details (name, email, phone, zip, city) looked up from the Edge address database. Call logmonitor_init first, then trigger the autofill popup, then call this to see which profiles were filtered and why.',
    )
    async def logmonitor_get_filter_results(browser_session: BrowserSession) -> ActionResult:
        """Read profile filter events from log and enrich with field data from Edge Web Data DB."""
        try:
            if not hasattr(browser_session, '_custom_data') or 'log_monitor' not in browser_session._custom_data:
                msg = '❌ Log monitor not initialized. Call logmonitor_init first.'
                return ActionResult(error=msg, include_in_memory=True, success=False)

            monitor = browser_session._custom_data['log_monitor']
            web_data_path = os.path.join(config.user_data_dir, config.profile, 'Web Data')
            result = monitor.get_filter_report(web_data_path)

            if result['empty']:
                msg = 'No profile filter events found in log. Make sure --vmodule=shipping_address_form=2 is set and the popup was triggered.'
                return ActionResult(extracted_content=msg, include_in_memory=True)

            msg = (f'Profile filter results ({len(result["failed"])} filtered, {len(result["valid"])} valid):\n'
                   + '\n'.join(result['report_lines']))
            print(msg)
            return ActionResult(extracted_content=msg, include_in_memory=True)

        except Exception as e:
            msg = f'❌ Error getting filter results: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)

    @tools.action(
        description='Mark email baseline — call this BEFORE triggering any login flow that may send a verification email. Records the current newest email EntryID so that get_email_verification_code only returns codes from emails that arrive after this point.',
    )
    async def email_mark_baseline(browser_session: BrowserSession) -> ActionResult:
        """Record current inbox head so we can ignore pre-existing emails."""
        print('📧 Marking email baseline (recording current inbox head)...')
        try:
            entry_id = await async_get_baseline_entry_id()
            # Store in session so get_email_verification_code can use it
            if not hasattr(browser_session, '_custom_data'):
                browser_session._custom_data = {}
            browser_session._custom_data['email_baseline_entry_id'] = entry_id
            msg = f'✅ Email baseline set ({"inbox empty" if entry_id is None else "EntryID recorded"})'
            print(msg)
            return ActionResult(extracted_content=msg, include_in_memory=True)
        except Exception as e:
            msg = f'❌ Failed to mark email baseline: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)

    @tools.action(
        description='Get email verification code from Outlook inbox — polls for a new email that arrived AFTER email_mark_baseline was called, and extracts the numeric verification code. Call email_mark_baseline first.',
        param_model=GetEmailVerificationCodeModel
    )
    async def get_email_verification_code(
        params: GetEmailVerificationCodeModel,
        browser_session: BrowserSession
    ) -> ActionResult:
        """Poll Outlook inbox for a Nike verification code email newer than the baseline."""
        baseline = None
        if hasattr(browser_session, '_custom_data'):
            baseline = browser_session._custom_data.get('email_baseline_entry_id')
        print(f'📧 Polling for email verification code (baseline={"set" if baseline else "unset"}, timeout={params.timeout_seconds}s)...')
        try:
            code = await async_get_verification_code(
                baseline_entry_id=baseline,
                sender_filter=params.sender_filter,
                subject_filter=params.subject_filter,
                timeout_seconds=params.timeout_seconds,
            )
            if code:
                msg = f'✅ Got verification code: {code}'
                print(msg)
                return ActionResult(extracted_content=msg, include_in_memory=True)
            else:
                msg = f'❌ Verification code not found within {params.timeout_seconds}s'
                print(msg)
                return ActionResult(error=msg, include_in_memory=True, success=False)
        except Exception as e:
            msg = f'❌ Error getting verification code: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)