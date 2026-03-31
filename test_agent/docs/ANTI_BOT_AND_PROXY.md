# 反爬虫与代理池方案

## 问题背景

Nike 等严格网站会触发以下拦截：

```
We had an issue with your request.
If you continue experiencing issues, try refreshing the page.
[ Code: 4DB3A115 ]
```

这是 Akamai Bot Manager 的拦截响应。检测维度主要有三类：

### 1. 浏览器指纹
```javascript
navigator.webdriver: true    // CDP 痕迹
navigator.plugins.length: 0  // headless 特征
window.chrome: undefined     // headless 无 chrome 对象
```

### 2. IP 与网络特征（最关键）
- 同一 IP 短时间内大量请求
- IP 属于数据中心/云服务商
- 缺少正常的 TCP 指纹

### 3. 行为特征
- 鼠标直线移动、无悬停
- 操作间隔固定
- 滚动匀速

---

## 方案一：免费代理池（开发测试用）

### 快速启用

```bash
# 自动抓取 30 个免费代理并轮换使用
python test_agent/test_runner.py --use-proxy-pool

# 自定义代理数量
python test_agent/test_runner.py --use-proxy-pool --max-proxies 50

# 快速验证（少量代理，启动快）
python test_agent/test_runner.py --use-proxy-pool --max-proxies 5
```

### 工作原理

```
启动时自动抓取代理
    ├─→ free-proxy-list.net (HTML 表格)
    └─→ proxyscrape.com (API)
    ↓
去重（500+ → 300+）
    ↓
并发验证（20 个/批，测试 https://httpbin.org/ip）
    ↓
保留可用代理（30 个）
    ↓
Round-robin 轮换使用
```

### 轮换与屏蔽机制

```python
# Round-robin 示例
代理池: [P1, P2, P3, P4, P5]

Test 1 → P1 → 成功 ✅
Test 2 → P2 → 成功 ✅
Test 3 → P3 → 失败 ❌ (success_rate < 30%, blocked=True)
Test 4 → P4 → 成功 ✅
Test 5 → P1 → 成功 ✅  (P3 被跳过)

# 屏蔽条件：fail_count >= 2 且 success_rate < 30%
```

### 代理池管理

```bash
# 独立抓取并保存到文件
python -m test_agent.llm.free_proxy_pool --scrape --count 30 --save proxies.txt

# 使用已保存的代理文件
# proxies.txt 格式：
# 103.152.112.162:80
# http://username:password@proxy.example.com:8080
```

```python
from test_agent.config import config

# 从文件加载
config.proxy_pool = ProxyPool.from_file('proxies.txt')
config.use_proxy = True
```

### 监控代理池状态

```python
stats = config.proxy_pool.get_stats()
print(f"Available: {stats['available']}/{stats['total']}")
print(f"Blocked: {stats['blocked']}")
print(f"Avg Success Rate: {stats['avg_success_rate']:.1%}")

# 可用率 < 30% 时需要重新抓取
```

### 免费代理的局限性

| 指标 | 实际情况 |
|------|---------|
| 可用率 | ~6%（500 个里约 30 个能用） |
| 响应时间 | 1-5 秒（直连 <100ms） |
| 启动时间 | 30-60 秒 |
| 稳定性 | 差，随时失效 |

**适用**：开发测试、临时验证
**不适用**：生产环境、大规模爬取

### 在代码中集成

```python
import asyncio
from browser_use import Agent, BrowserProfile
from test_agent.llm.llm_config import get_claude_sonnet
from test_agent.config import config

async def main():
    # 初始化代理池
    await config.init_proxy_pool(max_proxies=30)

    # 获取代理并创建 BrowserProfile
    browser_config = config.get_browser_profile_config()
    proxy_settings = await config.get_proxy_for_browser()
    if proxy_settings:
        browser_config['proxy'] = proxy_settings  # ProxySettings 对象，非 dict

    browser = BrowserProfile(**browser_config)
    agent = Agent(
        task="Visit nike.com and add shoes to cart",
        llm=get_claude_sonnet(),
        browser_profile=browser,
    )

    history = await agent.run()
    await config.mark_proxy_result(success=history.is_successful())

asyncio.run(main())
```

> **注意**：`get_proxy_for_browser()` 返回 `ProxySettings` 对象而非 `dict`。
> `BrowserProfile` 的 `proxy` 字段类型是 `ProxySettings | None`，传入 `dict` 时因 `extra='ignore'` 会被静默丢弃，代理不生效。

### 常见问题

**Q：抓取很慢？**
减少 `--max-proxies` 数量，或提前抓取保存到文件。

