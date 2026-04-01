"""
ReplayManager：管理 replay.json 的读写，封装 rerun() 失败处理与断点续跑逻辑。

职责范围（仅 Phase 2 checkout）：
  - replay 模式：存在 replay.json，直接 rerun()；失败时 LLM 断点续跑（heal）并合并。
  - explore 模式：不存在 replay.json，LLM 完整探索，精炼后保存。

Phase 1 (pre-checkout) 由调用方负责，BrowserSession 以参数形式传入。
"""
import logging
import re
import time
from pathlib import Path
from typing import Any

from browser_use import Agent, BrowserProfile, BrowserSession, Tools
from browser_use.agent.views import AgentHistoryList

from test_agent.config import config
from test_agent.replay.history_refiner import refine

logger = logging.getLogger(__name__)


def _load_replay(replay_path: Path, tools: Tools) -> AgentHistoryList | None:
	"""加载 replay.json，返回 AgentHistoryList，文件不存在或损坏返回 None。"""
	if not replay_path.exists():
		return None
	try:
		from browser_use.agent.views import AgentOutput
		action_model = tools.registry.create_action_model()
		output_model = AgentOutput.type_with_custom_actions(action_model)
		history = AgentHistoryList.load_from_file(replay_path, output_model)
		logger.info(f'[ReplayManager] loaded {len(history.history)} steps from {replay_path}')
		return history
	except Exception as e:
		logger.warning(f'[ReplayManager] failed to load {replay_path}: {e}')
		return None


def _save_replay(history: AgentHistoryList, replay_path: Path) -> None:
	"""保存 AgentHistoryList 到 replay.json。"""
	try:
		replay_path.parent.mkdir(parents=True, exist_ok=True)
		history.save_to_file(replay_path)
		logger.info(f'[ReplayManager] saved {len(history.history)} steps to {replay_path}')
	except Exception as e:
		logger.error(f'[ReplayManager] failed to save {replay_path}: {e}')


def _extract_failed_step_index(error_msg: str) -> int | None:
	"""
	从 rerun() 抛出的 RuntimeError 消息中提取失败的 step index。

	rerun() 内部格式：'Step N failed after X attempts: ...'
	"""
	m = re.search(r'Step\s+(\d+)\s+failed', error_msg, re.IGNORECASE)
	if m:
		return int(m.group(1))
	return None


