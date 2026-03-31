"""
ReplayManager：管理 replay.json 的读写，封装 rerun() 失败处理与断点续跑逻辑。

核心设计：
  - replay.json 存储精炼后的 AgentHistoryList（browser-use 原生格式）
  - rerun() 失败时浏览器保持打开，LLM 从当前页面状态续跑
  - 续跑产生的 tail history 经 HistoryRefiner 精炼后合并回 replay.json
"""
import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

from browser_use import Agent, BrowserProfile, BrowserSession, Tools
from browser_use.agent.views import AgentHistory, AgentHistoryList, ActionResult

from test_agent.config import config
from test_agent.replay.history_refiner import refine, _PROTECTED_ACTION_TYPES, _get_action_type

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

	用法：
		manager = ReplayManager(replay_path, task, llm, browser_profile, tools)
		success = await manager.run()
	"""

	def __init__(
		self,
		replay_path: Path | str,
		task: str,
		llm: Any,
		browser_profile: BrowserProfile,
		tools: Tools,
		max_steps: int | None = None,
		rerun_max_retries: int | None = None,
		rerun_delay_between_actions: float | None = None,
		rerun_max_step_interval: float | None = None,
	):
		self.replay_path = Path(replay_path)
		self.task = task
		self.llm = llm
		self.browser_profile = browser_profile
		self.tools = tools
		self.max_steps = max_steps if max_steps is not None else config.max_steps
		self.rerun_max_retries = rerun_max_retries if rerun_max_retries is not None else config.rerun_max_retries
		self.rerun_delay_between_actions = rerun_delay_between_actions if rerun_delay_between_actions is not None else config.rerun_delay_between_actions
		self.rerun_max_step_interval = rerun_max_step_interval if rerun_max_step_interval is not None else config.rerun_max_step_interval

	async def run(self) -> bool:
		"""
		主入口：根据 replay.json 是否存在，走探索模式或回放模式。

		Returns:
			True 表示测试通过，False 表示失败
		"""
		replay = _load_replay(self.replay_path, self.tools)

		if replay is None:
			logger.info('[ReplayManager] no replay.json → entering LLM explore mode')
			result = await self._explore_and_refine(save_path=self.replay_path)
		else:
			logger.info(f'[ReplayManager] replay.json found ({len(replay.history)} steps) → entering replay mode')
			result = await self._replay_with_healing(replay)

		return result

	async def explore(self, dry_run: bool = False) -> bool:
		"""
		强制探索模式：LLM 跑完后精炼。

		Args:
			dry_run: True → 只跑 LLM，不精炼，不存文件（验证 task 描述是否合理）；
			         False → LLM 跑完后精炼，直接覆盖 replay.json
		"""
		if dry_run:
			logger.info('[ReplayManager] explore mode → dry run, skip refine, result will NOT be saved')
		else:
			logger.info(f'[ReplayManager] explore-and-refine mode → will refine and overwrite {self.replay_path.name}')
		save_path = None if dry_run else self.replay_path
		return await self._explore_and_refine(save_path=save_path, dry_run=dry_run)

	# ------------------------------------------------------------------
	# 探索模式：LLM 完整跑一遍，然后精炼，存 replay.json
	# ------------------------------------------------------------------

	async def _explore_and_refine(self, save_path: Path | None, dry_run: bool = False) -> bool:
		"""LLM 完整探索，精炼后存到 save_path。dry_run=True 时跳过精炼，不存文件。"""
		logger.info('[ReplayManager] starting LLM explore...')

		agent = Agent(
			task=self.task,
			llm=self.llm,
			browser_profile=self.browser_profile,
			tools=self.tools,
			max_actions_per_step=config.max_actions_per_step,
		)

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

		if dry_run:
			logger.info('[ReplayManager] explore dry-run complete, skipping refine, result not saved')
			return True

		# 精炼（跳过 rerun 验证，因为刚跑完，页面状态已变）
		logger.info('[ReplayManager] refining history...')
		refined = await refine(
			raw_history,
			task=self.task,
			llm=self.llm,
			browser_profile=self.browser_profile,
			tools=self.tools,
			skip_verify=True,  # 首次不验证，下次回放时会验证
		)

		assert save_path is not None
		_save_replay(refined, save_path)
		return True

	# ------------------------------------------------------------------
	# 回放模式：直接 rerun()，失败时断点续跑
	# ------------------------------------------------------------------

	async def _replay_with_healing(self, replay: AgentHistoryList) -> bool:
		"""
		执行回放，失败时启动 LLM 断点续跑 + 精炼合并。

		关键：浏览器 session 在两个 Agent 之间共享，不关闭。
		"""
		# 创建共享的 BrowserSession，keep_alive=True 防止 rerun 失败时 session 被 reset
		# heal agent 需要看到失败那一刻的真实页面状态
		heal_profile = self.browser_profile.model_copy(update={'keep_alive': True})
		browser_session = BrowserSession(browser_profile=heal_profile)
		await browser_session.start()

		try:
			failed_step_index = await self._try_rerun(replay, browser_session)

			if failed_step_index is None:
				# 回放成功
				logger.info('[ReplayManager] replay succeeded ✅')
				return True

			# 回放失败，LLM 断点续跑
			logger.info(f'[ReplayManager] replay failed at step {failed_step_index}, starting LLM heal...')
			healed = await self._heal(replay, failed_step_index, browser_session)
			return healed

		finally:
			try:
				await browser_session.stop()
			except Exception:
				pass

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
		agent = Agent(
			task=self.task,
			llm=self.llm,
			browser_profile=self.browser_profile,
			browser_session=browser_session,
			tools=self.tools,
		)

		try:
			t0 = time.perf_counter()
			await agent.rerun_history(
				replay,
				max_retries=self.rerun_max_retries,
				skip_failures=False,
				delay_between_actions=self.rerun_delay_between_actions,
				max_step_interval=self.rerun_max_step_interval,
			)
			elapsed = time.perf_counter() - t0
			logger.info(f'[ReplayManager] rerun completed in {elapsed:.1f}s ({len(replay.history)} steps, avg {elapsed/len(replay.history):.1f}s/step)')
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
		# task 保持原始任务，LLM 会根据当前页面状态自行判断剩余工作
		agent = Agent(
			task=self.task,
			llm=self.llm,
			browser_profile=self.browser_profile,
			browser_session=browser_session,
			tools=self.tools,
		)

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
			task=self.task,
			llm=self.llm,
			browser_profile=self.browser_profile,
			tools=self.tools,
			skip_verify=True,
		)

		# 合并：保留 replay 前 failed_step_index 步 + 精炼后的 tail
		head_steps = replay.history[:failed_step_index]

		# 去重：tail 开头若与 head 末尾 action_type 相同（且是有状态 action），跳过
		head_action_types = {
			_get_action_type(h.model_dump())
			for h in head_steps
		}
		tail_steps = refined_tail.history
		deduped_tail = []
		for h in tail_steps:
			at = _get_action_type(h.model_dump())
			if at in _PROTECTED_ACTION_TYPES and at in head_action_types:
				logger.info(f'[ReplayManager] dedup: skipping tail step "{at}" already in head')
				continue
			deduped_tail.append(h)
			# 一旦遇到非重复步骤，后续不再去重（只去头部重复）
			head_action_types.discard(at)
		merged = AgentHistoryList(history=head_steps + deduped_tail)

		logger.info(
			f'[ReplayManager] merged: head={len(head_steps)} + tail={len(deduped_tail)} '
			f'(refined={len(refined_tail.history)}) = {len(merged.history)} steps'
		)

		# heal 成功本身即验证，直接保存
		_save_replay(merged, self.replay_path)
		logger.info('[ReplayManager] merged replay saved ✅')

		return True