**Q：所有代理都被屏蔽了？**
ProxyPool 会自动重置成功率最高的 1/3 代理。如果仍不够：
```bash
python test_agent/test_runner.py --use-proxy-pool --max-proxies 100
```

**Q：代理池会自动重试吗？**
不会，需要在业务逻辑中自行重试：
```python
for i in range(3):
    proxy = await config.get_proxy_for_browser()
    try:
        # 运行测试...
        await config.mark_proxy_result(success=True)
        break
    except Exception:
        await config.mark_proxy_result(success=False)
```

---

## 方案二：商业住宅代理（生产环境推荐）

| 服务商 | 类型 | 月费 | IP 池大小 | 推荐度 |
|--------|------|------|---------|--------|
| Bright Data | 住宅 | $500+ | 7200 万+ | ⭐⭐⭐⭐⭐ |
| Smartproxy | 住宅 | $75+ | 4000 万+ | ⭐⭐⭐⭐⭐ |
| Oxylabs | 住宅 | $300+ | 1 亿+ | ⭐⭐⭐⭐⭐ |
| IPRoyal | 住宅 | $7/GB | 200 万+ | ⭐⭐⭐⭐ |
| ScrapingBee | API | $49+ | — | ⭐⭐⭐⭐（最简单） |

**对于 Nike 等 Akamai 保护的网站，必须使用住宅代理，数据中心 IP 会被立即封禁。**

### Bright Data 配置

```python
from browser_use.browser.profile import ProxySettings

proxy = ProxySettings(
    server="http://brd.superproxy.io:22225",
    username="brd-customer-{CUSTOMER_ID}-zone-residential-country-us",
    password="YOUR_PASSWORD",
)
```

### Smartproxy 配置（Sticky Sessions）

```python
# 每个 session_id 对应一个固定 IP（持续 10 分钟）
proxies = []
for i in range(20):
    proxies.append(ProxySettings(
        server="http://gate.smartproxy.com:7000",
        username=f"your_username-session-{i}-country-us",
        password="your_password",
    ))
```

### ScrapingBee（最省事，按请求计费）

```python
import requests

response = requests.get('https://app.scrapingbee.com/api/v1/', params={
    'api_key': 'YOUR_KEY',
    'url': 'https://www.nike.com/...',
    'render_js': True,
    'premium_proxy': True,
    'country_code': 'us',
    'stealth_proxy': True,
})
```

> ScrapingBee 返回 HTML，需要手动处理，不能直接与 browser-use 集成。

---

## 方案三：反检测浏览器配置（配合代理使用）

```python
# test_agent/config.py
browser_config = {
    'executable_path': self.edge_path,
    'user_data_dir': self.user_data_dir,
    'args': [
        '--disable-blink-features=AutomationControlled',
        '--exclude-switches=enable-automation',
        '--disable-infobars',
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        '--window-size=1920,1080',
    ],
    'headless': False,  # Akamai 能检测 headless，永远不要用
}
```

### 注入反检测脚本（高级）

```javascript
// 在页面加载前注入，隐藏自动化特征
Object.defineProperty(navigator, 'webdriver', { get: () => false });
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
Object.defineProperty(navigator, 'plugins', {
    get: () => [{ name: "Chrome PDF Plugin", filename: "internal-pdf-viewer", length: 1 }],
});
```

```python
await page.addInitScript(bypass_script)
```

---

## 方案对比

| 方案 | 成本 | 效果 | 稳定性 | 适用场景 |
|------|------|------|--------|---------|
| 免费代理池 | 免费 | ⭐⭐ 20-30% | ⭐ 差 | 开发测试 |
| 反检测配置 | 免费 | ⭐⭐⭐ 50-60% | ⭐⭐⭐ | 简单网站 |
| 商业住宅代理 | $75-500+/月 | ⭐⭐⭐⭐⭐ 95%+ | ⭐⭐⭐⭐⭐ | 生产环境 |
| 代理 + 反检测 | $75-500+/月 | ⭐⭐⭐⭐⭐ 99%+ | ⭐⭐⭐⭐⭐ | 严格网站 |
| ScrapingBee API | $49+/月 | ⭐⭐⭐⭐ 90%+ | ⭐⭐⭐⭐ | 最简单集成 |

**预算建议**：
- 开发阶段：免费代理池 + 反检测配置
- 生产环境：Smartproxy ($75/月) + 反检测配置
- 不想折腾：ScrapingBee 免费试用起步

---

## 相关文档

- `CLAUDE_SETUP.md` — Claude 模型配置
- `USER_DATA_DIR_SOLUTION.md` — Browser profile 污染问题（另一个反爬虫角度）
- `RDP_Session_Management.md` — RDP 环境下的特殊问题
