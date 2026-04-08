"""
Proxy manager for Edge browser automation.

Responsibilities:
  1. ProxyServer / ProxyPool  — proxy pool with Webshare primary + free pool fallback
  2. init_proxy               — initialize pool at startup
  3. get_proxy                — get next proxy from pool
  4. mark_proxy_result        — record success/failure for current proxy
  5. ProxyAuthWatcher         — RAII context manager: UIA thread that auto-fills the
                                proxy auth dialog that appears before CDP can intercept it

Free proxy warning: 10-20% availability; use only for testing/dev.
"""

import asyncio
import json
import threading
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import aiohttp
try:
	import brotli  # noqa: F401
except ImportError:
	pass
from bs4 import BeautifulSoup

from browser_use.browser.profile import ProxySettings


# Webshare proxy credentials
WEBSHARE_API_KEY = 'itrqt4v8grbbk0zpa9xaxl9ncnd5wo20ch0yceqm'
WEBSHARE_PROXY_USERNAME = 'opxpuitp'
WEBSHARE_PROXY_PASSWORD = 'eod3m6wco1ma'


# ---------------------------------------------------------------------------
# ProxyServer
# ---------------------------------------------------------------------------

@dataclass
class ProxyServer:
	host: str
	port: int
	username: Optional[str] = None
	password: Optional[str] = None
	protocol: str = 'http'

	success_count: int = 0
	fail_count: int = 0
	last_used: Optional[datetime] = None
	blocked: bool = False
	response_time: float = 0.0

	@property
	def url(self) -> str:
		if self.username and self.password:
			return f'{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}'
		return f'{self.protocol}://{self.host}:{self.port}'

	@property
	def success_rate(self) -> float:
		total = self.success_count + self.fail_count
		return self.success_count / total if total > 0 else 0.0

	def mark_used(self, success: bool, response_time: float = 0.0) -> None:
		self.last_used = datetime.now()
		if success:
			self.success_count += 1
			self.blocked = False
			self.response_time = response_time
		else:
			self.fail_count += 1
			if self.fail_count >= 2 and self.success_rate < 0.3:
				self.blocked = True

	def __str__(self) -> str:
		return f'{self.host}:{self.port} (success_rate: {self.success_rate:.1%})'


# ---------------------------------------------------------------------------
# FreeProxyScraper
# ---------------------------------------------------------------------------

