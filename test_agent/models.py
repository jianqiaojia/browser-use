"""Data models for Test Agent."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class ReplayMode(str, Enum):
	"""Execution mode for a test case.

	precheckout_llm__checkout_replay   - Phase 1 LLM 导航 + Phase 2 rerun（默认）
	precheckout_skip__checkout_replay  - 跳过 Phase 1，直接从 checkout 页面 rerun（cookie 保持登录态）
	fully_llm                          - Phase 1 + Phase 2 全 LLM，不 refine，作为兜底
	"""
	PRECHECKOUT_LLM__CHECKOUT_REPLAY = 'precheckout_llm__checkout_replay'
	PRECHECKOUT_SKIP__CHECKOUT_REPLAY = 'precheckout_skip__checkout_replay'
	FULLY_LLM = 'fully_llm'


class TestCase(BaseModel):
	"""单个测试用例。

	pre_checkout_instructions:  Phase 1 硬性约束（登录状态、cart 准备等）。进入 pre-checkout task prompt。
	pre_checkout_guidance:      Phase 1 UI 操作参考建议。进入 pre-checkout task prompt。
	checkout_instructions:      Phase 2 硬性约束（autofill 验证目标等）。进入 checkout task prompt。
	checkout_guidance:          Phase 2 UI 操作参考建议。进入 checkout task prompt。
	profile:                    覆盖默认 Edge profile 目录（e.g. "Profile 3"）。None 表示使用 config 默认值。
	replay_mode:                执行模式，默认 precheckout_llm__checkout_replay。
	"""
	name: str
	pre_checkout_instructions: Optional[str | list[str]] = None
	pre_checkout_guidance: Optional[str | list[str]] = None
	checkout_instructions: Optional[str | list[str]] = None
	checkout_guidance: Optional[str | list[str]] = None
	profile: Optional[str] = None
	replay_mode: ReplayMode = ReplayMode.PRECHECKOUT_LLM__CHECKOUT_REPLAY


class SiteTest(BaseModel):
	"""单个 site 的测试集合。

	domain:                     测试目标站点的 URL（e.g. https://www.nike.com）。
	site_pre_checkout_guidance: 适用于该 site 所有 test case 的 Phase 1 共享 UI 操作参考。
	site_checkout_guidance:     适用于该 site 所有 test case 的 Phase 2 共享 UI 操作参考。
	"""
	domain: Optional[str] = None
	site_pre_checkout_guidance: Optional[str | list[str]] = None
	site_checkout_guidance: Optional[str | list[str]] = None
	test_cases: list[TestCase] = []
