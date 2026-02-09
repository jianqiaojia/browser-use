# 免费代理池使用指南

## 🎯 功能概述

免费代理池功能允许你通过轮换IP地址来绕过网站的反爬虫检测（如Nike的 Code: 4DB3A115 错误）。

**核心特性**：
- ✅ 自动从多个源抓取免费代理
- ✅ 自动验证代理可用性
- ✅ Round-robin轮换策略
- ✅ 自动屏蔽失败的代理
- ✅ 统计成功率和响应时间

## 🚀 快速开始

### 1. 基础用法 - 启用代理池

```bash
cd "q:\AI\browser-use"
uv run python test_runner_claude.py --use-proxy-pool
```

这会：
1. 自动抓取30个免费代理
2. 验证可用性
3. 在测试中自动轮换使用

### 2. 高级用法 - 自定义代理数量

```bash
# 抓取更多代理（更稳定但启动慢）
uv run python test_runner_claude.py --use-proxy-pool --max-proxies 50

# 快速测试（少量代理）
uv run python test_runner_claude.py --use-proxy-pool --max-proxies 10
```

## 📊 代理池管理

### 独立测试代理池

```bash
# 抓取并验证30个代理
uv run python test_agent/free_proxy_pool.py --scrape --count 30

# 抓取并保存到文件
uv run python test_agent/free_proxy_pool.py --scrape --count 30 --save proxies.txt
```

输出示例：
```
[ProxyScraper] Starting to scrape proxies (target: 30)...
[ProxyScraper] Scraped 300 proxies from free-proxy-list.net
[ProxyScraper] Scraped 200 proxies from proxyscrape.com
[ProxyScraper] After deduplication: 450
[ProxyScraper] ✓ 103.152.112.162:80 (1.23s)
[ProxyScraper] ✓ 185.217.143.96:3128 (2.45s)
...
[ProxyScraper] ✓ Found 32 working proxies

[Stats]
  Total: 32
  Available: 32
  Blocked: 0
  Avg Success Rate: 100.0%
```

### 使用保存的代理文件

如果你已经有一个代理列表文件，可以直接使用：

```python
from test_agent.config import config

# 在代码中加载
config.proxy_pool = ProxyPool.from_file('proxies.txt')
config.use_proxy = True
```

代理文件格式：
```
# Simple format
103.152.112.162:80
185.217.143.96:3128

# With authentication
http://username:password@proxy.example.com:8080

# Comments are ignored
# socks5://proxy.example.com:1080
```

## 🔧 工作原理

### 1. 代理抓取流程

```
用户启动测试
    ↓
自动抓取代理
    ├─→ free-proxy-list.net (HTML表格)
    └─→ proxyscrape.com (API)
    ↓
去重 (450+ → 300+)
    ↓
并发验证 (20个/批)
    └─→ 测试 https://httpbin.org/ip
    ↓
保留可用代理 (30个)
    ↓
开始测试
```

### 2. 轮换策略

```python
# Round-robin 示例
代理池: [Proxy1, Proxy2, Proxy3, Proxy4, Proxy5]

Test 1 → Proxy1 → 成功 ✅
Test 2 → Proxy2 → 成功 ✅
Test 3 → Proxy3 → 失败 ❌ (success_rate < 30%, blocked=True)
Test 4 → Proxy4 → 成功 ✅
Test 5 → Proxy5 → 成功 ✅
Test 6 → Proxy1 → 成功 ✅  (Proxy3被跳过)
```

### 3. 自动屏蔽机制

```python
# ProxyServer 自动屏蔽逻辑
def mark_used(success: bool):
    if success:
        self.success_count += 1
        self.blocked = False
    else:
        self.fail_count += 1
        # 连续失败2次 且 成功率<30% → 屏蔽
        if self.fail_count >= 2 and self.success_rate < 0.3:
            self.blocked = True
```

## 📈 效果对比

### 不使用代理池

```
Nike Test → Code: 4DB3A115 (反爬虫检测) → 失败 ❌
```

### 使用代理池

```
Nike Test
    ↓
Attempt 1 (Proxy1) → Code: 4DB3A115 → 失败 ❌ (标记代理1)
    ↓
Attempt 2 (Proxy2) → 200 OK → 成功 ✅
```

## ⚠️ 重要提示

### 免费代理的局限性

1. **成功率低**：
   - 抓取500个 → 验证后剩30个 (~6%可用率)
   - 实际使用中可能继续失效

2. **速度慢**：
   - 响应时间：1-5秒（vs 直连的 <100ms）
   - 启动时间：抓取+验证需要 30-60秒

3. **不稳定**：
   - 代理随时可能失效
   - 需要定期重新抓取

### 最佳实践

✅ **推荐用于**：
- 开发和测试环境
- 绕过简单的IP限制
- 临时验证反爬虫解决方案

❌ **不推荐用于**：
- 生产环境
- 大规模爬取
- 需要稳定性的场景

### 生产环境替代方案

对于生产环境，建议使用商业代理服务：

| 服务商 | 成本 | 成功率 | 速度 | 特点 |
|--------|------|--------|------|------|
| Bright Data | $500+/月 | 99%+ | 快 | 最大代理池 |
| Smartproxy | $75+/月 | 95%+ | 快 | 性价比高 |
| Oxylabs | $300+/月 | 98%+ | 快 | 企业级 |

参考 `ANTI_BOT_SOLUTIONS.md` 获取详细对比。