_SCRAPER_HEADERS = {
	'Accept-Encoding': 'gzip, deflate',
	'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}


class FreeProxyScraper:

	@staticmethod
	async def _scrape_free_proxy_list() -> List[ProxyServer]:
		proxies: List[ProxyServer] = []
		try:
			timeout = aiohttp.ClientTimeout(total=30)
			async with aiohttp.ClientSession(timeout=timeout, headers=_SCRAPER_HEADERS) as session:
				async with session.get('https://free-proxy-list.net/') as resp:
					soup = BeautifulSoup(await resp.text(), 'html.parser')
					table = soup.find('table', {'class': 'table'})
					if not table:
						return []
					for row in table.find_all('tr')[1:]:
						cols = row.find_all('td')
						if len(cols) >= 7:
							try:
								proxies.append(ProxyServer(
									host=cols[0].text.strip(),
									port=int(cols[1].text.strip()),
									protocol='https' if 'yes' in cols[6].text.lower() else 'http',
								))
							except (ValueError, AttributeError):
								continue
			print(f'[ProxyScraper] Scraped {len(proxies)} from free-proxy-list.net')
		except Exception as e:
			print(f'[ProxyScraper] free-proxy-list.net error: {e}')
		return proxies

	@staticmethod
	async def _scrape_proxyscrape() -> List[ProxyServer]:
		proxies: List[ProxyServer] = []
		url = 'https://api.proxyscrape.com/v2/?request=get&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all'
		try:
			timeout = aiohttp.ClientTimeout(total=30)
			async with aiohttp.ClientSession(timeout=timeout, headers=_SCRAPER_HEADERS) as session:
				async with session.get(url) as resp:
					for line in (await resp.text()).strip().split('\n'):
						line = line.strip()
						if ':' in line:
							try:
								host, port = line.split(':')
								proxies.append(ProxyServer(host=host.strip(), port=int(port.strip())))
							except (ValueError, AttributeError):
								continue
			print(f'[ProxyScraper] Scraped {len(proxies)} from proxyscrape.com')
		except Exception as e:
			print(f'[ProxyScraper] proxyscrape.com error: {e}')
		return proxies

	@staticmethod
	async def _test_proxy(proxy: ProxyServer, test_url: str = 'https://www.nike.com', timeout: float = 10.0) -> tuple[bool, float]:
		t0 = asyncio.get_event_loop().time()
		try:
			async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout), headers=_SCRAPER_HEADERS) as session:
				async with session.get(test_url, proxy=proxy.url) as resp:
					if resp.status == 200:
						return True, asyncio.get_event_loop().time() - t0
		except Exception:
			pass
		return False, 0.0

	@classmethod
	async def scrape_and_verify(cls, max_proxies: int = 50, concurrent_tests: int = 20) -> List[ProxyServer]:
		print(f'[ProxyScraper] Scraping (target={max_proxies})...')
		results = await asyncio.gather(cls._scrape_free_proxy_list(), cls._scrape_proxyscrape(), return_exceptions=True)
		all_proxies = []
		for r in results:
			if isinstance(r, list):
				all_proxies.extend(r)
		# deduplicate
		seen: dict = {}
		for p in all_proxies:
			seen.setdefault(f'{p.host}:{p.port}', p)
		all_proxies = list(seen.values())
		print(f'[ProxyScraper] {len(all_proxies)} unique proxies, testing...')

		working: List[ProxyServer] = []
		for i in range(0, len(all_proxies), concurrent_tests):
			batch = all_proxies[i:i + concurrent_tests]
			test_results = await asyncio.gather(*[cls._test_proxy(p) for p in batch])
			for proxy, (ok, rt) in zip(batch, test_results):
				if ok:
					proxy.mark_used(success=True, response_time=rt)
					working.append(proxy)
					print(f'[ProxyScraper] ✓ {proxy.host}:{proxy.port} ({rt:.2f}s)')
					if len(working) >= max_proxies:
						break
			if len(working) >= max_proxies:
				break
			await asyncio.sleep(0.5)

		working.sort(key=lambda p: p.response_time)
		print(f'[ProxyScraper] {len(working)} working proxies found')
		return working


# ---------------------------------------------------------------------------
# ProxyPool
# ---------------------------------------------------------------------------

