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
    
    def _check_element_for_popup_features(self, element: Any, all_text_content: list) -> bool:
        """
        检查一个元素是否有足够的Express Checkout特征字符串（>=3个匹配）。
        all_text_content 已经预先填充了按钮名称。
        """
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
                print(f"[UIA]   ✓ Found feature: '{feature}'")
        if len(matched_features) >= 3:
            print(f"[UIA]   ✅ Express Checkout Popup matched ({len(matched_features)} features)")
            return True
        # print(f"  ✗ Not enough features matched ({len(matched_features)}/3 required)")
        return False

    def _collect_text(self, element: Any) -> list[str]:
        """收集 element 下所有 Text 控件的 CurrentName。"""
        result = []
        try:
            cond = self.uia.CreatePropertyCondition(
                UIAutomationClient.UIA_ControlTypePropertyId,
                UIAutomationClient.UIA_TextControlTypeId,
            )
            texts = element.FindAll(UIAutomationClient.TreeScope_Descendants, cond)
            for i in range(texts.Length):
                try:
                    name = texts.GetElement(i).CurrentName
                    if name and name.strip():
                        result.append(name)
                except:
                    continue
        except:
            pass
        return result

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
                    # vprint(f"    Button {i}: '{name}'")
            except:
                continue
        return names, buttons

    def _has_express_checkout_popup_features(self, window: Any, verbose: bool = True) -> bool | tuple[bool, Any]:
        """
        检查 UIA Pane 是否是 Edge Express Checkout Popup。

        UIA 树结构（edge_express_checkout_view.cc）：
            EdgeExpressCheckoutView (root pane)
            ├── InlineSplitButton  → "Autofill" button
            └── EdgeExpressCheckoutBodyView (body pane)
                ├── "Contact info" Text
                ├── "Payment methods" Text
                └── profile option Buttons

        FindAll(TreeScope_Descendants) 先枚举 body pane 再枚举 root pane，
        因此分两种命中情况：
          - body pane：有 body features 但无 Autofill → walk to parent 确认
          - root pane：body features + Autofill 都在当前节点

        Returns: False | True | (True, parent_element)
        """
        vprint = print if verbose else lambda *_: None

        # 子 pane 特征：text 中有 Contact info 和 Payment methods
        _BODY_FEATURES = {'Contact info', 'Payment methods'}
        # 父 pane 额外特征：button name 中有 Autofill
        _ROOT_FEATURE = 'Autofill'

        def _log_matched() -> None:
            for f in sorted(_BODY_FEATURES | {_ROOT_FEATURE}):
                vprint(f"[UIA]   ✓ Feature: '{f}'")
            vprint(f"[UIA]   ✅ Express Checkout Popup matched")

        try:
            btn_names, buttons = self._collect_buttons_text(window, verbose=False)
            text_content = self._collect_text(window)
            all_content = text_content + btn_names

            body_matched = _BODY_FEATURES.issubset({f for f in _BODY_FEATURES if any(f in t for t in all_content)})
            if not body_matched:
                return False

            # 子 pane：有 body features，再查父节点是否有 Autofill
            if not any(_ROOT_FEATURE in t for t in all_content):
                vprint(f"[UIA]   Body pane matched, walking up to parent for Autofill button...")
                try:
                    tree_walker = self.uia.CreateTreeWalker(self.uia.CreateTrueCondition())
                    parent = tree_walker.GetParentElement(window)
                    if parent:
                        parent_btn_names, _ = self._collect_buttons_text(parent, verbose=False)
                        if any(_ROOT_FEATURE in t for t in parent_btn_names):
                            _log_matched()
                            return (True, parent)
                except Exception as e:
                    vprint(f"[UIA]   ❌ Error walking to parent: {e}")
                return False

            # 根 pane：body features + Autofill 都在当前 pane
            _log_matched()
            return True

        except Exception as e:
            vprint(f"[UIA]   ❌ Error checking features: {e}")
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
            vprint(f"[UIA] Searching for Express Checkout Popup...")

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
                    
                    # vprint(f"[UIA]   Searching in: {name}")
                    
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
                            # width = rect.right - rect.left
                            # height = rect.bottom - rect.top
                            
                            # 检查宽度是否匹配
                            # vprint(f"shit!!!!!    Pane #{j+1}: {width}x{height}")
                            # if 300 <= width <= 320:
                            # vprint(f"    Pane #{j+1}: {width}x{height} ✓ in range")

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

                                print(f"[UIA]   ✅✅✅ Found Express Checkout Popup!")

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
            
            print("[UIA]   ❌❌ Express Checkout Popup not found")
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

            # vprint(f"[find_option_buttons] Found {buttons.Length} total buttons")

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
        """调用元素（点击）。优先 InvokePattern，fallback 到 LegacyIAccessiblePattern.DoDefaultAction。"""
        try:
            invoke_pattern = element.GetCurrentPattern(UIAutomationClient.UIA_InvokePatternId)
            if invoke_pattern:
                invoke = invoke_pattern.QueryInterface(UIAutomationClient.IUIAutomationInvokePattern)
                invoke.Invoke()
                return True
        except Exception:
            pass
        try:
            legacy = element.GetCurrentPattern(UIAutomationClient.UIA_LegacyIAccessiblePatternId)
            if legacy:
                acc = legacy.QueryInterface(UIAutomationClient.IUIAutomationLegacyIAccessiblePattern)
                acc.DoDefaultAction()
                return True
        except Exception as e:
            print(f"[UIA] Error invoking element: {e}")
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
            # print(f"Found {len(option_buttons)} option buttons")

            if len(option_buttons) > profile_index:
                print(f"Selecting option button at index {profile_index}")
                self.invoke_element(option_buttons[profile_index])
                time.sleep(0.3)  # 等待UI响应

            # 2. 查找并点击 Autofill 按钮
            all_buttons = self.find_buttons(popup)
            # print(f"Found {len(all_buttons)} total buttons")

            autofill_button = None
            for button in all_buttons:
                try:
                    name = button.CurrentName
                    if name and name.strip() == 'Autofill':  # 精确匹配 "Autofill"
                        autofill_button = button
                        print(f"[UIA] Found Autofill button")
                        break
                except:
                    continue

            if autofill_button:
                print("[UIA] Clicking Autofill button")
                self.invoke_element(autofill_button)
                return {'success': True}
            else:
                print("[UIA] Warning: Autofill button not found, but selection may have succeeded")
                return {'success': True, 'warning': 'Autofill button not found'}

        except Exception as e:
            return {'success': False, 'error': str(e)}