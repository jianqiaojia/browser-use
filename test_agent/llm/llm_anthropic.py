"""
Direct Anthropic LLM config for Claude via MicrosoftAI LLM Proxy

Uses native Anthropic client which handles structured output better than OpenAI-compatible mode.
"""
import os
from browser_use.llm.anthropic.chat import ChatAnthropic


def get_claude_sonnet_native(
	model: str = 'claude-sonnet-4-20250514',
	base_url: str = 'http://localhost:5000',
	api_key: str | None = None,
) -> ChatAnthropic:
	"""Get Claude using native Anthropic client.

	This works better than OpenAI-compatible mode for structured output.

	Args:
		model: Claude model name
		base_url: Proxy endpoint
		api_key: API key (auto-detected from env if None)

	Returns:
		ChatAnthropic instance
	"""
	if api_key is None:
		api_key = (
			os.environ.get('ANTHROPIC_API_KEY') or
			os.environ.get('OPENAI_API_KEY') or
			os.environ.get('LITELLM_API_KEY') or
			'sk-1234'
		)

	llm = ChatAnthropic(
		model=model,
		api_key=api_key,
		base_url=base_url,
		temperature=0.7,
	)

	return llm


if __name__ == '__main__':
	import asyncio
	from browser_use.llm.messages import UserMessage

	async def test():
		print("Testing native Anthropic client...")
		llm = get_claude_sonnet_native()

		result = await llm.ainvoke([
			UserMessage(content='Say "Hello from native Claude!" in JSON: {"message": "..."}')
		])
		print(f"Response: {result.completion}")

	asyncio.run(test())