class ProxyPool:

	def __init__(self, proxies: List[ProxyServer]):
		self.proxies = proxies
		self.current_index = 0
		self.lock = asyncio.Lock()

	@classmethod
	async def create_from_free_sources(cls, max_proxies: int = 30) -> 'ProxyPool':
		print(f'[ProxyPool] Building free pool (target={max_proxies})...')
		proxies = await FreeProxyScraper.scrape_and_verify(max_proxies=max_proxies)
		if not proxies:
			print('[ProxyPool] Warning: no working free proxies found')
		return cls(proxies)

	async def get_proxy(self) -> Optional[ProxyServer]:
		async with self.lock:
			if not self.proxies:
				return None
			available = [p for p in self.proxies if not p.blocked]
			if not available:
				# reset top third by success rate
				self.proxies.sort(key=lambda p: p.success_rate, reverse=True)
				for p in self.proxies[:max(1, len(self.proxies) // 3)]:
					p.blocked = False
					p.fail_count = 0
				available = [p for p in self.proxies if not p.blocked]
			if not available:
				return None
			self.current_index = (self.current_index + 1) % len(available)
			return available[self.current_index]

	async def mark_result(self, proxy: ProxyServer, success: bool, response_time: float = 0.0) -> None:
		async with self.lock:
			proxy.mark_used(success, response_time)

	def get_stats(self) -> dict:
		total = len(self.proxies)
		if not total:
			return {'total': 0, 'available': 0, 'blocked': 0, 'avg_success_rate': 0.0}
		blocked = sum(1 for p in self.proxies if p.blocked)
		return {
			'total': total,
			'available': total - blocked,
			'blocked': blocked,
			'avg_success_rate': sum(p.success_rate for p in self.proxies) / total,
		}


# ---------------------------------------------------------------------------
# Module-level proxy state
# ---------------------------------------------------------------------------

_proxy_pool: Optional[ProxyPool] = None
_current_proxy: Optional[ProxyServer] = None


async def init_proxy(
	webshare_api_key: str,
	webshare_username: str,
	webshare_password: str,
	max_free_proxies: int = 30,
) -> None:
	"""Initialize proxy pool: Webshare primary, free pool fallback."""
	global _proxy_pool

	try:
		url = 'https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&country_code__in=US&page_size=25'
		req = urllib.request.Request(url, headers={'Authorization': f'Token {webshare_api_key}'})
		loop = asyncio.get_event_loop()
		response_text = await loop.run_in_executor(
			None, lambda: urllib.request.urlopen(req, timeout=10).read().decode()
		)
		proxies = [
			ProxyServer(
				host=item['proxy_address'],
				port=item['port'],
				username=webshare_username,
				password=webshare_password,
			)
			for item in json.loads(response_text).get('results', [])
		]
		if proxies:
			_proxy_pool = ProxyPool(proxies=proxies)
			print(f'[Proxy] Webshare pool ready: {len(proxies)} US proxies')
			return
		print('[Proxy] Webshare returned 0 proxies, falling back to free pool...')
	except Exception as e:
		print(f'[Proxy] Webshare init failed ({e}), falling back to free pool...')

	_proxy_pool = await ProxyPool.create_from_free_sources(max_proxies=max_free_proxies)
	if _proxy_pool:
		stats = _proxy_pool.get_stats()
		print(f'[Proxy] Free pool ready: {stats["available"]}/{stats["total"]} proxies')


async def get_proxy() -> Optional[ProxySettings]:
	"""Return next proxy from pool, or None if not initialised."""
	global _current_proxy
	if not _proxy_pool:
		return None
	proxy = await _proxy_pool.get_proxy()
	if proxy:
		_current_proxy = proxy
		return ProxySettings(
			server=f'{proxy.protocol}://{proxy.host}:{proxy.port}',
			username=proxy.username,
			password=proxy.password,
		)
	return None


async def mark_proxy_result(success: bool, response_time: float = 0.0) -> None:
	"""Record outcome for the proxy returned by the last get_proxy() call."""
	global _current_proxy
	if _current_proxy and _proxy_pool:
		await _proxy_pool.mark_result(_current_proxy, success, response_time)
		_current_proxy = None


# ---------------------------------------------------------------------------
# ProxyAuthWatcher — UIA dialog auto-handler
# ---------------------------------------------------------------------------

class ProxyAuthWatcher:
	"""RAII context manager: UIA thread that auto-fills the proxy auth dialog.

	The dialog appears during Edge session restore before CDP attaches, so
	Fetch.authRequired cannot intercept it. UIA polls, fills credentials, clicks Sign in.

	Accepts a ProxySettings object or None. If None or credentials are missing, becomes a no-op.
	"""

	def __init__(self, proxy_settings: Optional['ProxySettings'] = None):
		self._username = proxy_settings.username if proxy_settings else None
		self._password = proxy_settings.password if proxy_settings else None
		self._thread: threading.Thread | None = None
		if self._username and self._password:
			self._thread = _start_watcher(self._username, self._password)

	def __enter__(self) -> 'ProxyAuthWatcher':
		return self

	def __exit__(self, *_) -> None:
		if self._thread:
			self._thread.stop_event.set()  # type: ignore[attr-defined]
			self._thread = None

	def start(self) -> None:
		pass  # thread already started in __init__

	def stop(self) -> None:
		self.__exit__(None, None, None)


def _start_watcher(username: str, password: str) -> threading.Thread:
	stop_event = threading.Event()

	def _watch():
		import comtypes
		import comtypes.client
		try:
			comtypes.CoInitialize()
			uia = comtypes.client.CreateObject(
				'{ff48dba4-60ef-4201-aa87-54103eef594e}',
				interface=comtypes.gen.UIAutomationClient.IUIAutomation,
			)
			name_prop = comtypes.gen.UIAutomationClient.UIA_NamePropertyId
			ctrl_prop = comtypes.gen.UIAutomationClient.UIA_ControlTypePropertyId
			button_ctrl = comtypes.gen.UIAutomationClient.UIA_ButtonControlTypeId
		except Exception as e:
			print(f'[ProxyAuthWatcher] UIA init failed: {e}')
			return

		print('[ProxyAuthWatcher] Started, watching for proxy auth dialog...')
		poll_count = 0
		while not stop_event.is_set():
			try:
				root = uia.GetRootElement()
				cond = uia.CreatePropertyCondition(name_prop, 'Sign in to access this site')
				dialog = root.FindFirst(comtypes.gen.UIAutomationClient.TreeScope_Descendants, cond)
				if dialog:
					print('[ProxyAuthWatcher] Dialog found, filling credentials...')
					try:
						edit_cond = uia.CreatePropertyCondition(
							ctrl_prop, comtypes.gen.UIAutomationClient.UIA_EditControlTypeId
						)
						edits = dialog.FindAll(comtypes.gen.UIAutomationClient.TreeScope_Descendants, edit_cond)
						print(f'[ProxyAuthWatcher] Found {edits.Length} edit field(s)')
						if edits.Length >= 1:
							vp = edits.GetElement(0).GetCurrentPattern(comtypes.gen.UIAutomationClient.UIA_ValuePatternId)
							vp.QueryInterface(comtypes.gen.UIAutomationClient.IUIAutomationValuePattern).SetValue(username)
							print(f'[ProxyAuthWatcher] Set username={username!r}')
						if edits.Length >= 2:
							vp = edits.GetElement(1).GetCurrentPattern(comtypes.gen.UIAutomationClient.UIA_ValuePatternId)
							vp.QueryInterface(comtypes.gen.UIAutomationClient.IUIAutomationValuePattern).SetValue(password)
							print('[ProxyAuthWatcher] Set password')
					except Exception as e:
						print(f'[ProxyAuthWatcher] Failed to fill credentials: {e}')
					btn_cond = uia.CreatePropertyCondition(ctrl_prop, button_ctrl)
					buttons = dialog.FindAll(comtypes.gen.UIAutomationClient.TreeScope_Descendants, btn_cond)
					print(f'[ProxyAuthWatcher] Found {buttons.Length} button(s)')
					for i in range(buttons.Length):
						btn = buttons.GetElement(i)
						btn_name = btn.CurrentName or ''
						print(f'[ProxyAuthWatcher]   button[{i}]: {btn_name!r}')
						if 'sign in' in btn_name.lower():
							invoke = btn.GetCurrentPattern(comtypes.gen.UIAutomationClient.UIA_InvokePatternId)
							invoke.QueryInterface(comtypes.gen.UIAutomationClient.IUIAutomationInvokePattern).Invoke()
							print('[ProxyAuthWatcher] ✅ Clicked Sign in')
							stop_event.set()
							break
				else:
					poll_count += 1
					if poll_count % 20 == 0:
						print(f'[ProxyAuthWatcher] Still watching... ({poll_count} polls)')
			except Exception as e:
				print(f'[ProxyAuthWatcher] Error: {e}')
			stop_event.wait(0.5)

		comtypes.CoUninitialize()
		print('[ProxyAuthWatcher] Stopped')

	t = threading.Thread(target=_watch, daemon=True, name='proxy-auth-watcher')
	t.start()
	t.stop_event = stop_event  # type: ignore[attr-defined]
	return t
