"""
Clear Site Data & Session Storage Actions
"""

import os
from pydantic import BaseModel
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.agent.views import ActionResult


class SetSessionStorageModel(BaseModel):
	key: str
	value: str


async def execute_clear_site_data(domain: str, browser_session: BrowserSession) -> ActionResult:
	"""Delete all cookies matching the domain and clear sessionStorage/localStorage."""
	all_cookies = await browser_session.cookies()
	target = [c for c in all_cookies if domain in c.get('domain', '')]
	if target:
		await browser_session._cdp_clear_cookies()
		keep = [c for c in all_cookies if domain not in c.get('domain', '')]
		if keep:
			await browser_session._cdp_set_cookies(keep)

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


async def execute_set_session_storage(
	params: SetSessionStorageModel,
	browser_session: BrowserSession,
) -> ActionResult:
	"""Set a value in sessionStorage."""
	page = await browser_session.get_current_page()
	try:
		await page.evaluate(
			'(key, value) => { sessionStorage.setItem(key, value); }',
			[params.key, params.value],
		)
		msg = f'🔧 Set sessionStorage[{params.key}] = {params.value}'
		return ActionResult(extracted_content=msg, include_in_memory=True)
	except Exception as e:
		msg = f'Failed to set sessionStorage: {str(e)}'
		return ActionResult(error=msg, include_in_memory=True)


def register_clear_site_data(registry: Registry) -> None:
	"""Register clear_site_data and set_session_storage actions."""

	@registry.action(
		description=(
			'Clear all cookies and session storage for a given domain, then reload the page. '
			'Use this to ensure a clean unauthenticated state before a test '
			'(e.g., sign-out without relying on UI).'
		),
	)
	async def clear_site_data(domain: str, browser_session: BrowserSession) -> ActionResult:
		return await execute_clear_site_data(domain, browser_session)

	@registry.action(
		description='Set a value in sessionStorage for the current page',
		param_model=SetSessionStorageModel,
	)
	async def set_session_storage(
		params: SetSessionStorageModel,
		browser_session: BrowserSession,
	) -> ActionResult:
		return await execute_set_session_storage(params, browser_session)
