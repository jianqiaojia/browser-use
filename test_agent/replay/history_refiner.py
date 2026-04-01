"""
HistoryRefiner：把含弯路的 AgentHistoryList 精炼为最短有效路径。

流程：
  1. 规则清洗  — 零成本删除明确无用步骤
  2. LLM 语义精炼 — 1次 LLM 调用，输出可删除的 step index
  3. 单次 rerun() 验证 — 验证精炼后路径可用，失败则退回清洗版
"""
import json
import logging
from pathlib import Path
from typing import Any

from browser_use import Agent, BrowserProfile, Tools
from browser_use.agent.views import AgentHistoryList

logger = logging.getLogger(__name__)

# 绝对不能删除的自定义 action 类型（业务关键，有副作用或状态依赖）
_PROTECTED_ACTION_TYPES = {
	'logmonitor_init',
	'logmonitor_wait_for_state',
	'logmonitor_get_filter_results',
	'uia_wait_for_popup',
	'uia_select_autofill',
}


def _get_action_type(step_dict: dict[str, Any]) -> str | None:
	"""从 history step dict 提取 action type（取第一个 action 的 key）。"""
	actions = (step_dict.get('model_output') or {}).get('action') or []
	if not actions:
		return None
	first = actions[0]
	if isinstance(first, dict):
		keys = [k for k in first if k != 'interacted_element']
		return keys[0] if keys else None
	return None


def _has_error(step_dict: dict[str, Any]) -> bool:
	for r in (step_dict.get('result') or []):
		if r.get('error'):
			return True
	return False


def _is_null_action(step_dict: dict[str, Any]) -> bool:
	"""步骤没有实际 action（纯思考步骤）。"""
	actions = (step_dict.get('model_output') or {}).get('action') or []
	return len(actions) == 0 or actions == [None]


def _interacted_element_stable_hash(step_dict: dict[str, Any], action_idx: int = 0) -> int | None:
	elements = (step_dict.get('state') or {}).get('interacted_element') or []
	if action_idx < len(elements) and elements[action_idx]:
		return elements[action_idx].get('stable_hash')
	return None


