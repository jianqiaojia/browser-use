"""
UIA Helper - Python实现
用于通过Windows UI Automation API操作Edge浏览器的Native UI组件
"""

import time
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
    
    def _check_element_for_popup_features(self, element: Any, all_text_content: list, verbose: bool = True) -> bool:
        """
        检查一个元素是否有足够的Express Checkout特征字符串（>=3个匹配）。
        all_text_content 已经预先填充了按钮名称。
        """
        vprint = print if verbose else lambda *_: None
        feature_strings = {
            'Contact info',      # IDS_EDGE_EC_INLINE_CONTACT_INFO
            'Payment methods',   # IDS_EDGE_WALLET_PAYMENT_METHODS
            'Autofill',         # IDS_EDGE_EC_INLINE_AUTOFILL
            'Saved info',       # IDS_EDGE_EC_INLINE_SAVED_INFO
            'Saved cards',      # IDS_EDGE_EC_INLINE_SAVED_CARDS
            'Manage',           # IDS_EDGE_EC_INLINE_Manage
        }
        matched_features = []
        for feature in feature_strings:
            if any(feature in text for text in all_text_content):
                matched_features.append(feature)
                vprint(f"  ✓ Found feature: '{feature}'")
        if len(matched_features) >= 3:
            vprint(f"  ✅ Found Express Checkout Popup! (matched {len(matched_features)} features)")
            return True
        vprint(f"  ✗ Not enough features matched ({len(matched_features)}/3 required)")
        return False

    def _collect_buttons_text(self, element: Any, verbose: bool = True) -> tuple[list, Any]:
        """
        在 element 下查找所有 Button，返回 (names_list, button_collection)。
        """
        vprint = print if verbose else lambda *_: None
        button_condition = self.uia.CreatePropertyCondition(
            UIAutomationClient.UIA_ControlTypePropertyId,
            UIAutomationClient.UIA_ButtonControlTypeId
        )
        buttons = element.FindAll(UIAutomationClient.TreeScope_Descendants, button_condition)
        names = []
        for i in range(buttons.Length):
            try:
                name = buttons.GetElement(i).CurrentName
                if name and name.strip():
                    names.append(name)
                    vprint(f"    Button {i}: '{name}'")
            except:
                continue
        return names, buttons

    def _has_express_checkout_popup_features(self, window: Any, verbose: bool = True) -> bool | tuple[bool, Any]:
        """
        检查窗口是否是Express Checkout Popup。
        - 如果 window 本身有 >=4 个按钮且特征匹配 → 返回 True
        - 如果 window 只有 2 个按钮（body sub-pane），向上走到父元素再检查：
          因为实际 widget 宽度因 shadow/border insets 比 308px 略宽，
          content sub-pane 是 308px，但父 widget pane 宽度 > 320px，不会进入外层循环。
          所以：找到 308px 的 body pane → 爬到父元素 → 父元素包含全部 4 个按钮。
          此时返回 (True, parent_element) 以便调用方使用正确的元素句柄。
        """
        vprint = print if verbose else lambda *_: None
        try:
            rect = window.CurrentBoundingRectangle
            width = rect.right - rect.left

            if not (300 <= width <= 320):
                vprint(f"  ✗ Width mismatch: {width}px (expected ~308px)")
                return False

            vprint(f"  ✓ Width check passed: {width}px")

            all_text_content = []
            try:
                text_condition = self.uia.CreatePropertyCondition(
                    UIAutomationClient.UIA_ControlTypePropertyId,
                    UIAutomationClient.UIA_TextControlTypeId
                )
                texts = window.FindAll(UIAutomationClient.TreeScope_Descendants, text_condition)
                for i in range(texts.Length):
                    try:
                        name = texts.GetElement(i).CurrentName
                        if name and name.strip():
                            all_text_content.append(name)
                    except:
                        continue
            except Exception as e:
                print(f"  ✗ Error getting texts: {e}")

            try:
                vprint(f"  Collecting buttons in current pane...")
                btn_names, buttons = self._collect_buttons_text(window, verbose=verbose)
                all_text_content.extend(btn_names)
                vprint(f"  Found {buttons.Length} buttons in pane")

                if buttons.Length >= 4:
                    vprint(f"  Found {len(all_text_content)} text/button elements")
                    return self._check_element_for_popup_features(window, all_text_content, verbose=verbose)

                vprint(f"  Only {buttons.Length} buttons in pane, walking up to parent to find full popup...")
                try:
                    tree_walker = self.uia.CreateTreeWalker(self.uia.CreateTrueCondition())
                    parent = tree_walker.GetParentElement(window)
                    if parent:
                        parent_rect = parent.CurrentBoundingRectangle
                        parent_width = parent_rect.right - parent_rect.left
                        parent_height = parent_rect.bottom - parent_rect.top
                        vprint(f"  Parent element: {parent_width}x{parent_height}")

                        parent_btn_names, parent_buttons = self._collect_buttons_text(parent, verbose=verbose)
                        vprint(f"  Found {parent_buttons.Length} buttons in parent")
                        parent_text_content = list(all_text_content) + parent_btn_names

                        if parent_buttons.Length >= 4:
                            if self._check_element_for_popup_features(parent, parent_text_content, verbose=verbose):
                                return (True, parent)
                        else:
                            vprint(f"  Parent also has < 4 buttons ({parent_buttons.Length}), giving up")
                except Exception as e:
                    print(f"  Error walking to parent: {e}")

            except Exception as e:
                print(f"  ✗ Error getting buttons: {e}")

            return False

        except Exception as e:
            print(f"  ✗ Error checking features: {e}")
            return False
    
    def find_autofill_popup(self, verbose: bool = True) -> Optional[Dict[str, Any]]:
        """
        查找 Express Checkout Popup
        基于C++代码edge_express_checkout_view.cc:
        - Line 604: PopupBaseView(controller, parent_widget) - 有parent_widget参数
        - Line 662: SetRole(ax::mojom::Role::kDialog) - Dialog角色
        - Line 104: kDefaultPaymentPopupWidth = 308 - 固定宽度
        
        popup不是顶层窗口，而是浏览器窗口内的Dialog元素！
        """
        try:
            vprint = print if verbose else lambda *_: None
            vprint(f"\n{'='*60}")
            vprint(f"Searching for Express Checkout Popup Dialog...")
            vprint(f"{'='*60}")

            # 查找所有Chrome浏览器窗口
            class_condition = self.uia.CreatePropertyCondition(
                UIAutomationClient.UIA_ClassNamePropertyId,
                "Chrome_WidgetWin_1"
            )
            windows = self.root.FindAll(
                UIAutomationClient.TreeScope_Children,
                class_condition
            )
            
            # 在每个Chrome窗口内搜索Dialog角色的元素
            for i in range(windows.Length):
                window = windows.GetElement(i)
                
                try:
                    name = window.CurrentName
                    # 只在Edge浏览器窗口中搜索
                    if 'edge' not in name.lower() and 'microsoft' not in name.lower():
                        continue
                    
                    vprint(f"\nSearching in browser: {name}")
                    
                    # 在窗口内搜索所有Dialog元素
                    dialog_condition = self.uia.CreatePropertyCondition(
                        UIAutomationClient.UIA_ControlTypePropertyId,
                        UIAutomationClient.UIA_PaneControlTypeId  # Dialog通常显示为Pane
                    )
                    
                    dialogs = window.FindAll(
                        UIAutomationClient.TreeScope_Descendants,
                        dialog_condition
                    )
                    
                    # 检查每个Dialog
                    for j in range(dialogs.Length):
                        dialog = dialogs.GetElement(j)
                        
                        try:
                            rect = dialog.CurrentBoundingRectangle
                            width = rect.right - rect.left
                            height = rect.bottom - rect.top
                            
                            # 检查宽度是否匹配
                            if 300 <= width <= 320:
                                vprint(f"    Pane #{j+1}: {width}x{height}")

                                # 检查是否有Express Checkout特征
                                result = self._has_express_checkout_popup_features(dialog, verbose=verbose)
                                # result 可能是 False / True / (True, parent_element)
                                if result:
                                    # 如果返回 (True, parent)，使用父元素作为句柄来源
                                    if isinstance(result, tuple):
                                        _, popup_element = result
                                        popup_rect = popup_element.CurrentBoundingRectangle
                                    else:
                                        popup_element = dialog
                                        popup_rect = rect

                                    vprint(f"\n{'='*60}")
                                    vprint(f"✅✅✅ Found Express Checkout Popup!")
                                    vprint(f"{'='*60}")

                                    # 尝试获取窗口句柄
                                    try:
                                        hwnd = popup_element.CurrentNativeWindowHandle
                                    except:
                                        hwnd = 0

                                    return {
                                        'success': True,
                                        'element': popup_element,
                                        'hwnd': hwnd if hwnd else window.CurrentNativeWindowHandle,
                                        'bounds': {
                                            'x': popup_rect.left,
                                            'y': popup_rect.top,
                                            'width': popup_rect.right - popup_rect.left,
                                            'height': popup_rect.bottom - popup_rect.top
                                        },
                                        'name': popup_element.CurrentName
                                    }
                        except Exception as e:
                            continue
                            
                except Exception as e:
                    print(f"  Error searching in window: {e}")
                    continue
            
            vprint(f"\n{'='*60}")
            vprint("❌ Express Checkout Popup not found")
            return {'success': False, 'error': 'Popup not found in any browser window'}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_popup_element(self, verbose: bool = True) -> Optional[Any]:
        """获取Popup窗口的UI元素"""
        vprint = print if verbose else lambda *_: None
        vprint(f"[get_popup_element] Starting...")
        result = self.find_autofill_popup(verbose=verbose)
        if result is None or not result.get('success'):
            error_msg = result.get('error', 'Unknown') if result else 'find_autofill_popup returned None'
            vprint(f"[get_popup_element] find_autofill_popup failed: {error_msg}")
            return None

        # 优先使用 find_autofill_popup 已解析好的 element（含父元素场景）
        if 'element' in result and result['element'] is not None:
            vprint(f"[get_popup_element] Using element from find_autofill_popup result")
            return result['element']

        hwnd = result['hwnd']
        vprint(f"[get_popup_element] Got hwnd: {hwnd}")
        try:
            element = self.uia.ElementFromHandle(hwnd)
            vprint(f"[get_popup_element] ElementFromHandle succeeded, returning element")
            return element
        except Exception as e:
            print(f"[get_popup_element] Error getting element from handle: {e}")
            import traceback
            traceback.print_exc()
            return None

    def find_option_buttons(self, parent_element: Any, verbose: bool = True) -> List[Any]:
        """
        查找 autofill 选项按钮

        在 Edge autofill popup 中，用户信息选项（Contact info / Payment methods）
        是 Button 类型，不是 ListItem 类型
        """
        try:
            vprint = print if verbose else lambda *_: None
            vprint(f"[find_option_buttons] Searching for option buttons...")

            # 查找所有 Button 类型的元素
            condition = self.uia.CreatePropertyCondition(
                UIAutomationClient.UIA_ControlTypePropertyId,
                UIAutomationClient.UIA_ButtonControlTypeId
            )

            buttons = parent_element.FindAll(
                UIAutomationClient.TreeScope_Descendants,
                condition
            )

            vprint(f"[find_option_buttons] Found {buttons.Length} total buttons")

            # 过滤出真正的选项按钮（排除 "Autofill", "More actions" 等操作按钮）
            options = []
            for i in range(buttons.Length):
                button = buttons.GetElement(i)
                try:
                    name = button.CurrentName

                    # 选项按钮的特征：name 很长，包含 "Contact info" 或 "Payment methods"
                    if name and len(name) > 50:
                        if 'Contact info' in name or 'Payment methods' in name:
                            vprint(f"[find_option_buttons] Option {len(options)}: '{name[:80]}...'")
                            options.append(button)
                except Exception as e:
                    vprint(f"[find_option_buttons] Error reading button {i}: {e}")
                    continue

            vprint(f"[find_option_buttons] Returning {len(options)} option buttons")
            return options

        except Exception as e:
            print(f"[find_option_buttons] Exception: {e}")
            import traceback
            traceback.print_exc()
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
    
    def get_popup_profile_names(self, verbose: bool = True) -> Dict[str, Any]:
        """
        获取 autofill 弹窗中所有 profile 选项的名称列表。
        用于验证某个 profile 是否被过滤掉（不出现在弹窗中）。

        Returns:
            {'success': True, 'profiles': ['Ming Peng ...', ...]} 或 {'success': False, 'error': ...}
        """
        vprint = print if verbose else lambda *_: None
        try:
            popup = self.get_popup_element(verbose=False)
            if popup is None:
                return {'success': False, 'error': 'Popup not found'}

            option_buttons = self.find_option_buttons(popup, verbose=False)
            profiles = []
            for btn in option_buttons:
                try:
                    name = btn.CurrentName
                    if name and 'Contact info' in name:
                        profiles.append(name)
                        vprint(f"  Profile: '{name[:100]}'")
                except Exception as e:
                    print(f"  Error reading profile name: {e}")

            vprint(f"[get_popup_profile_names] Found {len(profiles)} profiles")
            return {'success': True, 'profiles': profiles}

        except Exception as e:
            return {'success': False, 'error': str(e)}

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
            popup = self.get_popup_element(verbose=False)
            if popup is None:
                return {'success': False, 'error': 'Popup not found'}

            # 1. 查找选项按钮（使用新的 find_option_buttons）
            option_buttons = self.find_option_buttons(popup, verbose=False)
            print(f"Found {len(option_buttons)} option buttons")

            if len(option_buttons) > profile_index:
                print(f"Selecting option button at index {profile_index}")
                self.invoke_element(option_buttons[profile_index])
                time.sleep(0.3)  # 等待UI响应

            # 2. 查找并点击 Autofill 按钮
            all_buttons = self.find_buttons(popup)
            print(f"Found {len(all_buttons)} total buttons")

            autofill_button = None
            for button in all_buttons:
                try:
                    name = button.CurrentName
                    if name and name.strip() == 'Autofill':  # 精确匹配 "Autofill"
                        autofill_button = button
                        print(f"Found Autofill button")
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