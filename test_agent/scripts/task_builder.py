"""
Task builder：从 preambles.json 模板 + 测试用例数据构建 Phase 1 / Phase 2 task 字符串。
"""
import re
from pathlib import Path

from test_agent.models import TestCase


def load_preambles() -> tuple[str | None, str | None]:
	"""Load pre_checkout and checkout preamble templates from preambles.py."""
	import importlib.util
	path = Path(__file__).parent.parent / "test_case" / "preambles.py"
	if not path.exists():
		return None, None
	spec = importlib.util.spec_from_file_location("preambles", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return getattr(module, "pre_checkout", None), getattr(module, "checkout", None)


def _fill_preamble(
	preamble: str,
	domain: str | None,
	instructions: str | list[str] | None,
	site_guidance: str | list[str] | None,
	test_guidance: str | list[str] | None,
) -> str:
	"""Fill placeholders in a preamble template, omitting empty sections entirely."""
	text = preamble

	text = text.replace("{--Domain--}", domain or "")

	if instructions:
		lines = instructions if isinstance(instructions, list) else [instructions]
		inst_text = "\n".join(f"- {l}" for l in lines)
		text = text.replace("{--Instructions--}", inst_text)
	else:
		# Remove placeholder and the '# Instructions' header block above it
		text = re.sub(r'# Instructions\nInstructions below are hard constraints[^\n]*\n\{--Instructions--\}', '', text)
		text = text.replace("{--Instructions--}", "")

	sg_lines: list[str] = site_guidance if isinstance(site_guidance, list) else ([site_guidance] if site_guidance else [])
	tg_lines: list[str] = test_guidance if isinstance(test_guidance, list) else ([test_guidance] if test_guidance else [])
	all_lines = sg_lines + tg_lines
	if all_lines:
		guidance_text = "\n".join(f"- {l}" for l in all_lines)
		text = text.replace("{--Guidance--}", f"# Guidance\nGuidance is advisory — use your judgment based on what you actually see in the browser.\n{guidance_text}")
	else:
		text = text.replace("{--Guidance--}", "")

	# Collapse consecutive blank lines left by removed sections
	text = re.sub(r'\n{3,}', '\n\n', text).strip()

	return text


def build_pre_checkout_task(
	test: TestCase,
	preamble: str | None,
	site_pre_checkout_guidance: str | list[str] | None,
	domain: str | None = None,
) -> str:
	"""Build the Phase 1 task: reach a valid checkout state."""
	if not preamble:
		return ""
	return _fill_preamble(
		preamble,
		domain=domain,
		instructions=test.pre_checkout_instructions,
		site_guidance=site_pre_checkout_guidance,
		test_guidance=test.pre_checkout_guidance,
	)


def build_checkout_task(
	test: TestCase,
	preamble: str | None,
	site_checkout_guidance: str | list[str] | None,
	domain: str | None = None,
) -> str:
	"""Build the Phase 2 task: trigger EC autofill and verify."""
	if not preamble:
		return ""
	return _fill_preamble(
		preamble,
		domain=domain,
		instructions=test.checkout_instructions,
		site_guidance=site_checkout_guidance,
		test_guidance=test.checkout_guidance,
	)
