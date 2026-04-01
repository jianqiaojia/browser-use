"""
Log Monitor Actions — track browser state changes via a log file.

All four actions share state through browser_session._custom_data['log_monitor'].
"""

import os

from pydantic import BaseModel
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.agent.views import ActionResult

from test_agent.config import config


class LogMonitorWaitForStateModel(BaseModel):
	expected_state: str = 'AutofillSucceeded'
	timeout: float = 30.0


def _get_monitor(browser_session: BrowserSession):
	"""Return the log monitor stored on the session, or None."""
	if hasattr(browser_session, '_custom_data'):
		return browser_session._custom_data.get('log_monitor')
	return None


def register_log_monitor(registry: Registry) -> None:
	"""Register logmonitor_init, logmonitor_wait_for_state, logmonitor_get_history, logmonitor_get_filter_results."""

	@registry.action(
		description='Initialize log file monitor for tracking browser state changes. Call this before the action you want to monitor.',
	)
	async def logmonitor_init(browser_session: BrowserSession) -> ActionResult:
		"""Initialize log file monitor for checkout state tracking."""
		try:
			print('🔧 Initializing log file monitor...')
			from test_agent.scripts.log_file_monitor import LogFileMonitor

			if not hasattr(browser_session, '_custom_data'):
				browser_session._custom_data = {}

			log_path = config.log_file_path
			browser_session._custom_data['log_monitor'] = LogFileMonitor(log_file_path=log_path)
			browser_session._custom_data['log_monitor'].check_new_states()

			msg = f'✅ Log file monitor initialized. Monitoring: {log_path}'
			print(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)
		except Exception as e:
			msg = f'❌ Failed to initialize log monitor: {str(e)}'
			print(msg)
			return ActionResult(error=msg, include_in_memory=True, success=False)

	@registry.action(
		description='Wait for a specific state to appear in the log file (e.g., AutofillSucceeded, AutofillFailed). Call logmonitor_init first.',
		param_model=LogMonitorWaitForStateModel,
	)
	async def logmonitor_wait_for_state(
		params: LogMonitorWaitForStateModel,
		browser_session: BrowserSession,
	) -> ActionResult:
		"""Wait for checkout state to reach expected value by monitoring log file."""
		try:
			monitor = _get_monitor(browser_session)
			if monitor is None:
				msg = '❌ Log monitor not initialized. Call logmonitor_init first.'
				print(msg)
				return ActionResult(error=msg, include_in_memory=True, success=False)

			print(f'⏳ Waiting for checkout state: {params.expected_state} (timeout: {params.timeout}s)...')
			result = await monitor.wait_for_state(params.expected_state, params.timeout)

			if result['success']:
				msg = f'✅ Checkout state reached {params.expected_state} after {result["elapsed"]:.1f}s'
				print(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
			else:
				msg = (
					f'❌ Timeout: {params.expected_state} not reached after {result["elapsed"]:.1f}s '
					f'(checked {result["check_count"]} times). States: {result["states_seen"]}'
				)
				print(msg)
				return ActionResult(error=msg, include_in_memory=True, success=False)
		except Exception as e:
			msg = f'❌ Failed to wait for checkout state: {str(e)}'
			print(msg)
			return ActionResult(error=msg, include_in_memory=True, success=False)

	@registry.action(
		description='Get all state changes detected so far by the log file monitor.',
	)
	async def logmonitor_get_history(browser_session: BrowserSession) -> ActionResult:
		"""Get checkout state change history from log file."""
		try:
			monitor = _get_monitor(browser_session)
			if monitor is None:
				msg = 'Log monitor not initialized. No state history available.'
				return ActionResult(extracted_content=msg, include_in_memory=True)

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

	@registry.action(
		description=(
			'Get profile filter results from the log monitor. '
			'Returns each profile GUID that was evaluated, whether it passed or failed the filter, '
			'the failed reason code, and the profile field details (name, email, phone, zip, city) '
			'looked up from the Edge address database. '
			'Call logmonitor_init first, then trigger the autofill popup, '
			'then call this to see which profiles were filtered and why.'
		),
	)
	async def logmonitor_get_filter_results(browser_session: BrowserSession) -> ActionResult:
		"""Read profile filter events from log and enrich with field data from Edge Web Data DB."""
		try:
			monitor = _get_monitor(browser_session)
			if monitor is None:
				msg = '❌ Log monitor not initialized. Call logmonitor_init first.'
				return ActionResult(error=msg, include_in_memory=True, success=False)

			web_data_path = os.path.join(config.user_data_dir, config.profile, 'Web Data')
			result = monitor.get_filter_report(web_data_path)

			if result['empty']:
				msg = (
					'No profile filter events found in log. '
					'Make sure --vmodule=shipping_address_form=2 is set and the popup was triggered.'
				)
				return ActionResult(extracted_content=msg, include_in_memory=True)

			msg = (
				f'Profile filter results ({len(result["failed"])} filtered, {len(result["valid"])} valid):\n'
				+ '\n'.join(result['report_lines'])
			)
			print(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)
		except Exception as e:
			msg = f'❌ Error getting filter results: {str(e)}'
			print(msg)
			return ActionResult(error=msg, include_in_memory=True, success=False)
