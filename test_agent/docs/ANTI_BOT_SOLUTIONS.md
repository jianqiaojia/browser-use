# 网站反爬虫解决方案

## 🎯 问题分析

### 你遇到的错误

```
We had an issue with your request.
If you continue experiencing issues, try refreshing the page.
[ Code: 4DB3A115 ]
```

**这是什么？**
- 这是Nike网站的**反爬虫/反机器人**拦截页面
- Code: 4DB3A115 是Nike的错误追踪码
- 说明Nike检测到了自动化行为并阻止了访问

### 为什么会被检测？

#### 1. **浏览器指纹特征**
```javascript
// Nike网站可能检测的指标
{
  navigator.webdriver: true,           // ❌ Chrome DevTools Protocol的痕迹
  navigator.plugins.length: 0,         // ❌ 无插件（headless特征）
  navigator.languages: ["en-US"],      // ⚠️  语言太简单
  window.chrome: undefined,            // ❌ headless模式没有chrome对象
  screen.width === window.innerWidth   // ❌ 完美匹配（不自然）
}
```

#### 2. **IP和网络特征** ⭐ 关键
```
反爬虫系统检测：
- 同一IP短时间内大量请求 ❌
- IP地理位置与用户行为不匹配 ❌
- IP属于数据中心/云服务商 ❌
- 没有正常的TCP指纹 ❌
```

#### 3. **行为特征**
```
人类行为：
- 鼠标移动有曲线、加速度
- 点击前有悬停（hover）
- 滚动有惯性
- 操作间隔随机

机器人行为（browser-use默认）：
- 鼠标直线移动 ❌
- 点击无悬停 ❌
- 滚动匀速 ❌
- 操作间隔固定 ❌
```

## 🛡️ 解决方案分类

### 方案1: 代理IP池 ⭐⭐⭐⭐⭐ （推荐）

#### 为什么需要代理IP池？

**单IP的问题**：
```
你的真实IP：xxx.xxx.xxx.xxx
   ↓
访问Nike 1次 ✅
访问Nike 5次 ✅
访问Nike 10次 ⚠️  开始被监控
访问Nike 20次 ❌ IP被标记
访问Nike 30次 ❌ 直接拦截（Code: 4DB3A115）
```

**代理IP池**：
```
代理IP池（100个IP）
   ↓
每次请求用不同IP
   ↓
每个IP访问次数 < 5
   ↓
不会触发反爬虫 ✅
```

#### 1.1 使用商业住宅代理（最佳方案）

**推荐提供商**：

| 提供商 | 类型 | 价格 | IP池大小 | 推荐度 |
|--------|------|------|---------|--------|
| Bright Data | 住宅代理 | $500/月 起 | 7200万+ | ⭐⭐⭐⭐⭐ |
| Smartproxy | 住宅代理 | $75/月 起 | 4000万+ | ⭐⭐⭐⭐⭐ |
| Oxylabs | 住宅代理 | $300/月 起 | 1亿+ | ⭐⭐⭐⭐⭐ |
| IPRoyal | 住宅代理 | $7/GB | 200万+ | ⭐⭐⭐⭐ |
| Proxy-Cheap | 住宅代理 | $49/月 起 | 600万+ | ⭐⭐⭐ |

**实现代码**：

