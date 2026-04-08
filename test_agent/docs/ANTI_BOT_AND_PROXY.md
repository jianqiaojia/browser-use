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

## 代理认证弹框问题（已解决）

### 问题描述

启用需要用户名/密码的 HTTP 代理（如 Webshare direct 模式）时，Edge 会弹出系统级认证对话框：

```
Sign in to access this site
The proxy http://198.23.239.134:6540 requires a username and password.
```

### 根本原因

**Chromium 源码层面的限制**（`devtools_url_loader_interceptor.cc:2177`）：

```cpp
if (!stages_.Has(InterceptionStage::kRequest) || !interceptor_ ||
    !interceptor_->handle_auth_) {
  std::move(callback).Run(true, std::nullopt);  // 直接弹框
  return;
}
```

CDP `Fetch.authRequired` 只在请求被匹配到 URL pattern 时才触发。  
但 Edge 启动时恢复上次 session 的请求，走的是原始 `URLLoaderFactory`，不经过 `DevToolsURLLoaderFactoryProxy`，因此根本没有 `InterceptionJob`，完全绕过 CDP。

更深层原因：`kill_edge_processes()` 强杀 Edge 进程，Edge 将其记录为 `exit_type: Crashed`，下次启动强制恢复 session，在 CDP attach 之前就发出代理认证请求。

### 解决方案：`ProxyAuthWatcher`

位于 `test_agent/scripts/proxy_manager.py`。

**原理**：RAII 上下文管理器，启动一个后台 UIA 线程，持续监视"Sign in to access this site"对话框。一旦出现，自动填写用户名密码并点击 Sign in。

```python
from test_agent.scripts.proxy_manager import ProxyAuthWatcher

with ProxyAuthWatcher(username='opxpuitp', password='eod3m6wco1ma'):
    await browser_session.start()
    # ... run tests
# 退出 with 块时自动停止 UIA 线程
```

`test_runner.py` 中已集成，启用 `--use-proxy` 时自动生效。

---

## 方案一：Webshare 商业代理（当前主力）

### 快速启用

```bash
python test_agent/test_runner.py --use-proxy
```

### 工作原理

```
启动时从 Webshare API 拉取 US 代理列表
    ↓
初始化 ProxyPool（round-robin 轮换）
    ↓
每个 test case 获取一个代理
    ↓
BrowserProfile(proxy=ProxySettings(...))
    ↓
ProxyAuthWatcher 自动处理认证弹框
    ↓
记录成功/失败，更新代理统计
```

### 配置（`test_agent/scripts/proxy_manager.py`）

```python
WEBSHARE_API_KEY = 'itrqt4v8grbbk0zpa9xaxl9ncnd5wo20ch0yceqm'
WEBSHARE_PROXY_USERNAME = 'opxpuitp'
WEBSHARE_PROXY_PASSWORD = 'eod3m6wco1ma'
```

---

## 方案二：免费代理池（fallback / 开发测试用）

当 Webshare 不可用时自动 fallback。也可单独使用（不推荐生产）。

### 快速启用

```bash
# --use-proxy 会先尝试 Webshare，失败则自动 fallback 到免费池
python test_agent/test_runner.py --use-proxy
```

### 工作原理

```
Webshare 初始化失败
    ↓
自动抓取免费代理
    ├─→ free-proxy-list.net (HTML 表格)
    └─→ proxyscrape.com (API)
    ↓
去重（500+ → 300+）
    ↓
并发验证（20 个/批，测试 https://www.nike.com）
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

### 在代码中集成

```python
from test_agent.scripts.proxy_manager import init_proxy, get_proxy, mark_proxy_result
from test_agent.scripts.proxy_manager import WEBSHARE_API_KEY, WEBSHARE_PROXY_USERNAME, WEBSHARE_PROXY_PASSWORD

async def main():
    # 初始化代理池（Webshare 优先，free pool fallback）
    await init_proxy(
        webshare_api_key=WEBSHARE_API_KEY,
        webshare_username=WEBSHARE_PROXY_USERNAME,
        webshare_password=WEBSHARE_PROXY_PASSWORD,
    )

    # 获取代理
    proxy_settings = await get_proxy()
    if proxy_settings:
        browser_config['proxy'] = proxy_settings

    # 创建 BrowserSession
    with ProxyAuthWatcher(proxy_settings.username, proxy_settings.password):
        browser_session = BrowserSession(browser_profile=BrowserProfile(**browser_config))
        await browser_session.start()
        # ... run tests
        await mark_proxy_result(success=True)
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

---

## 方案三：其他商业住宅代理

| 服务商 | 类型 | 月费 | IP 池大小 | 推荐度 |
|--------|------|------|---------|--------|
| Webshare | 住宅/数据中心 | $20+ | 3000 万+ | ⭐⭐⭐⭐⭐（当前使用） |
| Bright Data | 住宅 | $500+ | 7200 万+ | ⭐⭐⭐⭐⭐ |
| Smartproxy | 住宅 | $75+ | 4000 万+ | ⭐⭐⭐⭐⭐ |
| Oxylabs | 住宅 | $300+ | 1 亿+ | ⭐⭐⭐⭐⭐ |
| IPRoyal | 住宅 | $7/GB | 200 万+ | ⭐⭐⭐⭐ |

**对于 Nike 等 Akamai 保护的网站，必须使用住宅代理，数据中心 IP 会被立即封禁。**

### Bright Data 配置示例

```python
from browser_use.browser.profile import ProxySettings

proxy = ProxySettings(
    server="http://brd.superproxy.io:22225",
    username="brd-customer-{CUSTOMER_ID}-zone-residential-country-us",
    password="YOUR_PASSWORD",
)
```

---

## 方案四：反检测浏览器配置（配合代理使用）

```python
# test_agent/config.py → get_browser_profile_config()
'args': [
    '--disable-blink-features=AutomationControlled',
    '--exclude-switches=enable-automation',
    '--disable-infobars',
]
```

### 注入反检测脚本（高级）

```javascript
// 在页面加载前注入，隐藏自动化特征
Object.defineProperty(navigator, 'webdriver', { get: () => false });
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
```

---

## 方案对比

| 方案 | 成本 | 效果 | 稳定性 | 适用场景 |
|------|------|------|--------|---------|
| 免费代理池 | 免费 | ⭐⭐ 20-30% | ⭐ 差 | 开发测试 |
| 反检测配置 | 免费 | ⭐⭐⭐ 50-60% | ⭐⭐⭐ | 简单网站 |
| Webshare 商业代理 | $20+/月 | ⭐⭐⭐⭐ 90%+ | ⭐⭐⭐⭐ | 当前主力 |
| 住宅代理 + 反检测 | $75-500+/月 | ⭐⭐⭐⭐⭐ 99%+ | ⭐⭐⭐⭐⭐ | 严格网站 |

---

## 相关文件

- `test_agent/scripts/proxy_manager.py` — 代理池 + ProxyAuthWatcher 实现
- `test_agent/test_runner.py` — `--use-proxy` 入口
- `CLAUDE_SETUP.md` — Claude 模型配置
- `USER_DATA_DIR_SOLUTION.md` — Browser profile 污染问题
- `RDP_Session_Management.md` — RDP 环境下的特殊问题
