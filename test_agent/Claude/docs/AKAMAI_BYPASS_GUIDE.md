# Akamai 绕过方案 - 商业代理配置示例

## 方案1：Bright Data + Anti-Detect Browser

### 1.1 配置 Bright Data 住宅代理

```python
# test_agent/config_brightdata.py

from browser_use.browser.profile import ProxySettings

def get_brightdata_proxy(zone: str = "residential") -> ProxySettings:
    """
    获取 Bright Data 代理配置

    注册地址: https://brightdata.com
    价格: $500/月起（40GB流量）

    Args:
        zone: 代理区域类型
            - "residential": 住宅IP（推荐，最难检测）
            - "datacenter": 数据中心IP（便宜但容易被封）
            - "mobile": 移动网络IP（4G/5G，最真实）
    """
    # 从 Bright Data 控制台获取
    CUSTOMER_ID = "hl_YOUR_CUSTOMER_ID"  # 替换为你的 customer ID
    PASSWORD = "YOUR_PASSWORD"           # 替换为你的密码

    # Bright Data 配置
    # 格式: brd-customer-{CUSTOMER_ID}-zone-{ZONE}-country-{COUNTRY}
    username = f"brd-customer-{CUSTOMER_ID}-zone-{zone}-country-us"

    return ProxySettings(
        server="http://brd.superproxy.io:22225",
        username=username,
        password=PASSWORD
    )

# 使用示例
proxy = get_brightdata_proxy(zone="residential")
browser_config['proxy'] = proxy
```

### 1.2 配置反检测参数

```python
# test_agent/config.py 增强版

def get_browser_profile_config(self) -> Dict[str, Any]:
    """增强的反检测配置"""
    config = {
        'executable_path': self.edge_path,
        'user_data_dir': self.user_data_dir,
        'profile_directory': self.profile,

        # 基础反检测
        'args': [
            '--enable-logging',
            '--v=1',
            '--disable-blink-features=AutomationControlled',  # 隐藏自动化标记

            # 额外的反检测参数
            '--disable-features=IsolateOrigins,site-per-process',
            '--disable-site-isolation-trials',
            '--disable-web-security',  # 仅测试环境
            '--disable-dev-shm-usage',
            '--no-sandbox',

            # 模拟真实浏览器
            '--window-size=1920,1080',
            '--disable-infobars',
            '--disable-extensions-except=/path/to/ublock',  # 使用真实扩展
        ],

        'headless': False,  # Akamai 能检测 headless
        'disable_security': True,
    }

    return config
```

### 1.3 添加行为模拟

```python
# test_agent/human_behavior.py

import random
import asyncio

class HumanBehaviorSimulator:
    """模拟人类行为，绕过 Akamai 时间序列分析"""

    @staticmethod
    async def random_delay(min_ms: int = 1000, max_ms: int = 3000):
        """随机延迟（模拟人类思考时间）"""
        delay = random.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    @staticmethod
    async def simulate_mouse_movement(page):
        """模拟鼠标移动"""
        # 随机移动鼠标到页面上的位置
        x = random.randint(100, 1800)
        y = random.randint(100, 900)
        await page.mouse.move(x, y)

    @staticmethod
    async def simulate_scrolling(page):
        """模拟页面滚动"""
        scroll_distance = random.randint(300, 800)
        await page.evaluate(f"window.scrollBy(0, {scroll_distance})")
        await asyncio.sleep(random.uniform(0.5, 1.5))

# 在 agent 中使用
from test_agent.human_behavior import HumanBehaviorSimulator

async def run_test_with_human_behavior(agent, task):
    behavior = HumanBehaviorSimulator()

    # 访问页面前随机延迟
    await behavior.random_delay(2000, 5000)

    # 执行任务...
    result = await agent.run(task)

    return result
```

## 方案2：使用专业的反检测工具

### 2.1 Playwright Stealth（免费，但效果有限）

```python
# 安装
pip install playwright-stealth

# 使用
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

async with async_playwright() as p:
    browser = await p.chromium.launch()
    page = await browser.new_page()
    await stealth_async(page)  # 应用反检测
    await page.goto('https://www.nike.com')
```

### 2.2 Undetected ChromeDriver（仅适用于 Selenium）

```bash
pip install undetected-chromedriver
```

