"""
Monkey patch for browser-use to handle missing usage tokens from litellm proxy

Some proxies (like litellm with GitHub Copilot) don't return usage information.
This patch provides fallback values (0) instead of crashing.
"""


def patch_openai_get_usage():
	"""Patch ChatOpenAI._get_usage to handle None values"""
	from browser_use.llm.openai.chat import ChatOpenAI
	from browser_use.llm.views import ChatInvokeUsage

	original_get_usage = ChatOpenAI._get_usage

	def patched_get_usage(self, response):
		"""Get usage with fallback to 0 for None values"""
		if response.usage is None:
			# No usage info at all
			return ChatInvokeUsage(
				prompt_tokens=0,
				prompt_cached_tokens=None,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=None,
				completion_tokens=0,
				total_tokens=0,
			)

		# Has usage but some fields might be None
		completion_tokens = response.usage.completion_tokens or 0
		completion_token_details = response.usage.completion_tokens_details
		if completion_token_details is not None:
			reasoning_tokens = completion_token_details.reasoning_tokens
			if reasoning_tokens is not None:
				completion_tokens += reasoning_tokens

		return ChatInvokeUsage(
			prompt_tokens=response.usage.prompt_tokens or 0,
			prompt_cached_tokens=response.usage.prompt_tokens_details.cached_tokens
			if response.usage.prompt_tokens_details is not None
			else None,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=completion_tokens,
			total_tokens=response.usage.total_tokens or 0,
		)

	ChatOpenAI._get_usage = patched_get_usage


# Auto-patch when imported
patch_openai_get_usage()

print("[INFO] Applied litellm usage patch - usage tokens will default to 0 if missing")
