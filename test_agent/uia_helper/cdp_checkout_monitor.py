"""
CDP Protocol Checkout State Monitor
使用 EdgeWallet CDP Protocol 监听 Express Checkout 状态变化
"""

import asyncio
from playwright.async_api import async_playwright, CDPSession
from typing import Optional, Callable
from datetime import datetime


class CheckoutStateMonitor:
    """Express Checkout 状态监听器 (使用 CDP Protocol)"""
    
    def __init__(self):
        self.cdp_session: Optional[CDPSession] = None
        self.state_callback: Optional[Callable] = None
        self.last_state = None
        self.states_history = []
    
    async def connect(self, browser_url: str = "http://localhost:9222"):
        """
        连接到 Edge 浏览器的 DevTools Protocol
        
        Args:
            browser_url: 浏览器 CDP 端点 URL
                        启动浏览器时需要添加: --remote-debugging-port=9222
        """
        playwright = await async_playwright().start()
        
        try:
            # 连接到已运行的浏览器
            browser = await playwright.chromium.connect_over_cdp(browser_url)
            contexts = browser.contexts
            
            if not contexts:
                raise Exception("No browser contexts found. Please open a page in Edge first.")
            
            # 获取第一个 context 和 page
            context = contexts[0]
            pages = context.pages
            
            if not pages:
                raise Exception("No pages found. Please open a page in Edge first.")
            
            page = pages[0]
            
            # 创建 CDP Session
            self.cdp_session = await context.new_cdp_session(page)
            
            print(f"✅ Connected to Edge browser")
            print(f"   Page: {page.url}")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            print("\n💡 Make sure Edge is running with:")
            print('   msedge.exe --remote-debugging-port=9222')
            return False
    
    async def enable_tracking(self):
        """启用 Checkout 状态跟踪"""
        if not self.cdp_session:
            raise Exception("Not connected. Call connect() first.")
        
        # 注册事件监听
        self.cdp_session.on(
            "EdgeWallet.checkoutStateChanged",
            self._on_state_changed
        )
        
        # 启用跟踪
        await self.cdp_session.send("EdgeWallet.enableCheckoutStateTracking")
        print("✅ Checkout state tracking enabled")
    
    async def disable_tracking(self):
        """禁用 Checkout 状态跟踪"""
        if not self.cdp_session:
            return
        
        await self.cdp_session.send("EdgeWallet.disableCheckoutStateTracking")
        print("🛑 Checkout state tracking disabled")
    
    def _on_state_changed(self, params: dict):
        """处理状态变化事件"""
        state = params.get('state')
        timestamp = params.get('timestamp')
        
        # 记录状态
        self.last_state = state
        self.states_history.append({
            'state': state,
            'timestamp': timestamp,
            'time': datetime.fromtimestamp(timestamp / 1000).strftime('%H:%M:%S.%f')[:-3]
        })
        
        # 打印状态变化
        time_str = datetime.fromtimestamp(timestamp / 1000).strftime('%H:%M:%S.%f')[:-3]
        print(f"\n🔔 [{time_str}] Checkout State Changed: {state}")
        
        # 调用用户回调
        if self.state_callback:
            self.state_callback(state, timestamp)
    
    def set_state_callback(self, callback: Callable):
        """
        设置状态变化回调函数
        
        Args:
            callback: 回调函数，签名为 callback(state: str, timestamp: float)
        """
        self.state_callback = callback
    
    def get_states_history(self):
        """获取状态历史"""
        return self.states_history
    
    def print_summary(self):
        """打印状态变化总结"""
        print("\n" + "=" * 60)
        print("Checkout State Changes Summary")
        print("=" * 60)
        
        if not self.states_history:
            print("No state changes recorded")
            return
        
        print(f"Total state changes: {len(self.states_history)}\n")
        
        for i, record in enumerate(self.states_history, 1):
            print(f"{i}. [{record['time']}] {record['state']}")
        
        print("\n" + "=" * 60)


async def example_usage():
    """示例：如何使用 CheckoutStateMonitor"""
    
    print("=" * 60)
    print("CDP Checkout State Monitor Example")
    print("=" * 60)
    
    # 创建监听器
    monitor = CheckoutStateMonitor()
    
    # 连接到浏览器
    print("\n📡 Connecting to Edge browser...")
    if not await monitor.connect():
        return
    
    # 设置自定义回调（可选）
    def on_state_change(state: str, timestamp: float):
        """自定义状态处理"""
        if state == "SUCCEEDED":
            print("   ✅ Autofill succeeded!")
        elif state == "FAILED":
            print("   ❌ Autofill failed!")
        elif state == "PARTIAL_SUCCEEDED":
            print("   ⚠️  Autofill partially succeeded")
    
    monitor.set_state_callback(on_state_change)
    
    # 启用跟踪
    await monitor.enable_tracking()
    
    print("\n" + "=" * 60)
    print("Monitoring checkout state changes...")
    print("=" * 60)
    print("\n💡 Now perform checkout actions in the browser.")
    print("   Press Ctrl+C to stop monitoring.\n")
    
    try:
        # 保持运行，监听事件
        await asyncio.sleep(60)  # 监听 60 秒
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping monitor...")
    finally:
        # 禁用跟踪
        await monitor.disable_tracking()
        
        # 打印总结
        monitor.print_summary()


async def example_with_playwright_test():
    """示例：结合 Playwright 进行完整的自动化测试"""
    
    print("=" * 60)
    print("Complete Automation Test Example")
    print("=" * 60)
    
    async with async_playwright() as p:
        # 启动浏览器并启用 CDP
        browser = await p.chromium.launch(
            channel="msedge",
            headless=False,
            args=['--remote-debugging-port=9222']
        )
        
        context = await browser.new_context()
        page = await context.new_page()
        
        # 创建 CDP Session
        cdp = await context.new_cdp_session(page)
        
        # 启用 EdgeWallet 跟踪
        print("\n✅ Enabling EdgeWallet tracking...")
        cdp.on("EdgeWallet.checkoutStateChanged", lambda params: 
            print(f"🔔 State: {params['state']} at {params['timestamp']}")
        )
        await cdp.send("EdgeWallet.enableCheckoutStateTracking")
        
        # 导航到测试页面
        print("\n🌐 Navigating to test page...")
        await page.goto("https://example.com/checkout")  # 替换为实际测试页面
        
        # 执行测试步骤
        print("\n🧪 Performing test actions...")
        # TODO: 添加你的测试步骤
        # await page.click('#express-checkout-button')
        # await page.wait_for_selector('.popup')
        
        # 等待状态变化
        print("\n⏳ Waiting for checkout completion...")
        await asyncio.sleep(10)
        
        # 禁用跟踪
        await cdp.send("EdgeWallet.disableCheckoutStateTracking")
        
        await browser.close()
        print("\n✅ Test completed")


if __name__ == '__main__':
    # 运行示例
    print("\nSelect example to run:")
    print("1. Basic monitoring (connect to existing browser)")
    print("2. Complete test (launch new browser)")
    
    choice = input("\nChoice (1-2): ").strip()
    
    if choice == '1':
        asyncio.run(example_usage())
    elif choice == '2':
        asyncio.run(example_with_playwright_test())
    else:
        print("Invalid choice")