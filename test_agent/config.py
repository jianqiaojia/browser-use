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
from typing import Final, Dict, List, Any

# Directory Configuration
BASE_DIR: Final[Path] = Path("test_agent")
TEST_CASE_DIR: Final[Path] = BASE_DIR / "test_case"

# Browser Configuration
EDGE_CANARY_PATH: Final[str] = 'C:\\Users\\jianqiaojia\\AppData\\Local\\Microsoft\\Edge SxS\\Application\\msedge.exe'
EDGE_USER_DATA_DIR: Final[str] = 'C:\\Users\\jianqiaojia\\xpay-edge-starter\\default-profile'
DEFAULT_PROFILE: Final[str] = 'Profile 1'
WALLET_PANE_URL: Final[str] = 'edge://wallet-drawer/'
ENABLE_FEATURES: Final[str] = ''
DISABLE_FEATURES: Final[str] = ''

# Log File Configuration
EDGE_LOG_FILE_PATH: Final[str] = 'C:\\Users\\jianqiaojia\\xpay-edge-starter\\default-profile\\chrome_debug.log'

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
        self.edge_path = EDGE_CANARY_PATH
        self.user_data_dir = EDGE_USER_DATA_DIR
        self.profile = DEFAULT_PROFILE
        self.wallet_pane_url = WALLET_PANE_URL
        self.enable_features = ENABLE_FEATURES
        self.disable_features = DISABLE_FEATURES
        self.log_file_path = EDGE_LOG_FILE_PATH
        
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
        
    def get_browser_profile_config(self) -> Dict[str, Any]:
        """Get browser profile configuration dictionary.
        
        新版：返回 BrowserProfile 所需的配置
        """
        return {
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
        }
        
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