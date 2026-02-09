# 反爬虫问题 - User Data Directory 污染发现

## 🔍 问题发现

### 现象
- 使用旧的 user data directory 时遇到 Akamai 429 错误
- 切换到**干净的临时目录**后问题消失

### 根本原因

**User Data Directory 被"污染"**：

```
旧目录: C:\Users\jianqiaojia\xpay-edge-starter\default-profile
├─ Cookies 已被 Nike/Akamai 标记
├─ LocalStorage 包含机器人检测数据
├─ IndexedDB 存储了异常行为记录
├─ Cache 中有可疑的请求模式
└─ 结果：一启动就被识别为机器人
```

**为什么干净目录有效**：
```
新目录: Q:\tmp2
├─ 没有任何历史记录
├─ 像一个全新的用户
├─ Nike/Akamai 看不到之前的"犯罪记录"
└─ 成功率大幅提升
```

## ✅ 已验证的解决方案

**使用 Edge Stable + 干净的临时目录**：

```python
# test_agent/config.py

EDGE_STABLE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
EDGE_USER_DATA_DIR = 'Q:\\tmp2'  # 干净的临时目录
```

**效果**：
- ✅ 不再触发 Akamai 429
- ✅ 可以正常访问 Nike 页面
- ✅ 无需商业代理即可测试

## 🔧 动态解决方案（推荐实现）

### 方案1：自动创建临时目录

```python
# test_agent/config.py

import tempfile
import uuid
from pathlib import Path

class TestAgentConfig:
    def __init__(self):
        # ... 其他配置 ...

        # 动态创建干净的临时目录
        self._temp_user_data_dir = None

    def get_clean_user_data_dir(self, force_new: bool = False) -> str:
        """
        获取干净的 User Data Directory

        Args:
            force_new: 是否强制创建新目录（遇到反爬虫时使用）

        Returns:
            临时目录路径
        """
        if force_new or not self._temp_user_data_dir:
            # 创建唯一的临时目录
            base_dir = Path(tempfile.gettempdir()) / "browser_use_clean"
            base_dir.mkdir(exist_ok=True)

            # 使用UUID确保唯一性
            session_id = uuid.uuid4().hex[:8]
            self._temp_user_data_dir = str(base_dir / f"session_{session_id}")

            print(f"[Config] Using clean user data dir: {self._temp_user_data_dir}")

        return self._temp_user_data_dir

    def cleanup_temp_dir(self):
        """清理临时目录（可选）"""
        if self._temp_user_data_dir and Path(self._temp_user_data_dir).exists():
            import shutil
            shutil.rmtree(self._temp_user_data_dir, ignore_errors=True)
            print(f"[Config] Cleaned up temp dir: {self._temp_user_data_dir}")
```

**使用方式**：

```python
# 正常测试
browser_config = config.get_browser_profile_config()
browser_config['user_data_dir'] = config.user_data_dir  # 使用默认目录

# 遇到反爬虫时
if detected_anti_bot:
    browser_config['user_data_dir'] = config.get_clean_user_data_dir(force_new=True)
    print("[AntiBot] Switched to clean profile to bypass detection")
```

### 方案2：检测429自动切换

```python
# test_agent/anti_bot_handler.py

class AntiBotHandler:
    """反爬虫检测和自动处理"""

    @staticmethod
    def is_anti_bot_error(history) -> bool:
        """检测是否遇到反爬虫"""
        # 检查history中的错误
        for step in history.history:
            if hasattr(step, 'error') and step.error:
                error_msg = str(step.error).lower()
                if any(keyword in error_msg for keyword in [
                    '429', 'too many requests',
                    'akamai', 'bot manager',
                    '4db3a115',  # Nike特定错误码
                    'access denied'
                ]):
                    return True
        return False

    @staticmethod
    async def retry_with_clean_profile(agent, task, config, max_retries=2):
        """遇到反爬虫时自动切换干净profile重试"""
        for attempt in range(max_retries + 1):
            # 运行测试
            history = await agent.run(task)

            # 检查是否遇到反爬虫
            if not AntiBotHandler.is_anti_bot_error(history):
                return history  # 成功

            # 遇到反爬虫，切换profile重试
            if attempt < max_retries:
                print(f"\n[AntiBot] Detected anti-bot (429/Akamai), retrying with clean profile...")

                # 创建新的干净profile
                clean_dir = config.get_clean_user_data_dir(force_new=True)

                # 重新创建browser
                browser_config = config.get_browser_profile_config()
                browser_config['user_data_dir'] = clean_dir
                browser = BrowserProfile(**browser_config)

                # 重新创建agent
                agent = Agent(
                    task=task,
                    llm=agent.llm,
                    browser_profile=browser,
                )

        return history  # 所有重试都失败
```