class ReplayManager:
	"""
	管理测试用例的精炼回放生命周期。

	两阶段执行：
	  Phase 1 (pre-checkout): LLM 每次全新执行 pre_checkout_task，抵达 checkout 页面后浏览器 session 保持打开。
	  Phase 2 (checkout):     在同一 session 上，走 replay（存在 replay.json）或 explore（不存在）。

	用法：
		manager = ReplayManager(replay_path, checkout_task, llm, browser_profile, tools)
		success = await manager.run(browser_session)
	"""

	def __init__(
		self,
		replay_path: Path | str,
		checkout_task: str,
		llm: Any,
		browser_profile: BrowserProfile,
		tools: Tools,
		max_steps: int | None = None,
		rerun_max_retries: int | None = None,
		rerun_delay_between_actions: float | None = None,
		rerun_max_step_interval: float | None = None,
	):
		self.replay_path = Path(replay_path)
		self.checkout_task = checkout_task
		self.llm = llm
		self.browser_profile = browser_profile
		self.tools = tools
		self.max_steps = max_steps if max_steps is not None else config.max_steps
		self.rerun_max_retries = rerun_max_retries if rerun_max_retries is not None else config.rerun_max_retries
		self.rerun_delay_between_actions = rerun_delay_between_actions if rerun_delay_between_actions is not None else config.rerun_delay_between_actions
		self.rerun_max_step_interval = rerun_max_step_interval if rerun_max_step_interval is not None else config.rerun_max_step_interval

	def _make_agent(self, browser_session: BrowserSession) -> Agent:
		"""构造 Agent，共享同一 browser_session。"""
		return Agent(
			task=self.checkout_task,
			llm=self.llm,
			browser_profile=self.browser_profile,
			browser_session=browser_session,
			tools=self.tools,
			max_actions_per_step=config.max_actions_per_step,
		)

	async def run(self, browser_session: BrowserSession) -> bool:
		"""
		Phase 2 主入口：在传入的 browser_session 上执行 checkout。

		- replay 模式：存在 replay.json，直接 rerun()；失败时 LLM heal 并合并。
		- explore 模式：不存在 replay.json，LLM 完整探索，精炼后保存。

		Args:
			browser_session: 已启动的浏览器 session（由调用方管理生命周期）

		Returns:
			True 表示测试通过，False 表示失败
		"""
		replay = _load_replay(self.replay_path, self.tools)
		if replay is None:
			logger.info('[ReplayManager] no replay.json → LLM explore checkout')
			return await self._explore_and_refine(save_path=self.replay_path, browser_session=browser_session)
		else:
			logger.info(f'[ReplayManager] replay.json found ({len(replay.history)} steps) → replay checkout')
			return await self._replay_with_healing(replay, browser_session=browser_session)

	# ------------------------------------------------------------------
	# Phase 2 探索模式：LLM 完整跑一遍，然后精炼，存 replay.json
	# ------------------------------------------------------------------

	async def _explore_and_refine(self, save_path: Path, browser_session: BrowserSession) -> bool:
		"""Phase 2 LLM explore checkout_task，精炼后存到 save_path。"""
		logger.info('[ReplayManager] starting LLM explore (checkout)...')

		agent = self._make_agent(browser_session)

		try:
			raw_history = await agent.run(max_steps=self.max_steps)
		except Exception as e:
			logger.error(f'[ReplayManager] LLM explore failed: {e}')
			return False

		if not raw_history or not raw_history.history:
			logger.error('[ReplayManager] LLM explore returned empty history')
			return False

		success = raw_history.is_successful()
		logger.info(f'[ReplayManager] LLM explore done, success={success}, steps={len(raw_history.history)}')

		if not success:
			logger.warning('[ReplayManager] LLM explore did not succeed, not saving replay')
			return False

		# 精炼（跳过 rerun 验证，因为刚跑完，页面状态已变）
		logger.info('[ReplayManager] refining history...')
		refined = await refine(
			raw_history,
			llm=self.llm,
			browser_profile=self.browser_profile,
			tools=self.tools,
			skip_verify=True,  # 首次不验证，下次回放时会验证
		)

		_save_replay(refined, save_path)
		return True

	# ------------------------------------------------------------------
	# 回放模式：直接 rerun()，失败时断点续跑
	# ------------------------------------------------------------------

	async def _replay_with_healing(self, replay: AgentHistoryList, browser_session: BrowserSession) -> bool:
		"""
		执行回放，失败时启动 LLM 断点续跑 + 精炼合并。

		关键：浏览器 session 在两个 Agent 之间共享，不关闭。
		"""
		failed_step_index = await self._try_rerun(replay, browser_session)

		if failed_step_index is None:
			# 回放成功
			logger.info('[ReplayManager] replay succeeded ✅')
			return True

		# 回放失败，LLM 断点续跑
		logger.info(f'[ReplayManager] replay failed at step {failed_step_index}, starting LLM heal...')
		healed = await self._heal(replay, failed_step_index, browser_session)
		return healed

	async def _try_rerun(
		self,
		replay: AgentHistoryList,
		browser_session: BrowserSession,
	) -> int | None:
		"""
		执行 rerun()。

		Returns:
			None 表示成功；int 表示失败的 step index（在 replay.history 中的位置）
		"""
		# rerun_history() 是确定性回放，不调用 LLM，llm 参数仅为 Agent 构造要求
		agent = self._make_agent(browser_session)

		try:
			t0 = time.perf_counter()
			results = await agent.rerun_history(
				replay,
				max_retries=self.rerun_max_retries,
				skip_failures=False,
				delay_between_actions=self.rerun_delay_between_actions,
				max_step_interval=self.rerun_max_step_interval,
			)
			elapsed = time.perf_counter() - t0
			logger.info(f'[ReplayManager] rerun completed in {elapsed:.1f}s ({len(replay.history)} steps, avg {elapsed/len(replay.history):.1f}s/step)')

			# results is a flat list of ActionResult from this rerun execution.
			# The last entry is the AI summary (is_done=True) — strip it before checking errors.
			action_results = [r for r in results if r and not r.is_done]
			error_results = [r for r in action_results if r.error]

			if error_results:
				first_error = error_results[0].error or ''
				logger.warning(f'[ReplayManager] rerun action result has error: {first_error[:150]}')

				# Try to map the error back to a history step index via "Step N failed" message
				step_num = _extract_failed_step_index(first_error)
				if step_num is not None:
					for i, h in enumerate(replay.history):
						if h.metadata and h.metadata.step_number == step_num:
							logger.warning(f'[ReplayManager] mapped to history index {i} → triggering heal')
							return i
					fallback = max(0, step_num - 1)
					logger.warning(f'[ReplayManager] step_num={step_num} not matched, fallback index={fallback} → triggering heal')
					return fallback

				# Cannot parse step number — heal from the first protected action step
				from test_agent.replay.history_refiner import _PROTECTED_ACTION_TYPES, _get_action_type
				for i, history_item in enumerate(replay.history):
					step_dict = history_item.model_dump()
					if _get_action_type(step_dict) in _PROTECTED_ACTION_TYPES:
						logger.warning(f'[ReplayManager] heal from first protected action step {i}')
						return i
				return len(replay.history) - 1

			# No action errors — also sanity-check the AI summary
			done_result = next((r for r in results if r and r.is_done), None)
			if done_result is None or not done_result.success:
				logger.warning(f'[ReplayManager] rerun finished but AI summary reports failure → triggering heal')
				return len(replay.history) - 1

			logger.info('[ReplayManager] all action results clean, AI summary reports success ✅')
			return None  # 成功
		except RuntimeError as e:
			error_msg = str(e)
			logger.warning(f'[ReplayManager] rerun raised RuntimeError: {error_msg[:200]}')

			# 尝试从错误消息提取失败的 step 编号
			step_num = _extract_failed_step_index(error_msg)
			if step_num is not None:
				# step_num 是 metadata.step_number（1-based），转为 history index（0-based）
				for i, h in enumerate(replay.history):
					if h.metadata and h.metadata.step_number == step_num:
						return i
				# 如果找不到精确匹配，返回粗略估计
				return max(0, step_num - 1)
			# 无法解析步骤号，认为是最后一步失败
			return len(replay.history) - 1

		except Exception as e:
			logger.error(f'[ReplayManager] rerun unexpected error: {e}')
			return len(replay.history) - 1

	async def _heal(
		self,
		replay: AgentHistoryList,
		failed_step_index: int,
		browser_session: BrowserSession,
	) -> bool:
		"""
		从失败步骤的当前浏览器状态开始，LLM 续跑完成剩余任务。
		精炼续跑产生的 tail，合并后写回 replay.json。
		"""
		logger.info(f'[ReplayManager] LLM taking over from step {failed_step_index}...')

		# 用共享 browser_session 启动续跑 agent
		# checkout_task 保持原始任务，LLM 会根据当前页面状态自行判断剩余工作
		agent = self._make_agent(browser_session)

		try:
			tail_history = await agent.run(max_steps=self.max_steps)
		except Exception as e:
			logger.error(f'[ReplayManager] LLM heal run failed: {e}')
			return False

		if not tail_history or not tail_history.history:
			logger.error('[ReplayManager] LLM heal returned empty history')
			return False

		tail_success = tail_history.is_successful()
		logger.info(f'[ReplayManager] LLM heal done, success={tail_success}, tail_steps={len(tail_history.history)}')

		if not tail_success:
			logger.warning('[ReplayManager] LLM heal did not succeed')
			return False

		# 精炼 tail（跳过验证，因为浏览器当前状态已是 tail 跑完后的状态）
		logger.info('[ReplayManager] refining tail history...')
		refined_tail = await refine(
			tail_history,
			llm=self.llm,
			browser_profile=self.browser_profile,
			tools=self.tools,
			skip_verify=True,
		)

		# 合并：保留 replay 前 failed_step_index 步 + 精炼后的 tail
		head_steps = replay.history[:failed_step_index]
		if failed_step_index == 0:
			logger.info('[ReplayManager] first step failed, merged replay is tail-only (full replacement)')

		# 去掉 tail 开头与 head 末尾重复的 action type（例如 LLM heal 时重新执行了 logmonitor_init）
		from test_agent.replay.history_refiner import _get_action_type
		tail_steps = list(refined_tail.history)
		if head_steps and tail_steps:
			head_last_type = _get_action_type(head_steps[-1].model_dump())
			tail_first_type = _get_action_type(tail_steps[0].model_dump())
			if head_last_type and head_last_type == tail_first_type:
				logger.info(f'[ReplayManager] dedup: removing tail[0] ({tail_first_type}) — duplicates head[-1]')
				tail_steps = tail_steps[1:]

		merged = AgentHistoryList(history=head_steps + tail_steps)

		logger.info(
			f'[ReplayManager] merged: head={len(head_steps)} + tail={len(refined_tail.history)} = {len(merged.history)} steps'
		)

		# heal 成功本身即验证，直接保存
		_save_replay(merged, self.replay_path)
		logger.info('[ReplayManager] merged replay saved ✅')

		return True
