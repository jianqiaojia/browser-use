"""
UIA Helper 持续监控测试客户端
用于测试在Popup失去焦点就消失的情况下持续捕获
"""

import time
import threading
from typing import Dict, Any, Optional
from datetime import datetime
import sys
import os

# 添加项目路径以便导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from test_agent.utils.uia_helper import UIAHelper


class ContinuousUIAClient:
    """持续监控的UIA Helper客户端"""

    def __init__(self):
        self.uia_helper = UIAHelper()
        self.monitoring = False
        self.popup_detected = False
        self.last_popup_state = None
        self.monitor_thread = None

    def find_autofill_popup(self) -> Dict[str, Any]:
        """获取Popup状态"""
        try:
            result = self.uia_helper.find_autofill_popup()
            return result if result else {'success': False, 'error': 'find_autofill_popup returned None'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def select_and_confirm(self, profile_index: int = 0, payment_index: int = 0) -> Dict[str, Any]:
        """选择地址/支付方式并确认"""
        try:
            return self.uia_helper.select_and_confirm(
                profile_index=profile_index,
                payment_index=payment_index
            )
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _monitor_popup(self, check_interval: float = 0.5, timeout: float = 30):
        """
        持续监控Popup的出现
        
        Args:
            check_interval: 检查间隔（秒）
            timeout: 总超时时间（秒）
        """
        start_time = time.time()
        check_count = 0
        
        print(f"\n🔍 开始监控 Popup（每 {check_interval} 秒检查一次）...")
        print(f"⏱️  最长监控 {timeout} 秒")
        print("-" * 60)
        
        while self.monitoring and (time.time() - start_time) < timeout:
            check_count += 1
            elapsed = time.time() - start_time
            
            # 获取状态
            state = self.find_autofill_popup()

            if state.get('success'):
                # 检测到Popup
                if not self.popup_detected:
                    self.popup_detected = True
                    print(f"\n✅ [检查 #{check_count}] 检测到 Popup! (耗时: {elapsed:.1f}秒)")

                # 更新最后的状态
                self.last_popup_state = state

                # 显示持续检测到
                print(f"   [{datetime.now().strftime('%H:%M:%S')}] Popup 仍然可见", end='\r')
            else:
                # 未检测到Popup
                if self.popup_detected:
                    # 之前检测到了，现在消失了
                    print(f"\n⚠️  [检查 #{check_count}] Popup 已消失")
                    self.popup_detected = False
                else:
                    # 一直没检测到
                    print(f"   [{datetime.now().strftime('%H:%M:%S')}] 等待 Popup 出现... (已等待 {elapsed:.1f}秒)", end='\r')
            
            time.sleep(check_interval)
        
        if (time.time() - start_time) >= timeout:
            print(f"\n\n⏱️  监控超时（{timeout}秒）")
        
        print(f"\n监控结束，共检查 {check_count} 次")
        print("-" * 60)
    
    def start_monitoring(self, check_interval: float = 0.5, timeout: float = 30):
        """
        启动持续监控
        
        Args:
            check_interval: 检查间隔（秒），默认0.5秒
            timeout: 总超时时间（秒），默认30秒
        """
        if self.monitoring:
            print("⚠️  监控已在运行中")
            return
        
        self.monitoring = True
        self.popup_detected = False
        self.last_popup_state = None
        
        # 在新线程中运行监控
        self.monitor_thread = threading.Thread(
            target=self._monitor_popup,
            args=(check_interval, timeout)
        )
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """停止监控"""
        if not self.monitoring:
            print("⚠️  监控未运行")
            return
        
        print("\n🛑 停止监控...")
        self.monitoring = False
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
    
    def wait_for_popup(self, timeout: float = 30, check_interval: float = 0.5) -> Optional[Dict[str, Any]]:
        """
        等待Popup出现并返回状态
        
        Args:
            timeout: 超时时间（秒）
            check_interval: 检查间隔（秒）
        
        Returns:
            Popup状态字典，如果超时则返回None
        """
        start_time = time.time()
        
        print(f"\n⏳ 等待 Popup 出现（最多 {timeout} 秒）...")
        
        while (time.time() - start_time) < timeout:
            state = self.find_autofill_popup()

            if state.get('success'):
                elapsed = time.time() - start_time
                print(f"✅ 在 {elapsed:.1f} 秒后检测到 Popup")
                return state

            time.sleep(check_interval)
        
        print(f"❌ 超时：未在 {timeout} 秒内检测到 Popup")
        return None


def test_continuous_monitoring():
    """测试持续监控功能"""
    print("=" * 60)
    print("UIA Helper 持续监控测试")
    print("=" * 60)

    client = ContinuousUIAClient()

    # 检查 UIA Helper 初始化
    print("\n初始化 UIA Helper...")
    try:
        # 测试调用
        state = client.find_autofill_popup()
        print("✅ UIA Helper 初始化成功")
    except Exception as e:
        print(f"❌ UIA Helper 初始化失败: {e}")
        return

    print("\n" + "=" * 60)
    print("测试场景：持续监控 Popup（适合失去焦点就消失的情况）")
    print("=" * 60)

    print("\n⏳ 请在接下来的30秒内:")
    print("  1. 打开 Edge 浏览器")
    print("  2. 访问有 Express Checkout 的页面")
    print("  3. 点击 Express Checkout 按钮")
    print("  4. 让 Popup 显示（不要让它失去焦点）")

    input("\n按 Enter 开始监控...")

    # 启动持续监控（30秒，每0.3秒检查一次）
    client.start_monitoring(check_interval=0.3, timeout=30)

    # 等待监控完成
    if client.monitor_thread:
        client.monitor_thread.join()

    # 如果检测到了Popup，尝试操作
    if client.popup_detected and client.last_popup_state:
        print("\n" + "=" * 60)
        print("检测到 Popup，准备执行操作...")
        print("=" * 60)

        choice = input("\n是否要选择第一个选项并确认？(y/n): ").strip().lower()

        if choice == 'y':
            print("\n执行操作...")
            # 快速获取最新状态并操作
            state = client.find_autofill_popup()
            if state.get('success'):
                result = client.select_and_confirm(profile_index=0)
                if result.get('success'):
                    print("✅ 操作成功")
                else:
                    print(f"❌ 操作失败: {result.get('error')}")
            else:
                print("❌ Popup 已消失，无法操作")
    else:
        print("\n❌ 未检测到 Popup")


def test_wait_and_act():
    """测试等待并立即操作"""
    print("=" * 60)
    print("UIA Helper 等待并立即操作测试")
    print("=" * 60)

    client = ContinuousUIAClient()

    # 检查初始化
    print("\n初始化 UIA Helper...")
    try:
        state = client.find_autofill_popup()
        print("✅ UIA Helper 初始化成功")
    except Exception as e:
        print(f"❌ UIA Helper 初始化失败: {e}")
        return

    print("\n" + "=" * 60)
    print("测试场景：等待 Popup 出现后立即操作")
    print("=" * 60)

    print("\n⏳ 请准备:")
    print("  1. 确保 Edge 浏览器已打开")
    print("  2. 访问有 Express Checkout 的页面")

    input("\n准备好后按 Enter，然后立即点击 Express Checkout 按钮...")

    # 等待 Popup 出现（检查频率更高，反应更快）
    state = client.wait_for_popup(timeout=15, check_interval=0.2)

    if state:
        print(f"\n检测到 Popup")

        # 立即执行操作（在Popup消失前）
        print("\n⚡ 立即执行操作...")
        result = client.select_and_confirm(profile_index=0)

        if result.get('success'):
            print("✅ 操作成功")
            if result.get('warning'):
                print(f"⚠️  {result.get('warning')}")
        else:
            print(f"❌ 操作失败: {result.get('error')}")
    else:
        print("\n❌ 未能在规定时间内检测到 Popup")


def main():
    """主函数"""
    while True:
        print("\n" + "=" * 60)
        print("UIA Helper 持续监控测试工具")
        print("=" * 60)
        print("\n选择测试模式:")
        print("  1. 持续监控模式（适合观察Popup行为）")
        print("  2. 等待并立即操作模式（适合实际测试）")
        print("  0. 退出")
        print("=" * 60)
        
        choice = input("\n请选择 (0-2): ").strip()
        
        if choice == '0':
            print("\n退出程序")
            break
        elif choice == '1':
            test_continuous_monitoring()
        elif choice == '2':
            test_wait_and_act()
        else:
            print("❌ 无效选项")
        
        input("\n按 Enter 继续...")


if __name__ == '__main__':
    main()