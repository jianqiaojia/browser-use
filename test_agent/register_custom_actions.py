"""Custom actions registration for browser automation - MIGRATED to browser-use v0.11.8"""
import os
import sys
import time
import asyncio
from pathlib import Path
from typing import Any, Optional

# 新版导入
from browser_use import Agent, BrowserSession, Tools
from browser_use.agent.views import ActionResult

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel

from test_agent.view import SetSessionStorageAction
from test_agent.config import config
from test_agent.custom_actions.os_click import register_os_click
from test_agent.custom_actions.cdp_click import register_cdp_click
from test_agent.utils.uia_helper import UIAHelper

class LoginToMSA(BaseModel):
    userName: str
    password: str

class BingSearchModel(BaseModel):
    text: str
    bingUrl: Optional[str] = None

class UIASelectAutofillModel(BaseModel):
    profile_index: int = 0
    payment_index: int = 0

class UIAWaitForPopupModel(BaseModel):
    timeout: float = 10.0
    check_interval: float = 0.3

class LogMonitorWaitForStateModel(BaseModel):
    expected_state: str = "AutofillSucceeded"
    timeout: float = 30.0

def register_custom_actions(tools: Tools):
    """Register custom actions for test automation.

    MIGRATED to browser-use v0.11.8:
    - Controller → Tools
    - browser: BrowserContext → browser_session: BrowserSession
    - 使用新版的 Agent API
    """

    # Register os_click for real OS-level mouse clicks
    register_os_click(tools.registry)

    # Register cdp_click for CDP clicks with window focus management
    register_cdp_click(tools.registry)

    # Initialize UIA Helper instance (shared across all actions)
    uia_helper = UIAHelper()

    async def call_agent(
        task: str,
        browser_session: BrowserSession,  # 新版：BrowserSession
        agent_llm: Any,
        tools_instance: Tools,  # 传入 tools 以便嵌套 agent 使用
    ) -> ActionResult:
        """Helper function to call a sub-agent for complex tasks."""
        agent = Agent(
            task=task,
            llm=agent_llm,
            browser=browser_session,  # 新版：简化的 API
            tools=tools_instance,
            max_actions_per_step=4,
            use_vision=False,  # 避免日志过多
            # 新版功能
            enable_planning=True,
            loop_detection_enabled=True,
        )
        
        ret = await agent.run(max_steps=20)

        # 检查最后一个结果
        if not ret.history:
            return ActionResult(error="No history found", include_in_memory=True)
        
        last_result = ret.history[-1].result[-1]

        return ActionResult(
            extracted_content=last_result.extracted_content,
            error=last_result.error,
            include_in_memory=True,
        )

    @tools.action(
        description="""Search on Bing for a specific query; if Bing url is specified, use that specified Url.
        always use this tool for searching on **Bing** before considering others
        """,
        param_model=BingSearchModel
    )
    async def search_on_bing(
        params: BingSearchModel,
        browser_session: BrowserSession,  # 新版参数
    ) -> ActionResult:
        print('🔶🔶🔶 search_on_bing')
        bingUrl = params.bingUrl if params.bingUrl is not None else 'https://www.bing.com'
        
        task = f"""
            1. goto {bingUrl} if current url is not {bingUrl}
            2. type "{params.text}" in the search bar
            3. press enter 
            """
        
        # 需要传入 tools 和 llm
        # 注意：这需要从外部传入，或者使用闭包
        # 这里简化处理，实际使用时需要调整
        final_result = await call_agent(task, browser_session, None, tools)
        print('🟧🟧🟧 search_on_bing done')
        return final_result

    @tools.action(
        description="""sign in to bing.com, using the provided username and password.
        always use this tool to sign in to bing.com before considering others.
        """,
        param_model=LoginToMSA
    )
    async def login_to_bing(
        params: LoginToMSA,
        browser_session: BrowserSession,  # 新版参数
    ) -> ActionResult:
        print('🟣🟣🟣 login_to_bing')
        task = f"""
        1. click sign in button in bing.com, and then a dropdown menu will appear
        2. select the option to use a personal account in the dropdown menu
        3. complete the sign in process using user name: {params.userName}, and password: {params.password}
        """
        
        final_result = await call_agent(task, browser_session, None, tools)
        print('🟩🟩🟩 login_to_bing done')
        return final_result
    
    @tools.action(
        description='switch to target tab - call this function when the agent need to switch to target tab with given domain',
    )
    async def switch_tab_with_target_domain(
        domain: str,
        browser_session: BrowserSession  # 新版参数
    ):
        """Switch to a tab with the specified domain."""
        # 新版 API 调整
        page = await browser_session.get_current_page()
        pages = page.context.pages
        
        for p in pages:
            if domain in p.url:
                await p.bring_to_front()
                await p.wait_for_load_state()
                # 更新当前页面
                browser_session._current_page = p
                msg = f'🔗 Switched to tab with {domain} successfully'
                return ActionResult(extracted_content=msg, include_in_memory=True)
        
        return ActionResult(
            error=f'Tab with domain {domain} not found',
            include_in_memory=True
        )

    @tools.action(
        description='Refresh current page',
    )
    async def refresh_page(browser_session: BrowserSession) -> ActionResult:
        """Refresh the current page."""
        page = await browser_session.get_current_page()
        await page.reload()
        msg = '🔗 Refreshed the page'
        return ActionResult(extracted_content=msg, include_in_memory=False)
        
    @tools.action(
        description='Set a value in sessionStorage for the current page',
        param_model=SetSessionStorageAction,
    )
    async def set_session_storage(
        params: SetSessionStorageAction,
        browser_session: BrowserSession  # 新版参数
    ) -> ActionResult:
        """Set a value in sessionStorage"""
        page = await browser_session.get_current_page()
        try:
            await page.evaluate(
                "(key, value) => { sessionStorage.setItem(key, value); }",
                [params.key, params.value]
            )
            msg = f'🔧 Set sessionStorage[{params.key}] = {params.value}'
            return ActionResult(extracted_content=msg, include_in_memory=True)
        except Exception as e:
            msg = f'Failed to set sessionStorage: {str(e)}'
            return ActionResult(error=msg, include_in_memory=True)

    @tools.action(
        description='Wait for the autofill popup to appear using UIA Helper - continuously checks until popup is detected or timeout',
        param_model=UIAWaitForPopupModel
    )
    async def uia_wait_for_popup(
        params: UIAWaitForPopupModel,
        browser_session: BrowserSession  # 新版参数
    ) -> ActionResult:
        """Wait for autofill popup to appear with continuous monitoring"""
        print(f'🔍 Waiting for autofill popup (timeout: {params.timeout}s, interval: {params.check_interval}s)...')

        start_time = time.time()
        check_count = 0

        while (time.time() - start_time) < params.timeout:
            check_count += 1

            try:
                # 直接调用 find_autofill_popup 检测是否存在
                result = uia_helper.find_autofill_popup()

                if result and result.get('success'):
                    elapsed = time.time() - start_time
                    msg = f'✅ Autofill popup detected after {elapsed:.1f}s ({check_count} checks)'
                    print(msg)
                    return ActionResult(
                        extracted_content=msg,
                        include_in_memory=True,
                    )
            except Exception as e:
                print(f'Check #{check_count} failed: {str(e)}')

            await asyncio.sleep(params.check_interval)  # 新版：使用 asyncio.sleep

        elapsed = time.time() - start_time
        msg = f'❌ Timeout: Autofill popup not detected after {elapsed:.1f}s ({check_count} checks)'
        print(msg)
        return ActionResult(
            error=msg,
            include_in_memory=True,
            success=False
        )
    
    @tools.action(
        description='Click the autofill button using UIA Helper - use this after popup is detected to trigger autofill and automatically fill the form',
        param_model=UIASelectAutofillModel
    )
    async def uia_select_autofill(
        params: UIASelectAutofillModel,
        browser_session: BrowserSession  # 新版参数
    ) -> ActionResult:
        """Click the autofill button via UIA Helper to trigger autofill"""
        print(f'⚡ Clicking autofill button via UIA (profile_index: {params.profile_index}, payment_index: {params.payment_index})...')

        try:
            result = uia_helper.select_and_confirm(
                profile_index=params.profile_index,
                payment_index=params.payment_index
            )

            if result.get('success'):
                msg = f'✅ Successfully selected autofill option at index {params.profile_index}'
                if result.get('warning'):
                    msg += f' (Warning: {result.get("warning")})'
                print(msg)
                return ActionResult(
                    extracted_content=msg,
                    include_in_memory=True,
                )
            else:
                error = result.get('error', 'Unknown error')
                msg = f'❌ Failed to select autofill option: {error}'
                print(msg)
                return ActionResult(
                    error=msg,
                    include_in_memory=True,
                    success=False
                )
        except Exception as e:
            msg = f'❌ Failed to execute UIA select operation: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)
    
    @tools.action(
        description='Initialize log file monitor - call this at the beginning of checkout test to monitor autofill status from Edge logs',
    )
    async def logmonitor_init(browser_session: BrowserSession) -> ActionResult:
        """Initialize log file monitor for checkout state tracking"""
        try:
            print('🔧 Initializing log file monitor...')
            
            # Import LogFileMonitor
            from test_agent.utils.log_file_monitor import LogFileMonitor
            
            # 新版：将监视器存储在 browser_session 的自定义属性中
            log_path = config.log_file_path
            
            # 创建自定义属性存储
            if not hasattr(browser_session, '_custom_data'):
                browser_session._custom_data = {}
            
            browser_session._custom_data['log_monitor'] = LogFileMonitor(log_file_path=log_path)
            
            # Initialize position (read to current end of file)
            browser_session._custom_data['log_monitor'].check_new_states()
            
            msg = f'✅ Log file monitor initialized. Monitoring: {log_path}'
            print(msg)
            return ActionResult(extracted_content=msg, include_in_memory=True)
            
        except Exception as e:
            msg = f'❌ Failed to initialize log monitor: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)
    
    @tools.action(
        description='Wait for checkout state from log file - use after autofill to verify success (e.g., AutofillSucceeded, AutofillFailed)',
        param_model=LogMonitorWaitForStateModel
    )
    async def logmonitor_wait_for_state(
        params: LogMonitorWaitForStateModel,
        browser_session: BrowserSession  # 新版参数
    ) -> ActionResult:
        """Wait for checkout state to reach expected value by monitoring log file"""
        try:
            print(f'⏳ Waiting for checkout state: {params.expected_state} (timeout: {params.timeout}s)...')
            
            # 检查监视器是否初始化
            if not hasattr(browser_session, '_custom_data') or 'log_monitor' not in browser_session._custom_data:
                msg = '❌ Log monitor not initialized. Call logmonitor_init first.'
                print(msg)
                return ActionResult(error=msg, include_in_memory=True, success=False)
            
            monitor = browser_session._custom_data['log_monitor']
            start_time = time.time()
            check_count = 0
            
            while (time.time() - start_time) < params.timeout:
                check_count += 1
                elapsed = time.time() - start_time
                
                # Check for new states in log
                new_states = monitor.check_new_states()
                
                if new_states:
                    for state in new_states:
                        print(f"🔔 [{state['timestamp_str']}] State: {state['state_name']}")
                        
                        # Check if this is the expected state
                        if state['state_name'] == params.expected_state:
                            msg = f'✅ Checkout state reached {params.expected_state} after {elapsed:.1f}s'
                            print(msg)
                            return ActionResult(
                                extracted_content=msg,
                                include_in_memory=True,
                            )
                
                await asyncio.sleep(0.5)
            
            # Timeout
            elapsed = time.time() - start_time
            states_history = [s['state_name'] for s in monitor.states_history]
            msg = f'❌ Timeout: Expected state {params.expected_state} not reached after {elapsed:.1f}s (checked {check_count} times). States: {states_history}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)
            
        except Exception as e:
            msg = f'❌ Failed to wait for checkout state: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)
    
    @tools.action(
        description='Get checkout state history from log file - returns all state changes detected',
    )
    async def logmonitor_get_history(browser_session: BrowserSession) -> ActionResult:
        """Get checkout state change history from log file"""
        try:
            if not hasattr(browser_session, '_custom_data') or 'log_monitor' not in browser_session._custom_data:
                msg = 'Log monitor not initialized. No state history available.'
                return ActionResult(extracted_content=msg, include_in_memory=True)
            
            monitor = browser_session._custom_data['log_monitor']
            states = monitor.states_history
            
            if not states:
                msg = 'No checkout state changes detected in log file yet'
            else:
                states_list = [s['state_name'] for s in states]
                msg = f'Checkout state history ({len(states)} changes): {states_list}'
            
            print(msg)
            return ActionResult(extracted_content=msg, include_in_memory=True)
            
        except Exception as e:
            msg = f'❌ Failed to get state history: {str(e)}'
            print(msg)
            return ActionResult(error=msg, include_in_memory=True, success=False)