"""Tier state machine for adaptive replay execution."""
import logging
from pathlib import Path
from pydantic import BaseModel

logger = logging.getLogger(__name__)

TIER_PRECHECKOUT_SKIP__CHECKOUT_REPLAY = 1     # Full replay (zero LLM)                ~5-10s
TIER_PRECHECKOUT_LLM__CHECKOUT_REPLAY = 2      # Phase 1 LLM + Phase 2 replay          ~120s
TIER_PRECHECKOUT_LLM__CHECKOUT_LLM = 3         # Phase 1 LLM + Phase 2 LLM explore     ~200s

TIER_DOWNGRADE_FAILURES = 3    # K: consecutive early-step failures to trigger downgrade
TIER_DOWNGRADE_EARLY_STEPS = 3  # M: failure in step index < M counts as "early-step"
TIER_UPGRADE_SUCCESSES = 5      # N: consecutive successes before attempting upgrade


class TierState(BaseModel):
	"""
	Persistent tier state for a single test case.
	Serialised to {name}.tier_state.json alongside replay.json.

	current_tier:          active execution tier (1/2/3)
	consecutive_failures:  how many runs in a row had early-step failures
	consecutive_successes: how many runs in a row succeeded (for upgrade logic)
	"""
	current_tier: int = TIER_PRECHECKOUT_LLM__CHECKOUT_REPLAY  # Default: two-phase (safe starting point)
	consecutive_failures: int = 0
	consecutive_successes: int = 0

	@classmethod
	def load(cls, path: Path) -> 'TierState':
		"""Load from file; return default state if missing or corrupt."""
		if path.exists():
			try:
				return cls.model_validate_json(path.read_text(encoding='utf-8'))
			except Exception as e:
				logger.warning(f'[TierState] failed to load {path}: {e} — using defaults')
		return cls()

	def save(self, path: Path) -> None:
		"""Persist to file."""
		try:
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(self.model_dump_json(indent=2), encoding='utf-8')
		except Exception as e:
			logger.error(f'[TierState] failed to save {path}: {e}')

	def record_success(self, path: Path) -> None:
		"""Record a successful run and potentially upgrade tier."""
		self.consecutive_failures = 0
		self.consecutive_successes += 1
		if self.current_tier == TIER_PRECHECKOUT_LLM__CHECKOUT_LLM:
			logger.info('[TierState] Tier 3 explore succeeded → upgrading to Tier 2')
			self.current_tier = TIER_PRECHECKOUT_LLM__CHECKOUT_REPLAY
			self.consecutive_successes = 0
		elif self.current_tier == TIER_PRECHECKOUT_LLM__CHECKOUT_REPLAY and self.consecutive_successes >= TIER_UPGRADE_SUCCESSES:
			logger.info(f'[TierState] {TIER_UPGRADE_SUCCESSES} consecutive successes → upgrading to Tier 1')
			self.current_tier = TIER_PRECHECKOUT_SKIP__CHECKOUT_REPLAY
			self.consecutive_successes = 0
		self.save(path)

	def record_failure(self, path: Path, early_step: bool = False) -> None:
		"""
		Record a failure.

		early_step=True:  failure in first M steps — indicates unstable checkout start state.
		                  Increments consecutive_failures and may trigger tier downgrade.
		early_step=False: mid/late failure — goes to heal logic, does NOT trigger downgrade.
		"""
		self.consecutive_successes = 0
		if early_step:
			self.consecutive_failures += 1
			if self.current_tier == TIER_PRECHECKOUT_SKIP__CHECKOUT_REPLAY and self.consecutive_failures >= TIER_DOWNGRADE_FAILURES:
				logger.info(f'[TierState] {TIER_DOWNGRADE_FAILURES} early-step failures → downgrading Tier 1 → Tier 2')
				self.current_tier = TIER_PRECHECKOUT_LLM__CHECKOUT_REPLAY
				self.consecutive_failures = 0
			elif self.current_tier == TIER_PRECHECKOUT_LLM__CHECKOUT_REPLAY and self.consecutive_failures >= TIER_DOWNGRADE_FAILURES:
				logger.info(f'[TierState] {TIER_DOWNGRADE_FAILURES} early-step failures → downgrading Tier 2 → Tier 3')
				self.current_tier = TIER_PRECHECKOUT_LLM__CHECKOUT_LLM
				self.consecutive_failures = 0
		else:
			self.consecutive_failures = 0
		self.save(path)