## 🔍 调试和监控

### 查看代理池状态

```python
from test_agent.config import config

# 在测试中查看统计
stats = config.proxy_pool.get_stats()
print(f"Available: {stats['available']}/{stats['total']}")
print(f"Blocked: {stats['blocked']}")
print(f"Avg Success Rate: {stats['avg_success_rate']:.1%}")
```

### 手动测试单个代理

```python
import asyncio
from test_agent.free_proxy_pool import FreeProxyScraper, ProxyServer

async def test():
    proxy = ProxyServer(host='103.152.112.162', port=80)
    is_working, response_time = await FreeProxyScraper.test_proxy(proxy)
    print(f"Working: {is_working}, Time: {response_time:.2f}s")

asyncio.run(test())
```

### 查看历史文件中的代理使用

测试历史文件会显示使用的代理（如果启用）：
```json
{
  "config": {
    "proxy": "http://103.152.112.162:80"
  },
  "result": "success"
}
```

## 📚 代码集成示例

### 示例1：在自定义脚本中使用

```python
import asyncio
from browser_use import Agent, BrowserProfile
from test_agent.llm_config import get_claude_sonnet
from test_agent.config import config

async def main():
    # 1. 初始化代理池
    await config.init_proxy_pool(max_proxies=30)

    # 2. 获取代理配置
    browser_config = config.get_browser_profile_config()
    proxy_config = await config.get_proxy_for_browser()
    if proxy_config:
        browser_config['proxy'] = proxy_config

    # 3. 创建浏览器和Agent
    browser = BrowserProfile(**browser_config)
    llm = get_claude_sonnet()
    agent = Agent(
        task="Visit nike.com and add shoes to cart",
        llm=llm,
        browser_profile=browser
    )

    # 4. 运行任务
    history = await agent.run()

    # 5. 标记代理结果
    await config.mark_proxy_result(
        success=history.is_successful(),
        response_time=0.0
    )

asyncio.run(main())
```

### 示例2：批量测试多个网站

```python
import asyncio
from test_agent.config import config

async def test_websites():
    # 初始化代理池一次
    await config.init_proxy_pool(max_proxies=50)

    websites = ['nike.com', 'adidas.com', 'puma.com']

    for site in websites:
        # 每个网站使用不同的代理
        proxy = await config.get_proxy_for_browser()
        print(f"Testing {site} with {proxy['server']}")

        # ... 运行测试 ...
        success = True  # 假设成功

        # 标记结果
        await config.mark_proxy_result(success=success)

asyncio.run(test_websites())
```

## 🎓 技术细节

### ProxyServer 类

```python
@dataclass
class ProxyServer:
    host: str
    port: int
    username: Optional[str] = None  # 认证（如果需要）
    password: Optional[str] = None
    protocol: str = 'http'  # http, https, socks5

    # 自动统计
    success_count: int = 0
    fail_count: int = 0
    blocked: bool = False
    response_time: float = 0.0

    @property
    def url(self) -> str:
        """生成代理URL"""
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        """计算成功率"""
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0
```

### ProxyPool 类

```python
class ProxyPool:
    async def get_proxy(self) -> Optional[ProxyServer]:
        """获取下一个可用代理（round-robin）"""

    async def mark_result(self, proxy: ProxyServer, success: bool):
        """标记代理使用结果"""

    def get_stats(self) -> dict:
        """获取统计信息"""

    @classmethod
    async def create_from_free_sources(cls, max_proxies: int = 30):
        """从免费源创建代理池（推荐）"""

    @classmethod
    def from_file(cls, filepath: str):
        """从文件加载代理"""
```

## 🐛 常见问题

### Q: 抓取代理很慢？
A: 这是正常的。验证500个代理需要30-60秒。可以：
- 减少 `--max-proxies` 数量（如 `--max-proxies 10`）
- 提前抓取并保存到文件：`python free_proxy_pool.py --scrape --save proxies.txt`

### Q: 所有代理都被屏蔽了？
A: ProxyPool会自动重置成功率最高的1/3代理。如果仍然不够：
```bash
# 重新抓取更多代理
uv run python test_runner_claude.py --use-proxy-pool --max-proxies 100
```

### Q: 能不能直接设置代理而不抓取？
A: 可以。创建一个 `proxies.txt` 文件：
```python
from test_agent.free_proxy_pool import ProxyPool
config.proxy_pool = ProxyPool.from_file('proxies.txt')
config.use_proxy = True
```

### Q: 代理池会自动重试吗？
A: 不会。如果当前代理失败，需要你的代码逻辑去重试：
```python
max_retries = 3
for i in range(max_retries):
    proxy = await config.get_proxy_for_browser()
    try:
        # 运行测试...
        await config.mark_proxy_result(success=True)
        break
    except Exception:
        await config.mark_proxy_result(success=False)
```

## 📝 总结

**优点**：
- ✅ 完全免费
- ✅ 自动化抓取和验证
- ✅ 即插即用
- ✅ 适合开发测试

**缺点**：
- ❌ 成功率低（~6%）
- ❌ 速度慢（1-5秒响应）
- ❌ 不稳定（随时失效）
- ❌ 不适合生产环境

**建议**：
- 开发测试：使用免费代理池 ✅
- 生产环境：升级到商业代理 ✅
- 大规模爬取：必须使用商业代理 ✅

更多反爬虫解决方案请参考 `ANTI_BOT_SOLUTIONS.md`。
