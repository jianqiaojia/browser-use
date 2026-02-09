"""
免费代理池管理器

警告：免费代理稳定性差（10-20%可用率），仅适合测试和开发环境。
生产环境请使用商业代理服务（Bright Data, Smartproxy等）。
"""
import asyncio
import aiohttp

# Force aiohttp to use brotli if available
try:
	import brotli  # noqa: F401
	# Enable brotli support in aiohttp by importing before ClientSession
except ImportError:
	pass

from bs4 import BeautifulSoup
from typing import List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import random


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
	response_time: float = 0.0  # 响应时间（秒）

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
		return self.success_count / total if total > 0 else 0.0

	def mark_used(self, success: bool, response_time: float = 0.0):
		"""标记使用结果"""
		self.last_used = datetime.now()
		if success:
			self.success_count += 1
			self.blocked = False
			self.response_time = response_time
		else:
			self.fail_count += 1
			# 连续失败2次就标记为blocked
			if self.fail_count >= 2 and self.success_rate < 0.3:
				self.blocked = True

	def __str__(self):
		return f"{self.host}:{self.port} (success_rate: {self.success_rate:.1%})"


class FreeProxyScraper:
	"""免费代理抓取器"""

	@staticmethod
	async def scrape_free_proxy_list() -> List[ProxyServer]:
		"""
		从 free-proxy-list.net 抓取代理

		Returns:
			代理列表（未验证）
		"""
		proxies = []
		url = 'https://free-proxy-list.net/'

		try:
			timeout = aiohttp.ClientTimeout(total=30)
			# 使用自定义 headers 避免 brotli 编码
			headers = {
				'Accept-Encoding': 'gzip, deflate',  # 不接受 br (brotli)
				'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
			}
			async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
				async with session.get(url) as response:
					html = await response.text()
					soup = BeautifulSoup(html, 'html.parser')
					table = soup.find('table', {'class': 'table'})

					if not table:
						print("[ProxyScraper] Table not found")
						return []

					for row in table.find_all('tr')[1:]:  # Skip header
						cols = row.find_all('td')
						if len(cols) >= 7:
							try:
								host = cols[0].text.strip()
								port = int(cols[1].text.strip())
								https = 'yes' in cols[6].text.lower()

								proxy = ProxyServer(
									host=host,
									port=port,
									protocol='https' if https else 'http'
								)
								proxies.append(proxy)
							except (ValueError, AttributeError):
								continue

			print(f"[ProxyScraper] Scraped {len(proxies)} proxies from free-proxy-list.net")
			return proxies

		except Exception as e:
			print(f"[ProxyScraper] Error scraping free-proxy-list.net: {e}")
			return []

	@staticmethod
	async def scrape_proxy_scrape() -> List[ProxyServer]:
		"""
		从 proxyscrape.com API 获取代理

		Returns:
			代理列表（未验证）
		"""
		proxies = []
		# ProxyScrape免费API
		url = 'https://api.proxyscrape.com/v2/?request=get&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all'

		try:
			timeout = aiohttp.ClientTimeout(total=30)
			# 使用自定义 headers 避免 brotli 编码
			headers = {
				'Accept-Encoding': 'gzip, deflate',  # 不接受 br (brotli)
				'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
			}
			async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
				async with session.get(url) as response:
					text = await response.text()
					lines = text.strip().split('\n')

					for line in lines:
						line = line.strip()
						if ':' in line:
							try:
								host, port = line.split(':')
								proxy = ProxyServer(
									host=host.strip(),
									port=int(port.strip()),
									protocol='http'
								)
								proxies.append(proxy)
							except (ValueError, AttributeError):
								continue

			print(f"[ProxyScraper] Scraped {len(proxies)} proxies from proxyscrape.com")
			return proxies

		except Exception as e:
			print(f"[ProxyScraper] Error scraping proxyscrape.com: {e}")
			return []

	@staticmethod
	async def test_proxy(proxy: ProxyServer, test_url: str = 'https://www.nike.com', timeout: float = 10.0) -> tuple[bool, float]:
		"""
		测试代理是否可用

		Args:
			proxy: 代理服务器
			test_url: 测试URL（默认使用 Nike 首页）
			timeout: 超时时间（秒）

		Returns:
			(是否可用, 响应时间)
		"""
		start_time = asyncio.get_event_loop().time()
		try:
			client_timeout = aiohttp.ClientTimeout(total=timeout)
			headers = {
				'Accept-Encoding': 'gzip, deflate',
				'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
			}
			async with aiohttp.ClientSession(timeout=client_timeout, headers=headers) as session:
				async with session.get(test_url, proxy=proxy.url) as response:
					if response.status == 200:
						elapsed = asyncio.get_event_loop().time() - start_time
						return True, elapsed
					return False, 0.0
		except:
			return False, 0.0

	@staticmethod
	async def scrape_and_verify(max_proxies: int = 50, concurrent_tests: int = 20) -> List[ProxyServer]:
		"""
		抓取并验证代理（推荐使用此方法）

		Args:
			max_proxies: 最多返回多少个可用代理
			concurrent_tests: 并发测试数

		Returns:
			验证过的可用代理列表
		"""
		print(f"[ProxyScraper] Starting to scrape proxies (target: {max_proxies})...")

		# 1. 从多个源抓取
		all_proxies = []
		sources = [
			FreeProxyScraper.scrape_free_proxy_list(),
			FreeProxyScraper.scrape_proxy_scrape(),
		]

		results = await asyncio.gather(*sources, return_exceptions=True)
		for result in results:
			if isinstance(result, list):
				all_proxies.extend(result)

		if not all_proxies:
			print("[ProxyScraper] No proxies scraped!")
			return []

		print(f"[ProxyScraper] Total scraped: {len(all_proxies)}")

		# 2. 去重
		unique_proxies = {}
		for p in all_proxies:
			key = f"{p.host}:{p.port}"
			if key not in unique_proxies:
				unique_proxies[key] = p

		all_proxies = list(unique_proxies.values())
		print(f"[ProxyScraper] After deduplication: {len(all_proxies)}")

		# 3. 批量测试
		working_proxies = []

		# 分批测试
		for i in range(0, len(all_proxies), concurrent_tests):
			batch = all_proxies[i:i+concurrent_tests]
			tasks = [FreeProxyScraper.test_proxy(p) for p in batch]
			results = await asyncio.gather(*tasks)

			for proxy, (is_working, response_time) in zip(batch, results):
				if is_working:
					proxy.mark_used(success=True, response_time=response_time)
					working_proxies.append(proxy)
					print(f"[ProxyScraper] [OK] {proxy.host}:{proxy.port} ({response_time:.2f}s)")

					if len(working_proxies) >= max_proxies:
						break

			if len(working_proxies) >= max_proxies:
				break

			# 避免请求过快
			await asyncio.sleep(0.5)

		# 按响应时间排序
		working_proxies.sort(key=lambda p: p.response_time)

		print(f"[ProxyScraper] [OK] Found {len(working_proxies)} working proxies")
		return working_proxies


