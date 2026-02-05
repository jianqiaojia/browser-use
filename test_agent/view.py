"""Data models for Test Agent - 兼容新版 browser-use v0.11.8

这个文件基本不需要修改，只需要更新导入路径。
"""
from typing import Optional, Any, Dict, List
from pydantic import BaseModel
from json import JSONEncoder

# 新版导入路径
from browser_use.agent.views import ActionResult
from browser_use.dom.views import DOMInteractedElement  # 新版：DOMHistoryElement → DOMInteractedElement

class TestCaseReplayAction(BaseModel):
    """测试用例重放动作
    
    迁移说明：element 类型从 DOMHistoryElement 改为 DOMInteractedElement
    """
    action: dict[str, Any]
    result: ActionResult
    element: Optional[DOMInteractedElement] = None  # 新版类型
    stepIndex: int
    actionIndex: int

    def print(self):
        print(f'>> 🟢🟢 Action {self.actionIndex}: {self.action.items()}')
        print(f'>> 🟡🟡 Action Result {self.result}')
        print(f'>> 🔴🔴 Action Element {self.element}')

class TestCaseReplayStep(BaseModel):
    """测试用例重放步骤"""
    stepIndex: int
    evaluation_previous_goal: str
    memory: str
    next_goal: str
    replayActions: list[TestCaseReplayAction] = []
    
    def add_action(self, action: TestCaseReplayAction):
        self.replayActions.append(action)
    
    def print(self):
        print(f'🔥🔥 Step {self.stepIndex}:')
        print(f'🍉🍉 Evaluation Previous Goal: {self.evaluation_previous_goal}')
        print(f'🍉🍉 Memory: {self.memory}')
        print(f'🍉🍉 Next Goal: {self.next_goal}')
        for action in self.replayActions:
            action.print()

class TestStep(BaseModel):
    """单个测试步骤"""
    step_name: str
    step_description: str
    expected_result: str
    
class TestStepEncoder(JSONEncoder):
    """测试步骤的 JSON 编码器"""
    def default(self, obj):
        if isinstance(obj, TestStep):
            return {
                'step_name': obj.step_name,
                'step_description': obj.step_description,
                'expected_result': obj.expected_result
            }
        return super().default(obj)
        
class TestFilter(BaseModel):
    """测试过滤器"""
    site_type: str
    priority: int
    feature: str

class PredefinedFunctionCall(BaseModel):
    """预定义函数调用"""
    function: str  # Name of the function to call
    parameters: Optional[Dict[str, Any]] = None  # Parameters for the function

class TestCase(BaseModel):
    """测试用例"""
    test_case_name: str
    test_case_description: str
    filter: TestFilter
    steps: list[TestStep] = []
    replay_steps: Optional[list[TestCaseReplayStep]] = None
    disable_features: Optional[str] = None
    enable_features: Optional[str] = None
    prerun_calls: Optional[List[PredefinedFunctionCall]] = None
    postrun_calls: Optional[List[PredefinedFunctionCall]] = None

class ECTest(BaseModel):
    """EC 测试集合"""
    domain: Optional[str] = None
    test_cases: list[TestCase] = []

class SetSessionStorageAction(BaseModel):
    """设置 SessionStorage 的参数模型"""
    key: str
    value: str
