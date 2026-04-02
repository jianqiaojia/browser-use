"""
UIA Autofill Actions — wait for the Edge Express Checkout popup and select an autofill entry.

Both actions share a single UIAHelper instance created at registration time.
"""

import asyncio
import time

from pydantic import BaseModel
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.agent.views import ActionResult

from test_agent.scripts.uia_helper import UIAHelper


class UIAWaitForPopupModel(BaseModel):
	timeout: float = 10.0
	check_interval: float = 1.0


class UIASelectAutofillModel(BaseModel):
	profile_index: int = 0
	payment_index: int = 0


async def execute_uia_wait_for_popup(
	params: UIAWaitForPopupModel,
	uia_helper: UIAHelper,
) -> ActionResult:
	"""Poll until the autofill popup is visible or timeout expires."""
	print(f'[UIA] Waiting for autofill popup (timeout: {params.timeout}s, interval: {params.check_interval}s)...')
	start_time = time.time()
	check_count = 0

	while (time.time() - start_time) < params.timeout:
		check_count += 1
		try:
			result = uia_helper.find_autofill_popup()
			if result and result.get('success'):
				elapsed = time.time() - start_time
				msg = f'[UIA] ✅ Autofill popup detected after {elapsed:.1f}s ({check_count} checks)'
				print(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
		except Exception as e:
			print(f'[UIA] Check #{check_count} error: {str(e)}')
		await asyncio.sleep(params.check_interval)

	elapsed = time.time() - start_time
	msg = f'[UIA] ❌ Timeout: Autofill popup not detected after {elapsed:.1f}s ({check_count} checks)'
	print(msg)
	return ActionResult(error=msg, include_in_memory=True, success=False)


async def execute_uia_select_autofill(
	params: UIASelectAutofillModel,
	uia_helper: UIAHelper,
) -> ActionResult:
	"""Click the autofill button via UIA Helper."""
	print(f'[UIA] Clicking autofill button (profile_index: {params.profile_index}, payment_index: {params.payment_index})...')
	try:
		result = uia_helper.select_and_confirm(
			profile_index=params.profile_index,
			payment_index=params.payment_index,
		)
		if result.get('success'):
			msg = f'[UIA] ✅ Autofill selected at index {params.profile_index}'
			if result.get('warning'):
				msg += f' (warning: {result.get("warning")})'
			print(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)
		else:
			error = result.get('error', 'Unknown error')
			msg = f'[UIA] ❌ Failed to select autofill: {error}'
			print(msg)
			return ActionResult(error=msg, include_in_memory=True, success=False)
	except Exception as e:
		msg = f'[UIA] ❌ Unexpected error: {str(e)}'
		print(msg)
		return ActionResult(error=msg, include_in_memory=True, success=False)


def register_uia_autofill(registry: Registry) -> None:
	"""Register uia_wait_for_popup and uia_select_autofill actions."""
	uia_helper = UIAHelper()

	@registry.action(
		description=(
			'Wait for the Edge Express Checkout autofill popup to become visible. '
			'Polls repeatedly until detected or timeout expires. '
			'Call this after focusing an input field to confirm the popup appeared before proceeding.'
		),
		param_model=UIAWaitForPopupModel,
	)
	async def uia_wait_for_popup(
		params: UIAWaitForPopupModel,
		browser_session: BrowserSession,
	) -> ActionResult:
		return await execute_uia_wait_for_popup(params, uia_helper)

	@registry.action(
		description=(
			'Click the autofill button using UIA Helper — use this after popup is detected '
			'to trigger autofill and automatically fill the form.'
		),
		param_model=UIASelectAutofillModel,
	)
	async def uia_select_autofill(
		params: UIASelectAutofillModel,
	) -> ActionResult:
		return await execute_uia_select_autofill(params, uia_helper)
