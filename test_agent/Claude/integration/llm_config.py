"""
Simple LLM config for MicrosoftAI LLM Proxy (litellm with GitHub Copilot)

Usage:
    from llm_config import get_claude_sonnet, get_gpt4o

    # Use Claude (recommended - native Anthropic client)
    llm = get_claude_sonnet()

    # Or use GPT-4o
    llm = get_gpt4o()
"""
import os
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.anthropic.chat import ChatAnthropic

# Default MicrosoftAI LLM Proxy endpoint (litellm)
DEFAULT_PROXY_ENDPOINT = os.environ.get('LLM_PROXY_ENDPOINT', 'http://localhost:5000')
DEFAULT_PROXY_API_KEY = os.environ.get('LLM_PROXY_API_KEY', 'dummy-key')  # litellm usually doesn't need real key


def get_claude_sonnet(
	model: str = 'claude-sonnet-4-20250514',
	base_url: str | None = None,
	api_key: str | None = None,
	use_native_client: bool = True,
) -> ChatAnthropic | ChatOpenAI:
	"""Get Claude Sonnet via MicrosoftAI LLM Proxy.

	Args:
		model: Claude model name
			- 'claude-sonnet-4-20250514' (Sonnet 4 latest)
			- 'claude-3-5-sonnet-20241022' (Sonnet 3.5 v2)
			- 'claude-3-5-sonnet-20240620' (Sonnet 3.5 v1)
		base_url: Proxy endpoint (default: http://localhost:5000)
		api_key: API key for proxy (if None, tries env vars or 'sk-1234')
		use_native_client: Use native Anthropic client (recommended, better structured output)

	Returns:
		ChatAnthropic or ChatOpenAI instance configured for Claude via proxy
	"""
	base_url = base_url or DEFAULT_PROXY_ENDPOINT

	# Try to get API key from environment or use a placeholder
	if api_key is None:
		# Try common environment variables
		api_key = (
			os.environ.get('ANTHROPIC_API_KEY') or
			os.environ.get('OPENAI_API_KEY') or
			os.environ.get('LITELLM_API_KEY') or
			'sk-1234'  # Placeholder - litellm proxy usually doesn't validate this
		)

	if use_native_client:
		# Use native Anthropic client - better for structured output
		llm = ChatAnthropic(
			model=model,
			api_key=api_key,
			base_url=base_url,
			temperature=0.7,
		)
	else:
		# Use OpenAI-compatible client - fallback option
		llm = ChatOpenAI(
			model=model,
			base_url=base_url,
			api_key=api_key,
			temperature=0.7,
			add_schema_to_system_prompt=True,
			dont_force_structured_output=True,
		)

	return llm


def get_gpt4o(
	model: str = 'gpt-4o',
	base_url: str | None = None,
	api_key: str | None = None,
) -> ChatOpenAI:
	"""Get GPT-4o via MicrosoftAI LLM Proxy.

	Args:
		model: OpenAI model name
		base_url: Proxy endpoint (default: http://localhost:4000)
		api_key: API key for proxy

	Returns:
		ChatOpenAI instance configured for GPT-4o via proxy
	"""
	base_url = base_url or DEFAULT_PROXY_ENDPOINT
	api_key = api_key or DEFAULT_PROXY_API_KEY

	llm = ChatOpenAI(
		model=model,
		base_url=base_url,
		api_key=api_key,
		temperature=0.2,
		add_schema_to_system_prompt=True,
		dont_force_structured_output=True,
	)

	return llm


# Quick test
if __name__ == '__main__':
	import asyncio
	from browser_use.llm.messages import UserMessage

	async def test_llm(llm, model_name: str):
		print(f"\n{'='*60}")
		print(f"Testing {model_name}")
		print(f"{'='*60}")

		try:
			result = await llm.ainvoke([UserMessage(content="Say 'Hello from LLM!' in JSON format: {\"message\": \"...\"}")])
			print(f"[OK] Response: {result.completion[:200]}")
		except Exception as e:
			print(f"[FAIL] Error: {e}")

	async def main():
		print("Testing MicrosoftAI LLM Proxy configuration...")

		# Test Claude
		claude = get_claude_sonnet()
		await test_llm(claude, "Claude Sonnet 4")

		# Test GPT-4o
		gpt4o = get_gpt4o()
		await test_llm(gpt4o, "GPT-4o")

	asyncio.run(main())