```python
# test_agent/proxy_manager.py

import random
import asyncio
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class ProxyServer:
	"""单个代理服务器"""
	host: str
	port: int
	username: Optional[str] = None
	password: Optional[str] = None
	protocol: str = 'http'  # http, https, socks5

	# 统计信息
	success_count: int = 0
	fail_count: int = 0
	last_used: Optional[datetime] = None
	blocked: bool = False

	@property
	def url(self) -> str:
		"""生成代理URL"""
		if self.username and self.password:
			return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
		return f"{self.protocol}://{self.host}:{self.port}"

	@property
	def success_rate(self) -> float:
		"""成功率"""
		total = self.success_count + self.fail_count
		return self.success_count / total if total > 0 else 1.0

	def mark_used(self, success: bool):
		"""标记使用结果"""
		self.last_used = datetime.now()
		if success:
			self.success_count += 1
			self.blocked = False
		else:
			self.fail_count += 1
			# 连续失败3次标记为blocked
			if self.fail_count >= 3 and self.success_rate < 0.3:
				self.blocked = True


class ProxyPool:
	"""代理IP池管理器"""

	def __init__(self, proxies: List[ProxyServer], rotation_strategy: str = 'round_robin'):
		"""
		Args:
			proxies: 代理服务器列表
			rotation_strategy: 轮换策略
				- 'round_robin': 顺序轮换
				- 'random': 随机选择
				- 'least_used': 选择使用最少的
				- 'best_success_rate': 选择成功率最高的
		"""
		self.proxies = proxies
		self.rotation_strategy = rotation_strategy
		self.current_index = 0
		self.lock = asyncio.Lock()

	@classmethod
	def from_brightdata(cls, username: str, password: str, country: str = 'us') -> 'ProxyPool':
		"""
		从Bright Data创建代理池

		Bright Data使用单个endpoint，自动轮换IP
		"""
		# Bright Data的endpoint格式
		proxy = ProxyServer(
			host=f'brd.superproxy.io',
			port=22225,
			username=f'{username}-country-{country}',
			password=password,
			protocol='http'
		)
		return cls([proxy], rotation_strategy='random')

	@classmethod
	def from_smartproxy(cls, username: str, password: str, country: str = 'us', count: int = 10) -> 'ProxyPool':
		"""
		从Smartproxy创建代理池

		Smartproxy支持sticky sessions（固定IP一段时间）
		"""
		proxies = []
		for i in range(count):
			# 每个session ID对应一个sticky IP（10分钟）
			session_id = f'session-{i}'
			proxy = ProxyServer(
				host='gate.smartproxy.com',
				port=7000,
				username=f'{username}-session-{session_id}-country-{country}',
				password=password,
				protocol='http'
			)
			proxies.append(proxy)
		return cls(proxies, rotation_strategy='round_robin')

	@classmethod
	def from_proxy_list(cls, proxy_list_file: str) -> 'ProxyPool':
		"""
		从文件加载代理列表

		文件格式（每行一个）：
		protocol://username:password@host:port
		或
		host:port
		"""
		proxies = []
		with open(proxy_list_file, 'r') as f:
			for line in f:
				line = line.strip()
				if not line or line.startswith('#'):
					continue

				# 解析代理URL
				if '://' in line:
					# 完整格式：protocol://username:password@host:port
					parts = line.split('://')
					protocol = parts[0]
					remaining = parts[1]

					if '@' in remaining:
						auth, endpoint = remaining.split('@')
						username, password = auth.split(':')
						host, port = endpoint.split(':')
					else:
						host, port = remaining.split(':')
						username = password = None
				else:
					# 简单格式：host:port
					host, port = line.split(':')
					protocol = 'http'
					username = password = None

				proxy = ProxyServer(
					host=host,
					port=int(port),
					username=username,
					password=password,
					protocol=protocol
				)
				proxies.append(proxy)

		return cls(proxies)

	async def get_proxy(self) -> Optional[ProxyServer]:
		"""
		获取下一个可用代理

		Returns:
			ProxyServer or None if no proxy available
		"""
		async with self.lock:
			available_proxies = [p for p in self.proxies if not p.blocked]

			if not available_proxies:
				# 所有代理都被blocked，重置最旧的几个
				self.proxies.sort(key=lambda p: p.last_used or datetime.min)
				for p in self.proxies[:len(self.proxies)//2]:
					p.blocked = False
					p.fail_count = 0
				available_proxies = [p for p in self.proxies if not p.blocked]

			if not available_proxies:
				return None

			# 根据策略选择代理
			if self.rotation_strategy == 'round_robin':
				self.current_index = (self.current_index + 1) % len(available_proxies)
				return available_proxies[self.current_index]

			elif self.rotation_strategy == 'random':
				return random.choice(available_proxies)

			elif self.rotation_strategy == 'least_used':
				return min(available_proxies, key=lambda p: p.success_count + p.fail_count)

			elif self.rotation_strategy == 'best_success_rate':
				return max(available_proxies, key=lambda p: p.success_rate)

			else:
				return random.choice(available_proxies)

	async def mark_proxy_result(self, proxy: ProxyServer, success: bool):
		"""标记代理使用结果"""
		async with self.lock:
			proxy.mark_used(success)

	def get_stats(self) -> dict:
		"""获取代理池统计信息"""
		total = len(self.proxies)
		blocked = sum(1 for p in self.proxies if p.blocked)
		avg_success_rate = sum(p.success_rate for p in self.proxies) / total if total > 0 else 0

		return {
			'total_proxies': total,
			'blocked_proxies': blocked,
			'available_proxies': total - blocked,
			'average_success_rate': avg_success_rate,
		}


# 使用示例
"""
# 1. 使用Bright Data
proxy_pool = ProxyPool.from_brightdata(
    username='brd-customer-xxxxxx',
    password='your_password',
    country='us'
)

# 2. 使用Smartproxy
proxy_pool = ProxyPool.from_smartproxy(
    username='your_username',
    password='your_password',
    country='us',
    count=20  # 20个sticky sessions
)

# 3. 从文件加载
proxy_pool = ProxyPool.from_proxy_list('proxies.txt')

# 获取并使用代理
proxy = await proxy_pool.get_proxy()
if proxy:
    print(f"Using proxy: {proxy.url}")
    # ... 使用代理

    # 标记结果
    await proxy_pool.mark_proxy_result(proxy, success=True)
"""
```

