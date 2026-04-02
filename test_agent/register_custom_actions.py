"""Custom actions registration — thin coordinator that delegates to per-action modules."""
import os
import sys

from browser_use import Tools

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_agent.actions.os_click import register_os_click
from test_agent.actions.cdp_click import register_cdp_click
from test_agent.actions.clear_site_data import register_clear_site_data
from test_agent.actions.uia_autofill import register_uia_autofill
from test_agent.actions.log_monitor import register_log_monitor
from test_agent.actions.email_verification import register_email_verification


def register_custom_actions(tools: Tools) -> None:
	"""Register all custom actions for test automation."""
	# register_os_click(tools.registry)
	register_cdp_click(tools.registry)
	register_clear_site_data(tools.registry)
	register_uia_autofill(tools.registry)
	register_log_monitor(tools.registry)
	register_email_verification(tools.registry)
