"""
Configuration management for Test Agent runners - MIGRATED to browser-use v0.11.8

This module provides centralized configuration for:
1. Browser settings
2. Test execution parameters
3. Azure OpenAI configurations
4. Agent behavior settings
5. Common file paths and directories

变更说明：
- 配置结构保持不变
- 仅更新注释以反映新版 API
"""

from pathlib import Path
from typing import Final, Dict, List, Any, Optional
from test_agent.Claude.integration.free_proxy_pool import ProxyPool, ProxyServer

# Import for browser proxy settings
from browser_use.browser.profile import ProxySettings

# Directory Configuration
BASE_DIR: Final[Path] = Path("test_agent")
TEST_CASE_DIR: Final[Path] = BASE_DIR / "test_case"

# Browser Configuration
EDGE_CANARY_PATH: Final[str] = 'C:\\Users\\jianqiaojia\\AppData\\Local\\Microsoft\\Edge SxS\\Application\\msedge.exe'
EDGE_STABLE_PATH: Final[str] = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
EDGE_USER_DATA_DIR: Final[str] = 'C:\\Users\\jianqiaojia\\xpay-edge-starter\\default-profile'
EDGE_STABLE_USER_DATA_DIR: Final[str] = 'Q:\\tmp2'
EDGE_LOG_FILE_PATH: Final[str] = 'C:\\Users\\jianqiaojia\\xpay-edge-starter\\default-profile\\chrome_debug.log'
EDGE_STABLE_LOG_FILE_PATH: Final[str] = 'Q:\\tmp2\\chrome_debug.log'
DEFAULT_PROFILE: Final[str] = 'Profile 2'
WALLET_PANE_URL: Final[str] = 'edge://wallet-drawer/'
ENABLE_FEATURES: Final[str] = ''
DISABLE_FEATURES: Final[str] = ''

# Agent Configuration
MAX_ACTIONS_PER_STEP: Final[int] = 5  # 新版推荐值
MAX_STEPS: Final[int] = 50  # 增加以确保有足够步骤完成所有任务（原 20 步不够）
VISION_ENABLED: Final[bool] = False

# Test Filter Configuration
DEFAULT_SITE_TYPE: Final[str] = "all"
DEFAULT_PRIORITY: Final[int] = 1
DEFAULT_FEATURE: Final[str] = "DID"
DEFAULT_RESULT_FOLDER: Final[str] = 'test_results'

# Azure OpenAI Configuration (环境变量或直接设置)
import os
AZURE_OPENAI_ENDPOINT: Final[str] = os.getenv('AZURE_OPENAI_ENDPOINT', 'https://xpay-mobius.openai.azure.com/')
AZURE_OPENAI_API_KEY: Final[str] = os.getenv('OPENAI_API_KEY', 'your-api-key')
AZURE_OPENAI_DEPLOYMENT_NAME: Final[str] = 'gpt-4o'
AZURE_OPENAI_API_VERSION: Final[str] = '2024-05-01-preview'