**集成到test runner**：

```python
# test_runner_claude.py

from test_agent.anti_bot_handler import AntiBotHandler

async def run_test_case_with_anti_bot(llm, test, config):
    """带反爬虫自动处理的测试运行"""

    # 第一次尝试：使用默认profile
    browser_config = config.get_browser_profile_config()
    browser = BrowserProfile(**browser_config)
    agent = Agent(task=task, llm=llm, browser_profile=browser)

    # 运行并自动处理反爬虫
    handler = AntiBotHandler()
    history = await handler.retry_with_clean_profile(agent, task, config, max_retries=2)

    return history
```

### 方案3：Profile 池管理（最完善）

```python
# test_agent/profile_pool.py

import tempfile
from pathlib import Path
from typing import List
import uuid

class ProfilePool:
    """
    浏览器Profile池管理

    用途：
    1. 管理多个干净的profile
    2. 轮换使用避免被关联
    3. 自动清理过期profile
    """

    def __init__(self, pool_size: int = 5):
        self.pool_size = pool_size
        self.profiles: List[str] = []
        self.current_index = 0
        self.base_dir = Path(tempfile.gettempdir()) / "browser_use_profiles"
        self.base_dir.mkdir(exist_ok=True)

    def get_next_profile(self) -> str:
        """获取下一个干净的profile"""
        if not self.profiles or self.current_index >= len(self.profiles):
            # 创建新的profile
            session_id = uuid.uuid4().hex[:8]
            profile_path = str(self.base_dir / f"profile_{session_id}")
            self.profiles.append(profile_path)
            self.current_index = len(self.profiles) - 1

        profile = self.profiles[self.current_index]
        self.current_index = (self.current_index + 1) % min(len(self.profiles), self.pool_size)

        print(f"[ProfilePool] Using profile: {Path(profile).name}")
        return profile

    def cleanup_all(self):
        """清理所有profile"""
        import shutil
        for profile in self.profiles:
            if Path(profile).exists():
                shutil.rmtree(profile, ignore_errors=True)
        print(f"[ProfilePool] Cleaned up {len(self.profiles)} profiles")

# 使用示例
profile_pool = ProfilePool(pool_size=5)

# 每次测试用不同的profile
for test in tests:
    clean_profile = profile_pool.get_next_profile()
    browser_config['user_data_dir'] = clean_profile
    # ... 运行测试
```

## 📊 对比分析

| 方案 | 实现难度 | 自动化程度 | 推荐度 |
|------|---------|-----------|--------|
| 手动指定临时目录 | 低 | 低 | ⭐⭐⭐ |
| 自动创建临时目录 | 中 | 中 | ⭐⭐⭐⭐ |
| 检测429自动切换 | 中 | 高 | ⭐⭐⭐⭐⭐ |
| Profile池管理 | 高 | 高 | ⭐⭐⭐⭐⭐ |

## 💡 立即可用的配置

**临时方案（最简单）**：

```python
# test_agent/config.py
EDGE_USER_DATA_DIR = 'Q:\\tmp2'  # 或任何干净的目录
```

**长期方案（推荐实现）**：

实现"检测429自动切换"方案，在遇到反爬虫时自动创建新的干净profile重试。

## 🎓 经验总结

**关键发现**：
1. ✅ **User Data Directory 污染是主要问题**，不是IP问题
2. ✅ **干净的profile** 比商业代理更有效（至少对Nike来说）
3. ✅ **动态切换profile** 可以作为反爬虫的第一道防线

**建议优先级**：
1. 立即：使用干净的临时目录（已验证有效）
2. 短期：实现"检测429自动切换"
3. 长期：实现完整的Profile池管理

**这比商业代理更好的地方**：
- ✅ 完全免费
- ✅ 实施简单
- ✅ 对Nike有效（已验证）
- ⚠️ 但可能不适用于所有网站

所以之前说的商业代理方案可以作为**备选方案**，当干净profile也不行时再考虑。
