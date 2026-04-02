"""
ReplayManager：管理单个测试用例的完整执行（pre-checkout + checkout replay/explore）。

执行策略由 ReplayMode 决定：
  precheckout_skip__checkout_replay  : 跳过 pre-checkout，直接从 checkout 页面 rerun()
  precheckout_llm__checkout_replay   : pre-checkout LLM + checkout rerun()
  fully_llm                          : Phase 1 + Phase 2 全 LLM，不 refine，作为兜底
  auto                               : 有 replay.json 就 rerun，没有就 explore
"""
import logging
import re
import time
from pathlib import Path
from typing import Any

from browser_use import Agent, BrowserProfile, BrowserSession, Tools
from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, StepMetadata
from browser_use.browser.views import BrowserStateHistory, TabInfo

from test_agent.config import config
from test_agent.models import ReplayMode
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


def _prepend_navigate_step(history: AgentHistoryList, url: str, tools: Tools) -> AgentHistoryList:
	"""
	Prepend a synthetic navigate step to history so rerun() can start from a blank page.

	When explore records from an already-loaded checkout page, no goto/navigate step exists.
	On precheckout_skip rerun the browser starts blank, so we inject this step at index 0.
	"""
	import time as _time
	from browser_use.agent.views import AgentOutput

	action_model = tools.registry.create_action_model()
	output_model = AgentOutput.type_with_custom_actions(action_model)

	# Construct the action as a dict and validate through the dynamic ActionModel union
	navigate_action = action_model.model_validate({'navigate': {'url': url, 'new_tab': False}})

	now = _time.time()
	navigate_output = output_model(
		evaluation_previous_goal='',
		memory='',
		next_goal=f'Navigate to checkout page: {url}',
		action=[navigate_action],
	)
	navigate_step = AgentHistory(
		model_output=navigate_output,
		result=[ActionResult(extracted_content=f'Navigated to {url}')],
		state=BrowserStateHistory(url=url, title='', tabs=[], interacted_element=[None]),
		metadata=StepMetadata(step_start_time=now, step_end_time=now, step_number=0, step_interval=0.0),
	)
	logger.info(f'[ReplayManager] prepended navigate step → {url}')
	return AgentHistoryList(history=[navigate_step] + history.history)


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
	管理单个测试用例的完整执行：pre-checkout（按需）+ checkout replay/explore。

	执行策略：
	  precheckout_llm__checkout_replay   : pre-checkout LLM + checkout rerun()（默认）
	  precheckout_skip__checkout_replay  : 跳过 pre-checkout，直接从 checkout 页面 rerun()
	  fully_llm                          : Phase 1 + Phase 2 全 LLM，不 refine，作为兜底

	用法：
		manager = ReplayManager(pre_checkout_task, checkout_task, replay_path, llm, browser_profile, tools, replay_mode)
		success = await manager.run(browser_session)
	"""

	def __init__(
		self,
		pre_checkout_task: str,
		checkout_task: str,
		replay_path: Path | str,
		llm: Any,
		browser_profile: BrowserProfile,
		tools: Tools,
		replay_mode: ReplayMode = ReplayMode.PRECHECKOUT_LLM__CHECKOUT_REPLAY,
		max_steps: int | None = None,
		rerun_max_retries: int | None = None,
		rerun_delay_between_actions: float | None = None,
		rerun_max_step_interval: float | None = None,
	):
		self.pre_checkout_task = pre_checkout_task
		self.checkout_task = checkout_task
		self.replay_path = Path(replay_path)
		self.llm = llm
		self.browser_profile = browser_profile
		self.tools = tools
		self.replay_mode = replay_mode
		self.max_steps = max_steps if max_steps is not None else config.max_steps
		self.rerun_max_retries = rerun_max_retries if rerun_max_retries is not None else config.rerun_max_retries
		self.rerun_delay_between_actions = rerun_delay_between_actions if rerun_delay_between_actions is not None else config.rerun_delay_between_actions
		self.rerun_max_step_interval = rerun_max_step_interval if rerun_max_step_interval is not None else config.rerun_max_step_interval

	async def _run_rerun_with_heal(
		self,
		replay: AgentHistoryList,
		browser_session: BrowserSession,
	) -> bool:
		"""Execute rerun; heal on failure."""
		failed_step_index = await self._try_rerun(replay, browser_session)
		if failed_step_index is None:
			return True
		logger.info(f'[ReplayManager] replay failed at step {failed_step_index}, healing...')
		return await self._heal(replay, failed_step_index, browser_session)

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

	def _should_run_pre_checkout(self) -> bool:
		"""
		Returns True if pre-checkout LLM should run before checkout.

		No replay.json → always True (browser starts blank, needs LLM to navigate first).
		PRECHECKOUT_SKIP → False (session already at checkout page via cookie).
		PRECHECKOUT_LLM / FULLY_LLM → True.
		"""
		if not self.replay_path.exists():
			return True
		if self.replay_mode == ReplayMode.PRECHECKOUT_SKIP__CHECKOUT_REPLAY:
			return False
		return True

	async def run(self, browser_session: BrowserSession) -> bool:
		"""
		执行完整测试：pre-checkout（按需，见 _should_run_pre_checkout）+ checkout replay/explore。

		Args:
			browser_session: 已启动的浏览器 session（由调用方管理生命周期）

		Returns:
			True 表示测试通过，False 表示失败
		"""
		run_pre_checkout = self._should_run_pre_checkout()

		print(f"[ReplayManager] mode={self.replay_mode.value} → {'running pre-checkout' if run_pre_checkout else 'skipping pre-checkout'}")

		if run_pre_checkout:
			t0 = time.perf_counter()
			print("[ReplayManager] [pre-checkout] starting...")
			pre_checkout_agent = Agent(
				task=self.pre_checkout_task,
				llm=self.llm,
				browser_profile=self.browser_profile,
				browser_session=browser_session,
				tools=self.tools,
				max_actions_per_step=config.max_actions_per_step,
			)
			pre_checkout_history = await pre_checkout_agent.run(max_steps=self.max_steps)
			if not pre_checkout_history or not pre_checkout_history.is_successful():
				print("[ReplayManager] [pre-checkout] ❌ failed")
				return False
			print(f"[ReplayManager] [pre-checkout] ✅ done ({len(pre_checkout_history.history)} steps, {time.perf_counter()-t0:.1f}s)")

		phase_label = 'checkout' if run_pre_checkout else 'checkout (direct)'
		print(f"[ReplayManager] [checkout] {self.replay_path.name} ({phase_label})")
		return await self._run_phase2(browser_session)

	async def _run_phase2(self, browser_session: BrowserSession) -> bool:
		"""Checkout 主逻辑：根据 replay_mode 决定 rerun / explore。"""
		# FULLY_LLM: 全 LLM 兜底，不 refine，不保存 replay
		if self.replay_mode == ReplayMode.FULLY_LLM:
			logger.info('[ReplayManager] mode=fully_llm → LLM checkout (no refine)')
			agent = self._make_agent(browser_session)
			try:
				history = await agent.run(max_steps=self.max_steps)
			except Exception as e:
				logger.error(f'[ReplayManager] fully_llm run failed: {e}')
				return False
			return bool(history and history.is_successful())

		# PRECHECKOUT_LLM / PRECHECKOUT_SKIP: rerun，无 replay.json 则 explore 并录制
		replay = _load_replay(self.replay_path, self.tools)
		if replay is None:
			logger.warning(f'[ReplayManager] {self.replay_mode.value} but no replay.json — falling back to LLM explore')
			return await self._explore_and_refine(save_path=self.replay_path, browser_session=browser_session)
		logger.info(f'[ReplayManager] {self.replay_mode.value} → rerun ({len(replay.history)} steps)')
		return await self._run_rerun_with_heal(replay, browser_session)

	# ------------------------------------------------------------------
	# checkout 探索模式：LLM 完整跑一遍，然后精炼，存 replay.json
	# ------------------------------------------------------------------

	async def _explore_and_refine(self, save_path: Path, browser_session: BrowserSession) -> bool:
		"""checkout LLM explore，精炼后存到 save_path。"""
		logger.info('[ReplayManager] starting LLM explore (checkout)...')

		# Capture checkout URL before agent runs so we can prepend a navigate step to replay.json.
		# This is critical for precheckout_skip mode: rerun starts from a blank page and needs
		# the navigate action to reach the checkout URL before replaying the remaining steps.
		checkout_url: str | None = None
		try:
			checkout_url = await browser_session.get_current_page_url()
			logger.info(f'[ReplayManager] captured checkout URL: {checkout_url}')
		except Exception as e:
			logger.warning(f'[ReplayManager] failed to capture checkout URL: {e}')

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

		# Prepend navigate step so rerun can start from blank page (precheckout_skip mode)
		if checkout_url and checkout_url not in ('about:blank', 'chrome://newtab/', ''):
			refined = _prepend_navigate_step(refined, checkout_url, self.tools)

		_save_replay(refined, save_path)
		return True

	# ------------------------------------------------------------------
	# 回放模式：直接 rerun()，失败时断点续跑
	# ------------------------------------------------------------------

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