class ProxyPool:
	"""代理池管理器"""

	def __init__(self, proxies: List[ProxyServer]):
		"""
		Args:
			proxies: 代理服务器列表
		"""
		self.proxies = proxies
		self.current_index = 0
		self.lock = asyncio.Lock()

	@classmethod
	async def create_from_free_sources(cls, max_proxies: int = 30) -> 'ProxyPool':
		"""
		从免费源创建代理池（自动抓取并验证）

		Args:
			max_proxies: 目标代理数量

		Returns:
			ProxyPool实例
		"""
		print(f"[ProxyPool] Initializing free proxy pool (target: {max_proxies})...")
		proxies = await FreeProxyScraper.scrape_and_verify(max_proxies=max_proxies)

		if not proxies:
			print("[ProxyPool] Warning: No working proxies found!")
			return cls([])

		return cls(proxies)

	@classmethod
	def from_file(cls, filepath: str) -> 'ProxyPool':
		"""
		从文件加载代理

		文件格式（每行一个）：
		host:port
		或
		protocol://username:password@host:port

		Args:
			filepath: 代理列表文件路径

		Returns:
			ProxyPool实例
		"""
		proxies = []
		with open(filepath, 'r') as f:
			for line in f:
				line = line.strip()
				if not line or line.startswith('#'):
					continue

				try:
					if '://' in line:
						# 完整格式
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
						# 简单格式
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
				except Exception as e:
					print(f"[ProxyPool] Error parsing line '{line}': {e}")
					continue

		print(f"[ProxyPool] Loaded {len(proxies)} proxies from {filepath}")
		return cls(proxies)

	async def get_proxy(self) -> Optional[ProxyServer]:
		"""
		获取下一个可用代理（round-robin策略）

		Returns:
			ProxyServer or None
		"""
		async with self.lock:
			if not self.proxies:
				return None

			# 获取未被blocked的代理
			available = [p for p in self.proxies if not p.blocked]

			if not available:
				# 所有代理都blocked了，重置success_rate最高的几个
				self.proxies.sort(key=lambda p: p.success_rate, reverse=True)
				for p in self.proxies[:len(self.proxies)//3]:
					p.blocked = False
					p.fail_count = 0
				available = [p for p in self.proxies if not p.blocked]

			if not available:
				return None

			# Round-robin
			self.current_index = (self.current_index + 1) % len(available)
			return available[self.current_index]

	async def mark_result(self, proxy: ProxyServer, success: bool, response_time: float = 0.0):
		"""标记代理使用结果"""
		async with self.lock:
			proxy.mark_used(success, response_time)

	def get_stats(self) -> dict:
		"""获取统计信息"""
		if not self.proxies:
			return {
				'total': 0,
				'available': 0,
				'blocked': 0,
				'avg_success_rate': 0.0,
			}

		total = len(self.proxies)
		blocked = sum(1 for p in self.proxies if p.blocked)
		avg_success_rate = sum(p.success_rate for p in self.proxies) / total

		return {
			'total': total,
			'available': total - blocked,
			'blocked': blocked,
			'avg_success_rate': avg_success_rate,
		}

	def save_to_file(self, filepath: str):
		"""保存代理到文件（方便下次使用）"""
		with open(filepath, 'w') as f:
			f.write("# Free proxy list\n")
			f.write(f"# Generated at: {datetime.now()}\n")
			f.write(f"# Total proxies: {len(self.proxies)}\n\n")

			for p in self.proxies:
				# 保存统计信息作为注释
				f.write(f"# Success: {p.success_count}, Fail: {p.fail_count}, Rate: {p.success_rate:.1%}\n")
				f.write(f"{p.host}:{p.port}\n")

		print(f"[ProxyPool] Saved {len(self.proxies)} proxies to {filepath}")


# 命令行测试
async def main():
	"""测试脚本"""
	import argparse

	parser = argparse.ArgumentParser(description='Free proxy pool manager')
	parser.add_argument('--scrape', action='store_true', help='Scrape and verify proxies')
	parser.add_argument('--count', type=int, default=30, help='Target proxy count')
	parser.add_argument('--save', type=str, help='Save proxies to file')

	args = parser.parse_args()

	if args.scrape:
		# 抓取并验证
		pool = await ProxyPool.create_from_free_sources(max_proxies=args.count)

		# 显示统计
		stats = pool.get_stats()
		print(f"\n[Stats]")
		print(f"  Total: {stats['total']}")
		print(f"  Available: {stats['available']}")
		print(f"  Blocked: {stats['blocked']}")
		print(f"  Avg Success Rate: {stats['avg_success_rate']:.1%}")

		# 保存到文件
		if args.save:
			pool.save_to_file(args.save)
	else:
		print("Usage: python free_proxy_pool.py --scrape [--count 30] [--save proxies.txt]")


if __name__ == '__main__':
	asyncio.run(main())
