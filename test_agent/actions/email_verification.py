"""
Email Verification Actions — baseline recording and verification code retrieval via Outlook COM.

email_mark_baseline must be called BEFORE triggering any login flow that sends a verification
email. get_email_verification_code reads only emails that arrive after that point.
"""

from pydantic import BaseModel
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.agent.views import ActionResult

from test_agent.scripts.email_helper import async_get_baseline_entry_id, async_get_verification_code


class GetEmailVerificationCodeModel(BaseModel):
	sender_filter: str = 'nike'
	subject_filter: str = ''
	timeout_seconds: int = 60


def register_email_verification(registry: Registry) -> None:
	"""Register email_mark_baseline and get_email_verification_code actions."""

	@registry.action(
		description=(
			'Mark email baseline — call this BEFORE triggering any login flow that may send a '
			'verification email. Records the current newest email EntryID so that '
			'get_email_verification_code only returns codes from emails that arrive after this point.'
		),
	)
	async def email_mark_baseline(browser_session: BrowserSession) -> ActionResult:
		"""Record current inbox head so we can ignore pre-existing emails."""
		print('📧 Marking email baseline (recording current inbox head)...')
		try:
			entry_id = await async_get_baseline_entry_id()
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

	@registry.action(
		description=(
			'Get email verification code from Outlook inbox — polls for a new email that arrived '
			'AFTER email_mark_baseline was called, and extracts the numeric verification code.'
		),
		param_model=GetEmailVerificationCodeModel,
	)
	async def get_email_verification_code(
		params: GetEmailVerificationCodeModel,
		browser_session: BrowserSession,
	) -> ActionResult:
		"""Poll Outlook inbox for a verification code email newer than the baseline."""
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
