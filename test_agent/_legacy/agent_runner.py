"""Agent runner module for browser automation testing - MIGRATED to browser-use v0.11.8"""
import os
import json
import sys
from typing import Any
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use import Agent, AgentHistoryList, BrowserSession, BrowserProfile, Tools
from test_agent.register_custom_actions import register_custom_actions
from test_agent.config import config
from test_agent.view import TestCase, TestStepEncoder 

def _save_history_image(
    history_list: AgentHistoryList,
    output_path: str) -> None:
    """Save the last screenshot from agent history to a file."""
    last_item = None
    for item in reversed(history_list.history):
        if item.state.screenshot_path:  # 新版使用 screenshot_path
            last_item = item
            break
    
    if not last_item or not last_item.state.screenshot_path:
        return
    
    # 新版截图已经保存为文件，直接复制
    import shutil
    shutil.copy(last_item.state.screenshot_path, output_path)

async def run_agent(
    llm: Any,
    test: TestCase,
    trigger_id: str,
    run_id: int
) -> AgentHistoryList:
    """Run browser automation agent with given language model and task.
    
    MIGRATED to browser-use v0.11.8:
    - Browser + BrowserContext → BrowserSession + BrowserProfile
    - Controller → Tools
    - 移除 planner_llm (新版不需要单独的 planner)
    - 新增循环检测、规划系统、判断系统
    
    Args:
        llm: Language model for task execution (ChatAzureOpenAI from browser_use.llm.azure.chat)
        test: TestCase containing test steps
        trigger_id: Test trigger identifier
        run_id: Run identifier
        
    Returns:
        AgentHistoryList containing execution history
    """
    # 初始化 BrowserSession (替代旧的 Browser)
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            # 注意: Chrome 实例路径配置
            chrome_instance_path=config.edge_path,
            extra_chromium_args=[
                f'--profile-directory={config.profile}',
                f'--user-data-dir={config.user_data_dir}',
                '--enable-logging',
                '--v=1',
                *([] if not config.enable_features else [config.enable_features]),
                *([] if not config.disable_features else [config.disable_features])
            ],
            # 新版使用 BrowserProfile 配置，不需要单独的 new_context_config
            # pane_url 等配置可以通过其他方式处理
        )
    )
    
    # 设置 Tools (替代旧的 Controller)
    tools = Tools()
    register_custom_actions(tools)

    try:
        # 初始化 Agent - 使用新版 API
        agent = Agent(
            task=json.dumps(test.steps, cls=TestStepEncoder),
            llm=llm,
            browser=browser_session,  # 简化：直接传 BrowserSession
            tools=tools,  # Controller → Tools
            max_actions_per_step=5,  # 增加到 5（新版推荐）
            
            # 新版功能 - 解决动态页面问题
            use_judge=True,  # AI 判断任务完成
            enable_planning=True,  # 启用规划系统
            planning_replan_on_stall=3,  # 失败3次后重新规划
            loop_detection_enabled=True,  # 循环检测
            loop_detection_window=20,  # 检测窗口
            step_timeout=180,  # 步骤超时
            
            # 可选：使用 vision（如果需要）
            use_vision=config.vision_enabled,
        )
        
        # 运行 Agent
        history_list = await agent.run(max_steps=config.max_steps)
        
        # 保存截图
        output_path = f"{config.test_result_folder}/{trigger_id}/{run_id}.png"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        _save_history_image(history_list, output_path)
        
        # 保存历史（新版推荐）
        history_path = f"{config.test_result_folder}/{trigger_id}/{run_id}_history.json"
        agent.save_history(history_path)
        
        return history_list
    finally:
        # 新版 Agent 会自动清理，但如果需要手动关闭：
        # await agent.close()
        pass