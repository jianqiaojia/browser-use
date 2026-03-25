"""Test runner for automated browser tests using browser-use v0.11.8

This module provides functionality to run automated browser tests using Azure OpenAI.
Tests are defined in JSON files with steps, and execution history is automatically saved.

Major improvements in v0.11.8:
- No need for manual replay_steps - history is auto-saved
- Smart element matching with 5-layer strategy
- Built-in loop detection and page change detection
- Automatic variable detection for data-driven testing
"""
import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Any, Optional

from browser_use import Agent, BrowserProfile
from browser_use.llm.azure.chat import ChatAzureOpenAI
from azure.identity import DefaultAzureCredential

from config import config
from view import TestCase, ECTest, TestStep
from register_custom_actions import register_custom_actions


def check_azure_credential() -> bool:
    """Check if Azure credential is valid and set token to environment."""
    os.environ['AZURE_TENANT_ID'] = '72f988bf-86f1-41af-91ab-2d7cd011db47'
    os.environ['AZURE_CLIENT_ID'] = 'd24ab6d4-7ca0-48e9-a926-9f1363961414'
    os.environ['AZURE_CLIENT_SEND_CERTIFICATE_CHAIN'] = 'True'

    try:
        credential = DefaultAzureCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        
        os.environ["OPENAI_API_TYPE"] = "azure_ad"
        os.environ["OPENAI_API_KEY"] = token.token
        return True
    except Exception as e:
        print(f"Error with Azure credentials: {str(e)}")
        return False


def _init_llm() -> ChatAzureOpenAI:
    """Initialize Azure OpenAI language model with Azure AD auth."""
    if not check_azure_credential():
        raise EnvironmentError("Azure credentials are invalid or expired")
    
    azure_endpoint = "https://xpay-mobius.openai.azure.com/"
    api_key = os.environ.get('OPENAI_API_KEY')
    
    # 源码版本使用 browser_use.llm.azure.ChatAzureOpenAI
    llm = ChatAzureOpenAI(
        model='gpt-4o',
        azure_endpoint=azure_endpoint,
        api_key=api_key,
        api_version='2024-08-01-preview',
        add_schema_to_system_prompt=True,  # Add JSON schema to system prompt instead of response_format
        dont_force_structured_output=True,  # Don't use response_format for structured output
    )
    
    return llm


def build_task_from_steps(steps: list[TestStep]) -> str:
    """Build task description from test steps.
    
    Args:
        steps: List of test steps
        
    Returns:
        Task description string
    """
    task_parts = []
    for step in steps:
        task_parts.append(f"{step.step_name}: {step.step_description}")
    return "\n".join(task_parts)