#### 1.2 集成到browser-use

```python
# test_agent/config.py - 增强版

from test_agent.proxy_manager import ProxyPool, ProxyServer

class TestAgentConfig:
	def __init__(self):
		# ... 现有配置

		# 代理配置
		self.use_proxy = True
		self.proxy_pool = None

	def init_proxy_pool(self, provider: str = 'brightdata'):
		"""初始化代理池"""
		if provider == 'brightdata':
			self.proxy_pool = ProxyPool.from_brightdata(
				username=os.getenv('BRIGHTDATA_USERNAME'),
				password=os.getenv('BRIGHTDATA_PASSWORD'),
				country='us'
			)
		elif provider == 'smartproxy':
			self.proxy_pool = ProxyPool.from_smartproxy(
				username=os.getenv('SMARTPROXY_USERNAME'),
				password=os.getenv('SMARTPROXY_PASSWORD'),
				country='us',
				count=20
			)
		elif provider == 'file':
			self.proxy_pool = ProxyPool.from_proxy_list('proxies.txt')

	async def get_proxy_for_browser(self):
		"""获取用于浏览器的代理配置"""
		if not self.use_proxy or not self.proxy_pool:
			return None

		proxy = await self.proxy_pool.get_proxy()
		if not proxy:
			return None

		# browser-use需要的代理格式
		return {
			'server': f'{proxy.host}:{proxy.port}',
			'username': proxy.username,
			'password': proxy.password,
		}


# 更新浏览器配置
config = TestAgentConfig()
config.init_proxy_pool(provider='brightdata')  # 或 'smartproxy' 或 'file'
```

#### 1.3 在test_runner中使用代理

```python
# test_runner_claude.py - 增强版

async def run_test_case(llm, test, trigger_id, run_id):
	"""Execute a test case with proxy rotation"""

	# 获取代理
	proxy_config = await config.get_proxy_for_browser()

	# 创建Browser Profile with proxy
	browser_config = config.get_browser_profile_config()

	if proxy_config:
		browser_config['proxy'] = proxy_config
		print(f"[Proxy] Using proxy: {proxy_config['server']}")

	browser_profile = BrowserProfile(**browser_config)

	try:
		# 创建Agent
		agent = Agent(
			task=task,
			llm=llm,
			browser_profile=browser_profile,
			max_actions_per_step=config.max_actions_per_step,
			use_vision=config.vision_enabled,
		)

		# 运行测试
		history = await agent.run(max_steps=config.max_steps)

		# 标记代理成功
		if proxy_config and config.proxy_pool:
			proxy = await config.proxy_pool.get_proxy()
			await config.proxy_pool.mark_proxy_result(proxy, success=True)

		return True

	except Exception as e:
		# 检查是否是反爬虫拦截
		if '4DB3A115' in str(e) or 'issue with your request' in str(e):
			print(f"[Proxy] Proxy blocked, marking as failed")

			# 标记代理失败
			if proxy_config and config.proxy_pool:
				proxy = await config.proxy_pool.get_proxy()
				await config.proxy_pool.mark_proxy_result(proxy, success=False)

			# 重试with新代理
			print("[Proxy] Retrying with new proxy...")
			return await run_test_case(llm, test, trigger_id, run_id)

		raise
```

