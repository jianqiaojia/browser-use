"""
UIA Autofill Actions — trigger Edge Express Checkout popup and select an autofill entry.

Single combined action: cdp_click → select autofill, with auto-retry.
Uses CSS selector (not DOM index) for stable replay across page loads.
"""

import asyncio

from pydantic import BaseModel, Field
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.agent.views import ActionResult

from test_agent.scripts.uia_helper import UIAHelper


class TriggerAndAutofillModel(BaseModel):
	input_selector: str = Field(
		description='CSS selector of the input field to trigger Edge Express Checkout autofill popup (e.g. "#email" or "[name=\\"cardnumber\\"]")'
	)
	profile_index: int = Field(default=0, description='Index of the contact info profile to select (0 = first)')
	payment_index: int = Field(default=0, description='Index of the payment method to select (0 = first)')


async def execute_trigger_and_autofill(
	params: TriggerAndAutofillModel,
	uia_helper: UIAHelper,
	browser_session: BrowserSession,
	max_attempts: int = 3,
) -> ActionResult:
	"""Click input → select autofill, with retry loop."""
	from test_agent.actions.cdp_click import execute_cdp_click_by_selector

	for attempt in range(1, max_attempts + 1):
		print(f'\n[TriggerAndAutofill] Attempt {attempt}/{max_attempts}')

		click_result = await execute_cdp_click_by_selector(params.input_selector, browser_session)
		if click_result.error:
			print(f'[TriggerAndAutofill] cdp_click failed: {click_result.error}')
			await asyncio.sleep(1.0)
			continue

		select_result = uia_helper.select_and_confirm(
			profile_index=params.profile_index,
			payment_index=params.payment_index,
		)
		if select_result.get('success'):
			msg = f'[TriggerAndAutofill] ✅ Autofill selected (attempt {attempt})'
			if select_result.get('warning'):
				msg += f' (warning: {select_result["warning"]})'
			print(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)
		print(f'[TriggerAndAutofill] select failed: {select_result.get("error", "Unknown")}')

	msg = f'[TriggerAndAutofill] ❌ Failed after {max_attempts} attempts'
	print(msg)
	return ActionResult(error=msg, include_in_memory=True, success=False)


def register_uia_autofill(registry: Registry) -> None:
	"""Register trigger_and_autofill action."""
	uia_helper = UIAHelper()

	@registry.action(
		description=(
			'Trigger the Edge Express Checkout autofill popup by clicking an input field, '
			'then click the autofill button to fill the form. '
			'Automatically retries up to 3 times if the popup does not appear or disappears. '
			'Pass input_selector = CSS selector of the input field (e.g. "#email" or "[name=\\"cardnumber\\"]").'
		),
		param_model=TriggerAndAutofillModel,
	)
	async def trigger_and_autofill(
		params: TriggerAndAutofillModel,
		browser_session: BrowserSession,
	) -> ActionResult:
		return await execute_trigger_and_autofill(params, uia_helper, browser_session)