def rule_clean(history_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""
	规则清洗：删除明确无用的步骤，不需要 LLM 也不需要验证。

	删除条件：
	  - 纯思考步骤（无 action）
	  - 原本就失败的步骤（result.error 非空）
	  - 连续相同 stable_hash + 相同 action_type（重复点击同一元素）
	  - action_type 为 extract/screenshot 且 interacted_element 全为 None（无副作用观察）
	"""
	cleaned = []
	prev_hash: int | None = None
	prev_action_type: str | None = None

	for step in history_data:
		action_type = _get_action_type(step)

		# 1. 纯思考步骤
		if _is_null_action(step):
			logger.debug(f'[rule_clean] drop null-action step')
			continue

		# 2. 原本就失败的步骤
		if _has_error(step):
			logger.debug(f'[rule_clean] drop failed step: {action_type}')
			continue

		# 3. 连续重复操作同一元素（click 或 input_text）
		curr_hash = _interacted_element_stable_hash(step)
		if (
			curr_hash is not None
			and curr_hash == prev_hash
			and action_type == prev_action_type
			and action_type in ('click', 'input_text')
		):
			logger.debug(f'[rule_clean] drop duplicate {action_type} step (hash={curr_hash})')
			continue

		# 4. 纯观察步骤（extract/screenshot，无元素交互）
		if action_type in ('extract', 'screenshot'):
			elements = (step.get('state') or {}).get('interacted_element') or []
			if all(e is None for e in elements):
				logger.debug(f'[rule_clean] drop no-interaction {action_type} step')
				continue

		cleaned.append(step)
		prev_hash = curr_hash
		prev_action_type = action_type

	logger.info(f'[rule_clean] {len(history_data)} → {len(cleaned)} steps')
	return cleaned


def _build_step_summary(step: dict[str, Any], idx: int) -> dict[str, Any]:
	"""构建单步摘要，用于喂给 LLM 做语义精炼。"""
	action_type = _get_action_type(step)
	model_output = step.get('model_output') or {}
	state = step.get('state') or {}

	# 取第一个 interacted_element
	elements = state.get('interacted_element') or []
	elem = elements[0] if elements else None

	return {
		'step_index': idx,
		'goal': model_output.get('next_goal') or '',
		'action_type': action_type,
		'element_ax_name': (elem or {}).get('ax_name') if elem else None,
		'element_xpath': (elem or {}).get('x_path') if elem else None,
		'url': state.get('url') or '',
		'result_success': not _has_error(step),
		'result_error': next(
			(r.get('error') for r in (step.get('result') or []) if r.get('error')),
			None,
		),
		'is_protected': action_type in _PROTECTED_ACTION_TYPES,
	}


_REFINE_SYSTEM_PROMPT = """\
CRITICAL INSTRUCTION: You MUST output ONLY a single raw JSON object. No markdown, no explanation, no code fences, no Chinese text, no analysis report. ONLY the JSON object itself.

You are a browser automation test engineer. Given a browser action history on the checkout page (JSON), your job is to find steps that can be safely removed to produce the shortest correct path that still fully accomplishes the task.

HARD CONSTRAINTS — never delete:
1. Steps where is_protected=true
2. Steps where result_success=false
3. The last step

CANDIDATES for deletion:
- Scroll steps not required by subsequent steps
- Repeated open/close of the same dropdown
- Dead-end exploration steps (navigated away and came back)
- Observation-only steps (screenshot/extract with no side effects)
- Steps that pursue a sub-goal already satisfied earlier (keep the first success, delete the redundant repeat)

OUTPUT FORMAT — raw JSON only, nothing else:
{"can_delete": [2, 5, 7], "reasons": {"2": "reason", "5": "reason", "7": "reason"}}

If nothing to delete: {"can_delete": [], "reasons": {}}
"""


async def llm_refine(
	cleaned_steps: list[dict[str, Any]],
	llm: Any,
) -> list[int]:
	"""
	用 LLM 分析清洗后的 history，返回可以删除的 step index 列表。

	返回的 index 是在 cleaned_steps 中的位置（0-based）。
	"""
	if len(cleaned_steps) <= 3:
		# 步骤太少，不值得精炼
		return []

	summaries = [_build_step_summary(step, i) for i, step in enumerate(cleaned_steps)]

	# 标注 URL 变化信息（方便 LLM 判断）
	for i in range(1, len(summaries)):
		prev_url = summaries[i - 1]['url']
		curr_url = summaries[i]['url']
		summaries[i]['url_changed_from_prev'] = (prev_url != curr_url and bool(prev_url))

	user_msg = f"Action history ({len(summaries)} steps):\n{json.dumps(summaries, ensure_ascii=False, indent=2)}\n\nRemember: output ONLY the JSON object, nothing else."

	logger.info(f'[llm_refine] calling LLM to refine {len(cleaned_steps)} steps...')

	try:
		from browser_use.llm import SystemMessage, UserMessage
		completion = await llm.ainvoke([
			SystemMessage(content=_REFINE_SYSTEM_PROMPT),
			UserMessage(content=user_msg),
		])
		raw = completion.completion.strip()
		logger.debug(f'[llm_refine] raw response: {raw[:300]}')

		# 提取 JSON（忽略 markdown 包装和前后多余文字）
		start = raw.find('{')
		end = raw.rfind('}') + 1
		if start == -1 or end == 0:
			logger.warning(f'[llm_refine] LLM returned no valid JSON, skipping refinement. raw={raw[:200]!r}')
			return []

		result = json.loads(raw[start:end])
		can_delete: list[int] = result.get('can_delete') or []

		# 安全校验：确保 LLM 没有违反硬性约束
		safe_to_delete = []
		for idx in can_delete:
			if not (0 <= idx < len(cleaned_steps)):
				continue
			step = cleaned_steps[idx]
			action_type = _get_action_type(step)
			if action_type in _PROTECTED_ACTION_TYPES:
				logger.warning(f'[llm_refine] LLM tried to delete protected step {idx} ({action_type}), ignoring')
				continue
			if idx == 0 or idx == len(cleaned_steps) - 1:
				logger.warning(f'[llm_refine] LLM tried to delete first/last step {idx}, ignoring')
				continue
			safe_to_delete.append(idx)

		reasons = result.get('reasons') or {}
		for idx in safe_to_delete:
			logger.info(f'[llm_refine] will delete step {idx}: {reasons.get(str(idx), "?")}')

		return safe_to_delete

	except Exception as e:
		logger.warning(f'[llm_refine] failed: {e}, skipping LLM refinement')
		return []


async def verify_with_rerun(
	refined_history: AgentHistoryList,
	llm: Any,
	browser_profile: BrowserProfile,
	tools: Tools,
) -> bool:
	"""
	用精炼后的 history 跑一次 Agent.rerun() 验证。

	Returns:
		True 如果回放成功，False 否则
	"""
	logger.info(f'[verify] running rerun() with {len(refined_history.history)} steps...')
	try:
		agent = Agent(
			task='verify',
			llm=llm,
			browser_profile=browser_profile,
			tools=tools,
		)
		results = await agent.rerun_history(
			refined_history,
			max_retries=2,
			skip_failures=False,
		)
		# 检查是否有致命错误
		errors = [r.error for r in results if r and r.error]
		if errors:
			logger.warning(f'[verify] rerun had errors: {errors[:3]}')
			return False
		logger.info('[verify] rerun succeeded ✅')
		return True
	except Exception as e:
		logger.warning(f'[verify] rerun failed: {e}')
		return False


async def refine(
	history: AgentHistoryList,
	llm: Any,
	browser_profile: BrowserProfile,
	tools: Tools,
	skip_verify: bool = False,
) -> AgentHistoryList:
	"""
	主入口：对 AgentHistoryList 做完整精炼流程。

	Args:
		history: LLM 探索产生的原始 AgentHistoryList
		llm: LLM 实例（用于语义精炼）
		browser_profile: 浏览器配置（用于 rerun 验证）
		tools: 已注册自定义 actions 的 Tools 实例
		skip_verify: True 时跳过 rerun 验证（调试用）

	Returns:
		精炼后的 AgentHistoryList（步骤最少、功能正确）
	"""
	raw_data: list[dict[str, Any]] = history.model_dump()['history']
	original_count = len(raw_data)

	# Step 1: 规则清洗
	cleaned_data = rule_clean(raw_data)

	# Step 2: LLM 语义精炼
	indices_to_delete = await llm_refine(cleaned_data, llm)

	if indices_to_delete:
		refined_data = [s for i, s in enumerate(cleaned_data) if i not in set(indices_to_delete)]
		logger.info(f'[refine] LLM deleted {len(indices_to_delete)} steps: {len(cleaned_data)} → {len(refined_data)}')
	else:
		refined_data = cleaned_data
		logger.info('[refine] LLM found nothing to delete, using rule-cleaned result')

	# 反序列化回 AgentHistoryList
	refined_history = _deserialize_history(refined_data, history)

	# Step 3: 单次 rerun() 验证
	if skip_verify:
		logger.info('[refine] skipping verify (skip_verify=True)')
		final_history = refined_history
	else:
		ok = await verify_with_rerun(refined_history, llm, browser_profile, tools)
		if ok:
			final_history = refined_history
		else:
			# 兜底：退回规则清洗版（跳过 LLM 精炼，但保留规则清洗）
			logger.warning('[refine] refined version failed verify, falling back to rule-cleaned version')
			cleaned_history = _deserialize_history(cleaned_data, history)
			final_history = cleaned_history

	final_count = len(final_history.history)
	logger.info(
		f'[refine] done: {original_count} → {final_count} steps '
		f'(removed {original_count - final_count})'
	)
	return final_history


def _deserialize_history(
	steps_data: list[dict[str, Any]],
	original: AgentHistoryList,
) -> AgentHistoryList:
	"""
	把 steps_data（model_dump 格式）还原为 AgentHistoryList。

	直接从 original 里按步骤内容匹配，避免复杂的反序列化逻辑。
	匹配依据：step_number（metadata）或在 original.history 中的位置。
	"""
	# 建立 original step_number → AgentHistory 的映射
	original_by_step: dict[int, Any] = {}
	for i, h in enumerate(original.history):
		key = (h.metadata.step_number if h.metadata else i)
		original_by_step[key] = h

	selected = []
	for step_dict in steps_data:
		step_num = (step_dict.get('metadata') or {}).get('step_number')
		if step_num is not None and step_num in original_by_step:
			selected.append(original_by_step[step_num])
		else:
			# fallback：按 goal 文字匹配
			goal = (step_dict.get('model_output') or {}).get('next_goal') or ''
			matched = next(
				(h for h in original.history
				 if h.model_output and h.model_output.next_goal == goal),
				None,
			)
			if matched:
				selected.append(matched)
			else:
				logger.warning(f'[deserialize] could not match step (goal={goal[:50]}), skipping')

	return AgentHistoryList(history=selected)
