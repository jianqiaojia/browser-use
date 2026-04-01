"""Data models for Test Agent."""
from typing import Optional, Any, Dict, List
from pydantic import BaseModel


class TestCase(BaseModel):
    """单个测试用例。

    preconditions:  跑测试前需要人工满足的环境条件。仅供参考，不进 task prompt。
    instructions:   LLM 必须遵守的约束（登录状态、验证目标等）。进入 task prompt。
    guidance:       UI 操作参考建议，LLM 根据实际情况判断。进入 task prompt。
    """
    name: str
    preconditions: Optional[str] = None
    instructions: Optional[str | list[str]] = None
    guidance: Optional[str | list[str]] = None


class SiteTest(BaseModel):
    """单个 site 的测试集合。

    domain:        测试目标站点的 URL（e.g. https://www.nike.com）。
    site_guidance: 适用于该 site 所有 test case 的共享 UI 操作参考。
    """
    domain: Optional[str] = None
    site_guidance: Optional[str | list[str]] = None
    test_cases: list[TestCase] = []


class SetSessionStorageAction(BaseModel):
    """设置 SessionStorage 的参数模型"""
    key: str
    value: str