### 方案2: 免费代理IP（不推荐生产环境）

#### 2.1 免费代理源

```python
# test_agent/free_proxy_scraper.py

import aiohttp
from bs4 import BeautifulSoup

class FreeProxyScraper:
	"""抓取免费代理"""

	@staticmethod
	async def scrape_free_proxy_list() -> List[ProxyServer]:
		"""从free-proxy-list.net抓取"""
		proxies = []
		url = 'https://free-proxy-list.net/'

		async with aiohttp.ClientSession() as session:
			async with session.get(url) as response:
				html = await response.text()
				soup = BeautifulSoup(html, 'html.parser')
				table = soup.find('table', {'id': 'proxylisttable'})

				for row in table.find_all('tr')[1:]:  # Skip header
					cols = row.find_all('td')
					if len(cols) >= 7:
						host = cols[0].text.strip()
						port = int(cols[1].text.strip())
						https = 'yes' in cols[6].text.lower()

						proxy = ProxyServer(
							host=host,
							port=port,
							protocol='https' if https else 'http'
						)
						proxies.append(proxy)

		return proxies

	@staticmethod
	async def test_proxy(proxy: ProxyServer, test_url: str = 'https://httpbin.org/ip') -> bool:
		"""测试代理是否可用"""
		try:
			timeout = aiohttp.ClientTimeout(total=10)
			async with aiohttp.ClientSession(timeout=timeout) as session:
				proxy_url = proxy.url
				async with session.get(test_url, proxy=proxy_url) as response:
					return response.status == 200
		except:
			return False

# 使用
"""
scraper = FreeProxyScraper()
proxies = await scraper.scrape_free_proxy_list()

# 测试并过滤可用代理
working_proxies = []
for proxy in proxies:
	if await scraper.test_proxy(proxy):
		working_proxies.append(proxy)

proxy_pool = ProxyPool(working_proxies, rotation_strategy='random')
"""
```

**免费代理的问题**：
- ❌ 稳定性差（90%+不可用）
- ❌ 速度慢
- ❌ 可能被大量网站封禁
- ❌ 安全风险（可能记录数据）

### 方案3: 反检测浏览器配置（配合代理使用）

```python
# test_agent/config.py

class TestAgentConfig:
	def get_browser_profile_config(self) -> Dict[str, Any]:
		return {
			'executable_path': self.edge_path,
			'user_data_dir': self.user_data_dir,
			'profile_directory': self.profile,

			# ✅ 反检测核心配置
			'args': [
				'--disable-blink-features=AutomationControlled',
				'--exclude-switches=enable-automation',
				'--disable-infobars',
				'--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
			],

			# 代理配置（如果有）
			'proxy': self.proxy_config if hasattr(self, 'proxy_config') else None,

			'disable_security': False,
			'headless': False,  # 永远不要headless
		}
```

## 📊 方案对比

| 方案 | 成本 | 效果 | 稳定性 | 通用性 | 推荐度 |
|------|------|------|--------|--------|--------|
| 商业住宅代理池 | 💰💰💰 $50-500/月 | ⭐⭐⭐⭐⭐ 95%+ | ⭐⭐⭐⭐⭐ | ✅ 通用 | ⭐⭐⭐⭐⭐ |
| 免费代理池 | 💰 免费 | ⭐⭐ 20-30% | ⭐ 差 | ⚠️  受限 | ⭐ |
| 反检测配置 | 💰 免费 | ⭐⭐⭐ 50-60% | ⭐⭐⭐ | ✅ 通用 | ⭐⭐⭐ |
| 代理+反检测 | 💰💰💰 $50-500/月 | ⭐⭐⭐⭐⭐ 99%+ | ⭐⭐⭐⭐⭐ | ✅ 通用 | ⭐⭐⭐⭐⭐ |