class TestAgentConfig:
    """Configuration class for managing test agent settings."""
    
    def __init__(self):
        """Initialize configuration with default values."""
        # Browser settings
        self.edge_path = EDGE_STABLE_PATH
        self.user_data_dir = EDGE_STABLE_USER_DATA_DIR
        self.log_file_path = EDGE_STABLE_LOG_FILE_PATH
        self.profile = DEFAULT_PROFILE
        self.wallet_pane_url = WALLET_PANE_URL
        self.enable_features = ENABLE_FEATURES
        self.disable_features = DISABLE_FEATURES
        
        # Agent settings
        self.max_actions_per_step = MAX_ACTIONS_PER_STEP
        self.max_steps = MAX_STEPS
        self.vision_enabled = VISION_ENABLED
        
        # Test settings
        self.default_site_type = DEFAULT_SITE_TYPE
        self.default_priority = DEFAULT_PRIORITY
        self.default_feature = DEFAULT_FEATURE
        self.test_result_folder = DEFAULT_RESULT_FOLDER
        
        # Azure OpenAI settings (兼容旧版配置方式)
        self.AZURE_OPENAI_ENDPOINT = AZURE_OPENAI_ENDPOINT
        self.AZURE_OPENAI_API_KEY = AZURE_OPENAI_API_KEY
        self.AZURE_OPENAI_DEPLOYMENT_NAME = AZURE_OPENAI_DEPLOYMENT_NAME
        self.AZURE_OPENAI_API_VERSION = AZURE_OPENAI_API_VERSION
        self.HEADLESS = False
        self.CHROME_ARGS = ['--disable-blink-features=AutomationControlled']

        # Proxy settings
        self.use_proxy = False
        self.proxy_pool: Optional[ProxyPool] = None
        self._current_proxy: Optional[ProxyServer] = None
        
    def get_browser_profile_config(self) -> Dict[str, Any]:
        """Get browser profile configuration dictionary.

        新版：返回 BrowserProfile 所需的配置
        """
        config = {
            'executable_path': self.edge_path,  # 新版使用 executable_path
            'user_data_dir': self.user_data_dir,  # BrowserProfile 直接接受此参数
            'profile_directory': self.profile,  # 新版使用 profile_directory
            'args': [  # 新版使用 args 而不是 extra_chromium_args
                '--enable-logging',
                '--v=1',
                *([] if not self.enable_features else [self.enable_features]),
                *([] if not self.disable_features else [self.disable_features])
            ],
            # 新版 BrowserProfile 配置
            'headless': False,  # 显示浏览器窗口
            'keep_alive': False,  # 测试完成后关闭浏览器
            'disable_security': True,  # 禁用安全特性以便测试
            'no_viewport': True,  # 禁用视口设置，让浏览器使用保存的窗口大小偏好
            'window_position': None,  # 禁用窗口定位，让浏览器使用 profile 中保存的窗口位置
            # 注意：不能设置 window_size=None，因为会触发 --start-maximized
            # 也不能完全省略，因为 detect_display_configuration() 会自动设置为屏幕大小
            # 解决方案：需要修改启动参数来移除 --window-size 和 --window-position
        }

        # Add proxy if configured (will be set by async call)
        # Note: Proxy must be set via BrowserProfile.proxy parameter after async init
        return config
        
    async def init_proxy_pool(self, max_proxies: int = 30) -> None:
        """Initialize free proxy pool.

        Args:
            max_proxies: Maximum number of proxies to scrape and verify
        """
        print(f"[Config] Initializing proxy pool with target: {max_proxies} proxies...")
        self.proxy_pool = await ProxyPool.create_from_free_sources(max_proxies=max_proxies)
        self.use_proxy = True
        print(f"[Config] Proxy pool initialized: {self.proxy_pool.get_stats()}")

    async def get_proxy_for_browser(self) -> Optional[ProxySettings]:
        """Get next proxy configuration for browser.

        Returns:
            ProxySettings object or None if no proxy pool
        """
        if not self.use_proxy or not self.proxy_pool:
            return None

        proxy = await self.proxy_pool.get_proxy()
        if proxy:
            self._current_proxy = proxy
            # Return ProxySettings object (BrowserProfile expects this)
            return ProxySettings(server=proxy.url)
        return None

    async def mark_proxy_result(self, success: bool, response_time: float = 0.0) -> None:
        """Mark the result of using current proxy.

        Args:
            success: Whether the request succeeded
            response_time: Response time in seconds
        """
        if self._current_proxy and self.proxy_pool:
            await self.proxy_pool.mark_result(self._current_proxy, success, response_time)
            self._current_proxy = None

    def validate(self) -> None:
        """Validate configuration settings."""
        if not Path(self.edge_path).exists():
            raise ValueError(f"Edge browser not found at: {self.edge_path}")

        if not Path(self.user_data_dir).exists():
            raise ValueError(f"User data directory not found: {self.user_data_dir}")

        if self.max_actions_per_step <= 0:
            raise ValueError("MAX_ACTIONS_PER_STEP must be positive")

        if self.max_steps <= 0:
            raise ValueError("MAX_STEPS must be positive")

# Create global config instance
config = TestAgentConfig()