async def run_test_case(
    llm: Any,
    test: TestCase,
    trigger_id: str,
    run_id: int
) -> bool:
    """Execute a test case.

    Args:
        llm: Language model to use for the agent
        test: Test case to execute
        trigger_id: Identifier for the test trigger
        run_id: Run identifier

    Returns:
        True if test passed, False otherwise
    """
    
    print(f"\n{'='*60}")
    print(f"Test Case: {test.test_case_name}")
    print(f"Description: {test.test_case_description}")
    print(f"Trigger ID: {trigger_id}, Run ID: {run_id}")
    print(f"{'='*60}")
    
    try:
        # 从 steps 构建任务
        task = build_task_from_steps(test.steps)
        print(f"\n📋 Task:\n{task}\n")
        
        # 从 config 获取浏览器配置
        browser_config = config.get_browser_profile_config()
        
        # 创建 Browser Profile（使用自定义 Edge 配置）
        browser_profile = BrowserProfile(**browser_config)
        
        # 创建并运行 Agent（源码版本 - 直接传参数）
        print("🤖 Creating and running agent...")
        agent = Agent(
            task=task,
            llm=llm,
            browser_profile=browser_profile,
            max_actions_per_step=config.max_actions_per_step,
            use_vision=config.vision_enabled,
        )
        
        # 注册自定义 actions
        register_custom_actions(agent.tools)
        
        # 运行测试
        print("▶️  Executing test...")
        history = await agent.run(max_steps=config.max_steps)
        
        # 保存 history（自动的，方便调试和回归测试）
        safe_name = test.test_case_name.replace(" ", "_").replace("-", "_").lower()
        history_file = f"test_case/{safe_name}.history.json"
        
        print(f"\n💾 Saving history to {history_file}")
        agent.save_history(history_file)
        
        # 检查结果
        success = history.is_successful()
        
        # 打印统计信息
        print(f"\n📊 Test Statistics:")
        print(f"  Total steps: {len(history.history)}")
        print(f"  Total actions: {len(history.action_names())}")
        print(f"  Action types: {set(history.action_names())}")
        
        if success:
            print("\n✅ Test PASSED")
        else:
            print("\n⚠️  Test completed with warnings")
            if history.errors():
                print("  Errors:")
                for error in history.errors():
                    if error:       
                        print(f"    - {error}")
        
        return success if success is not None else False
    
    except Exception as e:
        print(f"\n❌ Error running test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def load_test_file(test_file: str) -> ECTest:
    """Load test case from JSON file.
    
    Args:
        test_file: Path to test JSON file
        
    Returns:
        ECTest object
        
    Raises:
        FileNotFoundError: If test file not found
    """
    print(f"\n{'='*60}")
    print(f"Loading test file: {test_file}")
    print(f"{'='*60}")
    
    test_path = Path(test_file)
    if not test_path.exists():
        raise FileNotFoundError(f"Test file not found: {test_file}")
    
    with open(test_path, 'r', encoding='utf-8') as f:
        test_data = json.load(f)
    
    return ECTest(**test_data)


async def run_test_file(
    test_file: str,
    trigger_id: str = "manual",
    run_id: int = 1
) -> bool:
    """Run tests from a test file.
    
    Args:
        test_file: Path to test JSON file
        trigger_id: Identifier for the test trigger
        run_id: Run identifier
        
    Returns:
        True if all tests passed, False otherwise
    """
    ec_test = load_test_file(test_file)
    
    llm = _init_llm()
    
    # Run tests
    results = []
    for test_case in ec_test.test_cases:
        success = await run_test_case(
            llm,
            test_case,
            trigger_id,
            run_id
        )
        
        results.append({
            "test_case": test_case.test_case_name,
            "success": success
        })
    
    # Print summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")
    for result in results:
        status = "✅ PASS" if result["success"] else "❌ FAIL"
        print(f"{status} {result['test_case']}")
    
    total = len(results)
    passed = sum(1 for r in results if r["success"])
    failed = total - passed
    
    print(f"\n📊 Overall Results:")
    print(f"  Total: {total}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Success Rate: {passed/total*100:.1f}%")
    
    return failed == 0


async def main():
    """Main entry point for the test runner."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run browser automation tests (auto-discovers *.test.json)"
    )
    parser.add_argument(
        "--trigger-id",
        default="manual",
        help="Test trigger identifier (default: manual)"
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=1,
        help="Test run identifier (default: 1)"
    )
    
    args = parser.parse_args()
    
    # Auto-discover test files
    script_dir = Path(__file__).parent
    test_files = list(script_dir.glob('test_case/**/*.test.json'))
    
    if not test_files:
        print("❌ No test files found in test_case/")
        sys.exit(1)
    
    print(f"\n🔍 Found {len(test_files)} test file(s):")
    for tf in test_files:
        print(f"  - {tf.relative_to(script_dir)}")
    
    # Run all test files
    all_success = True
    for test_file in test_files:
        success = await run_test_file(
            str(test_file),
            args.trigger_id,
            args.run_id
        )
        if not success:
            all_success = False
    
    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    asyncio.run(main())