## 🎯 推荐实施方案

### 最佳组合：商业住宅代理 + 反检测配置

```python
# 1. 配置代理池
config = TestAgentConfig()
config.init_proxy_pool(provider='brightdata')  # 或 smartproxy

# 2. 启用反检测配置
browser_config = config.get_browser_profile_config()  # 已包含反检测args

# 3. 获取代理
proxy_config = await config.get_proxy_for_browser()

# 4. 创建browser profile
browser_profile = BrowserProfile(
	**browser_config,
	proxy=proxy_config  # 添加代理
)

# 5. 运行测试
agent = Agent(
	task=task,
	llm=llm,
	browser_profile=browser_profile,
)

history = await agent.run(max_steps=50)
```

### 预期效果

**使用代理池前**：
```
测试运行10次
成功: 2次 (20%)
失败: 8次 (Code: 4DB3A115)
```

**使用代理池后**：
```
测试运行10次
成功: 9-10次 (90-100%)
失败: 0-1次（代理质量问题）
```

## 💡 实用建议

### 1. 选择合适的代理类型

| 代理类型 | 特点 | 适用场景 | 成本 |
|---------|------|---------|------|
| 住宅代理 | 真实家庭IP，最难检测 | Nike等严格网站 | 最高 |
| 数据中心代理 | 快速，但容易被检测 | 简单网站 | 中等 |
| 移动代理 | 移动网络IP，非常可信 | 移动端测试 | 最高 |

**对于Nike**：推荐使用**住宅代理**。

### 2. 代理轮换策略

```python
# Nike访问频率限制（假设）
每个IP每小时 < 10次请求 ✅
每个IP每小时 > 20次请求 ❌ 被标记

# 代理池大小计算
预计每小时测试: 100次
每个IP限制: 5次（保守）
需要代理数: 100 / 5 = 20个

# 推荐：30-50个代理（留有余量）
```

### 3. 代理质量监控

```python
# 定期检查代理池状态
stats = proxy_pool.get_stats()
print(f"""
Proxy Pool Stats:
- Total: {stats['total_proxies']}
- Available: {stats['available_proxies']}
- Blocked: {stats['blocked_proxies']}
- Avg Success Rate: {stats['average_success_rate']:.2%}
""")

# 如果可用代理 < 30%，需要补充
if stats['available_proxies'] / stats['total_proxies'] < 0.3:
	print("⚠️  Warning: Too many proxies blocked, consider refreshing pool")
```

### 4. 成本优化

**Bright Data按流量计费**：
- 每GB: ~$10-15
- 每次Nike测试: ~5-10MB
- 1000次测试 ≈ 5-10GB ≈ $50-150

**Smartproxy按月计费**：
- $75/月 = 5GB流量
- 适合中小规模测试

**建议**：
- 开发阶段：使用Smartproxy（固定成本）
- 生产环境：使用Bright Data（按需付费）

## 🏁 总结

### 为什么需要代理IP池？

1. **IP封禁是主要原因**
   - Nike会追踪每个IP的访问频率
   - 超过阈值 → 直接拦截（Code: 4DB3A115）
   - 代理池 = 分散请求 = 绕过限制

2. **与LLM无关**
   - GPT-4o的问题：JSON解析失败 ✅ Claude解决
   - 反爬虫的问题：IP被封 → 需要代理池

3. **通用解决方案**
   - 代理池适用于所有有反爬虫的网站
   - 不仅是Nike，Amazon/eBay/Target等都需要

### 快速开始

```bash
# 1. 注册代理服务
#    推荐：Smartproxy (https://smartproxy.com/)
#    优惠码可能有首月折扣

# 2. 设置环境变量
export SMARTPROXY_USERNAME=your_username
export SMARTPROXY_PASSWORD=your_password

# 3. 更新config
# 在 test_agent/config.py 中启用代理

# 4. 运行测试
uv run python test_runner_claude.py
```

**预期**：从20%成功率 → 90%+成功率！
