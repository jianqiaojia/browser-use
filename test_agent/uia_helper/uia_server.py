"""
UIA Helper Server - Python实现
用于通过Windows UI Automation API操作Edge浏览器的Native UI组件
"""

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, List, Any
import comtypes.client

# 动态加载 UI Automation 类型库
def _get_uia_client():
    """获取 UIAutomationClient 模块"""
    try:
        # 尝试导入已生成的模块
        from comtypes.gen import UIAutomationClient
        return UIAutomationClient
    except ImportError:
        # 如果没有生成，则动态生成
        print("正在生成 UI Automation 类型库...")
        import comtypes.client
        uia = comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient
        print("类型库生成完成")
        return UIAutomationClient

# 加载 UIAutomationClient
UIAutomationClient = _get_uia_client()


class UIAHelper:
    """Windows UI Automation 辅助类"""
    
    def __init__(self):
        # 初始化 UI Automation
        self.uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=UIAutomationClient.IUIAutomation
        )
        self.root = self.uia.GetRootElement()
    
    def _has_express_checkout_popup_features(self, window: Any) -> bool:
        """
        检查窗口是否是Express Checkout Popup
        基于edge_express_checkout_view.cc和edge_wallet_strings.grdp中的特征：
        1. 固定宽度308像素 (kDefaultPaymentPopupWidth)
        2. 包含特定文本: "Contact info" / "Payment methods" / "Autofill" / "Saved info" / "Saved cards"
        """
        try:
            # 1. 检查窗口宽度 (308px是Express Checkout popup的固定宽度)
            rect = window.CurrentBoundingRectangle
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            
            # 宽度应该正好是308，允许DPI缩放导致的误差
            if not (300 <= width <= 320):
                print(f"  ✗ Width mismatch: {width}px (expected ~308px)")
                return False
            
            print(f"  ✓ Width check passed: {width}px")
            
            # 2. 收集所有文本和按钮用于匹配
            all_text_content = []
            
            # 查找所有文本元素
            try:
                text_condition = self.uia.CreatePropertyCondition(
                    UIAutomationClient.UIA_ControlTypePropertyId,
                    UIAutomationClient.UIA_TextControlTypeId
                )
                texts = window.FindAll(UIAutomationClient.TreeScope_Descendants, text_condition)
                
                for i in range(texts.Length):
                    try:
                        text_elem = texts.GetElement(i)
                        name = text_elem.CurrentName
                        if name and name.strip():
                            all_text_content.append(name)
                    except:
                        continue
            except Exception as e:
                print(f"  ✗ Error getting texts: {e}")
            
            # 查找所有按钮
            try:
                button_condition = self.uia.CreatePropertyCondition(
                    UIAutomationClient.UIA_ControlTypePropertyId,
                    UIAutomationClient.UIA_ButtonControlTypeId
                )
                buttons = window.FindAll(UIAutomationClient.TreeScope_Descendants, button_condition)
                
                for i in range(buttons.Length):
                    try:
                        btn = buttons.GetElement(i)
                        name = btn.CurrentName
                        if name and name.strip():
                            all_text_content.append(name)
                    except:
                        continue
            except Exception as e:
                print(f"  ✗ Error getting buttons: {e}")
            
            print(f"  Found {len(all_text_content)} text/button elements")
            if all_text_content:
                print(f"  Sample content: {all_text_content[:5]}")
            
            # 3. 检查特征字符串 (从edge_wallet_strings.grdp)
            # 这些是Express Checkout popup的特有字符串
            feature_strings = {
                'Contact info',      # IDS_EDGE_EC_INLINE_CONTACT_INFO
                'Payment methods',   # IDS_EDGE_WALLET_PAYMENT_METHODS
                'Autofill',         # IDS_EDGE_EC_INLINE_AUTOFILL
                'Saved info',       # IDS_EDGE_EC_INLINE_SAVED_INFO
                'Saved cards',      # IDS_EDGE_EC_INLINE_SAVED_CARDS
                'Manage',           # IDS_EDGE_EC_INLINE_Manage
            }
            
            # 计算匹配的特征字符串数量
            matched_features = []
            for feature in feature_strings:
                if any(feature in text for text in all_text_content):
                    matched_features.append(feature)
                    print(f"  ✓ Found feature: '{feature}'")
            
            # 判断：宽度匹配 + 至少2个特征字符串
            if len(matched_features) >= 2:
                print(f"  ✅ Found Express Checkout Popup! (matched {len(matched_features)} features)")
                return True
            
            print(f"  ✗ Not enough features matched ({len(matched_features)}/2 required)")
            return False
            
        except Exception as e:
            print(f"  ✗ Error checking features: {e}")
            return False
    
    def find_autofill_popup(self) -> Optional[Dict[str, Any]]:
        """
        查找 Express Checkout Popup
        基于C++代码edge_express_checkout_view.cc:
        - Line 604: PopupBaseView(controller, parent_widget) - 有parent_widget参数
        - Line 662: SetRole(ax::mojom::Role::kDialog) - Dialog角色
        - Line 104: kDefaultPaymentPopupWidth = 308 - 固定宽度
        
        popup不是顶层窗口，而是浏览器窗口内的Dialog元素！
        """
        try:
            print(f"\n{'='*60}")
            print(f"Searching for Express Checkout Popup Dialog...")
            print(f"{'='*60}")
            
            # 查找所有Chrome浏览器窗口
            class_condition = self.uia.CreatePropertyCondition(
                UIAutomationClient.UIA_ClassNamePropertyId,
                "Chrome_WidgetWin_1"
            )
            windows = self.root.FindAll(
                UIAutomationClient.TreeScope_Children,
                class_condition
            )
            
            print(f"Found {windows.Length} Chrome windows, searching for Dialog elements...")
            
            # 在每个Chrome窗口内搜索Dialog角色的元素
            for i in range(windows.Length):
                window = windows.GetElement(i)
                
                try:
                    name = window.CurrentName
                    # 只在Edge浏览器窗口中搜索
                    if 'edge' not in name.lower() and 'microsoft' not in name.lower():
                        continue
                    
                    print(f"\nSearching in browser: {name}")
                    
                    # 在窗口内搜索所有Dialog元素
                    dialog_condition = self.uia.CreatePropertyCondition(
                        UIAutomationClient.UIA_ControlTypePropertyId,
                        UIAutomationClient.UIA_PaneControlTypeId  # Dialog通常显示为Pane
                    )
                    
                    dialogs = window.FindAll(
                        UIAutomationClient.TreeScope_Descendants,
                        dialog_condition
                    )
                    
                    print(f"  Found {dialogs.Length} pane elements")
                    
                    # 检查每个Dialog
                    for j in range(dialogs.Length):
                        dialog = dialogs.GetElement(j)
                        
                        try:
                            rect = dialog.CurrentBoundingRectangle
                            width = rect.right - rect.left
                            height = rect.bottom - rect.top
                            
                            # 检查宽度是否匹配
                            if 300 <= width <= 320:
                                print(f"    Pane #{j+1}: {width}x{height}")
                                
                                # 检查是否有Express Checkout特征
                                if self._has_express_checkout_popup_features(dialog):
                                    print(f"\n{'='*60}")
                                    print(f"✅ Found Express Checkout Popup!")
                                    print(f"{'='*60}")
                                    
                                    # 尝试获取窗口句柄
                                    try:
                                        hwnd = dialog.CurrentNativeWindowHandle
                                    except:
                                        hwnd = 0
                                    
                                    return {
                                        'success': True,
                                        'hwnd': hwnd if hwnd else window.CurrentNativeWindowHandle,
                                        'bounds': {
                                            'x': rect.left,
                                            'y': rect.top,
                                            'width': width,
                                            'height': height
                                        },
                                        'name': dialog.CurrentName
                                    }
                        except Exception as e:
                            continue
                            
                except Exception as e:
                    print(f"  Error searching in window: {e}")
                    continue
            
            print(f"\n{'='*60}")
            print("❌ Express Checkout Popup not found")
            print("Make sure the popup is visible on screen")
            print(f"{'='*60}\n")
            return {'success': False, 'error': 'Popup not found in any browser window'}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_popup_element(self) -> Optional[Any]:
        """获取Popup窗口的UI元素"""
        result = self.find_autofill_popup()
        if not result.get('success'):
            return None
        
        hwnd = result['hwnd']
        try:
            # 从窗口句柄获取UI元素
            element = self.uia.ElementFromHandle(hwnd)
            return element
        except Exception as e:
            print(f"Error getting element from handle: {e}")
            return None
    
    def find_list_items(self, parent_element: Any) -> List[Any]:
        """查找列表项"""
        try:
            condition = self.uia.CreatePropertyCondition(
                UIAutomationClient.UIA_ControlTypePropertyId,
                UIAutomationClient.UIA_ListItemControlTypeId
            )
            
            items = parent_element.FindAll(
                UIAutomationClient.TreeScope_Descendants,
                condition
            )
            
            result = []
            for i in range(items.Length):
                result.append(items.GetElement(i))
            
            return result
        except Exception as e:
            print(f"Error finding list items: {e}")
            return []
    
    def find_buttons(self, parent_element: Any) -> List[Any]:
        """查找按钮"""
        try:
            condition = self.uia.CreatePropertyCondition(
                UIAutomationClient.UIA_ControlTypePropertyId,
                UIAutomationClient.UIA_ButtonControlTypeId
            )
            
            buttons = parent_element.FindAll(
                UIAutomationClient.TreeScope_Descendants,
                condition
            )
            
            result = []
            for i in range(buttons.Length):
                result.append(buttons.GetElement(i))
            
            return result
        except Exception as e:
            print(f"Error finding buttons: {e}")
            return []
    
    def invoke_element(self, element: Any) -> bool:
        """调用元素（点击）"""
        try:
            # 获取 Invoke Pattern
            invoke_pattern = element.GetCurrentPattern(
                UIAutomationClient.UIA_InvokePatternId
            )
            invoke = invoke_pattern.QueryInterface(UIAutomationClient.IUIAutomationInvokePattern)
            invoke.Invoke()
            return True
        except Exception as e:
            print(f"Error invoking element: {e}")
            return False
    
    def select_and_confirm(self, profile_index: int = 0, payment_index: int = 0) -> Dict[str, Any]:
        """
        选择地址/支付方式并确认
        
        Args:
            profile_index: 地址索引（默认0，选择第一个）
            payment_index: 支付方式索引（默认0）
        
        Returns:
            操作结果字典
        """
        try:
            popup = self.get_popup_element()
            if popup is None:
                return {'success': False, 'error': 'Popup not found'}
            
            # 1. 查找并选择地址
            list_items = self.find_list_items(popup)
            print(f"Found {len(list_items)} list items")
            
            if len(list_items) > profile_index:
                print(f"Selecting item at index {profile_index}")
                self.invoke_element(list_items[profile_index])
                time.sleep(0.3)  # 等待UI响应
            
            # 2. 查找并点击 Autofill 按钮
            # 根据 edge_express_checkout_view.cc line 2700: IDS_EDGE_EC_INLINE_AUTOFILL
            buttons = self.find_buttons(popup)
            print(f"Found {len(buttons)} buttons")
            
            autofill_button = None
            for button in buttons:
                try:
                    name = button.CurrentName
                    print(f"Button name: {name}")
                    if 'autofill' in name.lower():
                        autofill_button = button
                        print(f"Found Autofill button: {name}")
                        break
                except:
                    continue
            
            if autofill_button:
                print("Clicking Autofill button")
                self.invoke_element(autofill_button)
                return {'success': True}
            else:
                print("Warning: Autofill button not found, but selection may have succeeded")
                return {'success': True, 'warning': 'Autofill button not found'}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_popup_state(self) -> Dict[str, Any]:
        """
        获取 Popup 状态（用于 AI 分析）
        
        Returns:
            包含Popup状态的字典
        """
        try:
            popup = self.get_popup_element()
            if popup is None:
                return {'success': False, 'visible': False}
            
            # 获取列表项
            items = self.find_list_items(popup)
            addresses = []
            
            for item in items:
                try:
                    name = item.CurrentName
                    addresses.append(name)
                except:
                    addresses.append("(无法读取)")
            
            return {
                'success': True,
                'visible': True,
                'item_count': len(items),
                'items': addresses
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}


class UIARequestHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""
    
    uia_helper = UIAHelper()
    
    def do_GET(self):
        """处理GET请求"""
        if self.path == '/uia/get_popup_state':
            result = self.uia_helper.get_popup_state()
            self.send_json_response(result)
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        """处理POST请求"""
        if self.path == '/uia/find_popup':
            result = self.uia_helper.find_autofill_popup()
            self.send_json_response(result)
            
        elif self.path == '/uia/select_and_confirm':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            request_data = json.loads(post_data.decode('utf-8'))
            
            profile_index = request_data.get('profile_index', 0)
            payment_index = request_data.get('payment_index', 0)
            
            result = self.uia_helper.select_and_confirm(profile_index, payment_index)
            self.send_json_response(result)
        else:
            self.send_error(404, "Not Found")
    
    def send_json_response(self, data: Dict[str, Any]):
        """发送JSON响应"""
        try:
            response = json.dumps(data, ensure_ascii=False)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', len(response.encode('utf-8')))
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        except (ConnectionAbortedError, BrokenPipeError) as e:
            # 客户端断开连接，忽略错误
            print(f"Client disconnected: {e}")
        except Exception as e:
            print(f"Error sending response: {e}")
    
    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[{self.log_date_time_string()}] {format % args}")


def main():
    """启动UIA Helper服务器"""
    host = 'localhost'
    port = 3333
    
    server = HTTPServer((host, port), UIARequestHandler)
    
    print("=" * 60)
    print(f"UIA Helper 服务器已启动")
    print(f"监听地址: http://{host}:{port}")
    print("=" * 60)
    print("\n可用的API端点:")
    print("  GET  /uia/get_popup_state      - 获取Popup状态")
    print("  POST /uia/find_popup           - 查找Popup窗口")
    print("  POST /uia/select_and_confirm   - 选择并确认")
    print("\n按 Ctrl+C 停止服务器\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n服务器已停止")
        server.shutdown()


if __name__ == '__main__':
    main()