## 方案3：使用 Scraping API 服务（最简单）

### 3.1 ScrapingBee 配置

```python
# test_agent/config_scrapingbee.py

import requests

def scrape_with_scrapingbee(url: str) -> str:
    """
    使用 ScrapingBee 绕过 Akamai

    注册: https://www.scrapingbee.com
    价格: $49/月起（1000次请求）

    ScrapingBee 会：
    - 自动处理 JavaScript
    - 轮换住宅IP
    - 绕过 Cloudflare/Akamai
    - 处理验证码
    """
    API_KEY = "YOUR_SCRAPINGBEE_API_KEY"

    params = {
        'api_key': API_KEY,
        'url': url,
        'render_js': True,           # 渲染 JavaScript
        'premium_proxy': True,        # 使用高级代理
        'country_code': 'us',         # 美国IP
        'stealth_proxy': True,        # 启用隐身模式
    }

    response = requests.get('https://app.scrapingbee.com/api/v1/', params=params)
    return response.text

# 集成到 browser-use
# 注意：ScrapingBee 返回的是 HTML，需要手动处理
```

## 方案4：分析 Akamai 的具体检测点（高级）

### 4.1 识别触发点

```python
# test_agent/akamai_analyzer.py

async def analyze_akamai_detection(page):
    """
    分析 Akamai 检测了什么
    """
    # 1. 检查是否加载了 Akamai sensor
    sensor_scripts = await page.evaluate("""
        () => {
            const scripts = Array.from(document.scripts);
            return scripts.filter(s =>
                s.src.includes('kpsdk') ||
                s.src.includes('akamai')
            ).map(s => s.src);
        }
    """)

    print(f"[Akamai] Detected sensors: {sensor_scripts}")

    # 2. 检查 cookies
    cookies = await page.context.cookies()
    akamai_cookies = [c for c in cookies if 'kp' in c['name'].lower()]
    print(f"[Akamai] Cookies: {akamai_cookies}")

    # 3. 检查是否有指纹收集
    canvas_hash = await page.evaluate("""
        () => {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            ctx.textBaseline = 'top';
            ctx.font = '14px Arial';
            ctx.fillText('test', 2, 2);
            return canvas.toDataURL();
        }
    """)
    print(f"[Akamai] Canvas fingerprint: {canvas_hash[:50]}...")

# 在测试前调用
await analyze_akamai_detection(page)
```

### 4.2 针对性绕过

```javascript
// 注入到页面的脚本（覆盖检测）
const bypassAkamai = `
    // 1. 隐藏 webdriver
    Object.defineProperty(navigator, 'webdriver', {
        get: () => false,
    });

    // 2. 修改 Chrome 对象
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {},
    };

    // 3. 覆盖 permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );

    // 4. 插件伪装
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            {
                0: {type: "application/x-google-chrome-pdf"},
                description: "Portable Document Format",
                filename: "internal-pdf-viewer",
                length: 1,
                name: "Chrome PDF Plugin"
            },
            // ... 更多插件
        ],
    });
`;

// 在页面加载前注入
await page.addInitScript(bypassAkamai);
```

## 💰 成本对比

| 方案 | 月成本 | 成功率 | 维护成本 |
|------|--------|--------|---------|
| 免费代理 | $0 | <5% | 高 |
| Bright Data 住宅 | $500+ | 95%+ | 低 |
| Smartproxy | $75+ | 85%+ | 低 |
| ScrapingBee | $49+ | 90%+ | 极低 |
| 自己绕过 Akamai | $0 | 20-60% | 极高 |

## 📝 总结

**针对 Akamai Bot Manager 的 429 错误：**

1. ❌ **免费代理完全不行** - IP会被立即封禁
2. ✅ **商业住宅代理 + 反检测** - 推荐方案
3. ✅ **Scraping API 服务** - 最简单但按请求收费
4. ⚠️ **手动绕过** - 技术难度高，不稳定

**我的建议：**
- 如果预算允许：使用 **Smartproxy ($75/月)** + 上述反检测配置
- 如果预算紧张：先用 **ScrapingBee ($49/月)** 的免费试用
- 如果不想花钱：找一个**没有 Akamai 保护的测试网站**来验证 Claude

需要我帮你配置哪个方案？
