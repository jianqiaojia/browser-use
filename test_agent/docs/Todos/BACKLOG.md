# Backlog

优先级从上到下，同优先级按编号排。

---

## P0 — 立即需要

### 0. Azure VM 部署 + POC 验证
在 Azure 上部署 Windows VM，跑通完整测试流程，验证云端可行性。

### 0. 解决无人值守问题
当前测试需要保持远程桌面连接（RDP/VNC），会话断开后浏览器失去焦点导致失败。
目标：测试全程无需人工在线，支持计划任务或 CI 触发后自动完成。
- 候选方案：虚拟显示（XVFB / Windows headless）、后台服务化、Windows Task Scheduler

---

## P1 — 近期

### 1. 修复第二次 replay 稳定性
当前已知问题：replay 时 cdp_click 后 autofill popup 有时不出现。
根本原因调查中：CDP mouse event 不能可靠触发 DOM `focusin`，特别是页面上已有其他 input 持有焦点时。
候选修复：cdp_click 鼠标事件后追加 JS `el.focus()` 强制 DOM focus。
相关文件：`test_agent/actions/cdp_click.py`

### 2. 双 Profile + 精准清 Cookie（电商全程 replay）
对 Nike 等电商 site，用独立 profile 保留登录态 + 购物车，只清 autofill 相关 cookie。
这样可以省掉 Phase 1，整个流程全程 replay，更快更稳定。

**适合全程 Replay（inline_sites 中 ~36%）**：
nike.com、target.com、kohls.com、homedepot.com、lowes.com、wayfair.com、
jcpenney.com、fanatics.com、bathandbodyworks.com、etsy.com、staples.com、
mcafee.com、bedbathandbeyond.com

**需验证**：amazon.com、shop.app、checkout.stripe.com、paypal.com、dominos/papajohns/pizzahut、ebay

**不适合（保留 Phase 1 LLM）**：
expedia.com、delta.com、britishairways.com、ryanair.com、hilton.com、marriott.com、
ihg.com、hotels.com、secure.booking.com — 航班/酒店价格+库存实时变，内容语义每次不同，
只能 replay autofill 本身那几步，pre-checkout 必须 LLM 重新探索。

详见：`ROADMAP_SCRIPT_AND_SELFHEAL.md` → 潜在优化章节

### 3. 提高鲁棒性 / 验证 corner case
当前只跑了主流程，需要覆盖更多边界情况：
- 购物车为空 / 有不可用商品
- Nike 要求邮箱验证码而非密码
- 网络慢 / 页面加载超时
- replay 回放元素找不到时的续跑

### 3b. 测试 autofill 失败场景
需要验证以下失败路径行为正确：

**Popup 不出现**
- `trigger_and_autofill` 重试 3 次后返回 `ActionResult(error=...)`
- Agent 应记录失败并通知 done，不应无限等待
- 验证 logmonitor 此时返回什么 state（例如 `AutofillNotTriggered`）

**Popup 出现但 Autofill 按钮未找到**
- `select_and_confirm` 返回 `{'success': True, 'warning': 'Autofill button not found'}`
- Agent 应将 warning 写入 memory，logmonitor 的 state 是否仍然 `AutofillSucceeded`？

**Autofill 填充后字段验证失败**
- logmonitor 返回 `AutofillFailed` 或其他非 Succeeded state
- Agent 是否有 fallback（手动填写字段）？还是直接 done(failed)？

**CSS selector 找不到触发字段**
- `execute_cdp_click_by_selector` 返回 `ActionResult(error='Element not found: ...')`
- Agent 是否尝试其他 selector 或上报失败？

**待补充**：各场景在 `logmonitor_wait_for_state` 超时时的实际返回值。
相关文件：`test_agent/actions/uia_autofill.py`、`test_agent/scripts/uia_helper.py`、logmonitor action

### 4. 标准化 test case 模板 + Tricks 文档
- `*.test.json` 编写规范（task_preamble、shared_steps、params 用法）
- 常见坑和 workaround（trigger field 选择、Edit 按钮展开、cdp_click vs os_click）
- 新 site 接入 checklist

### 5. 报警
测试失败时发送通知（邮件 / Teams / Webhook），支持 CI 集成。
- 失败摘要：test case 名、失败步骤、error message
- 可选：附截图或 history.json 链接

---

## P2 — 待评估

### 6. 切换回 GPT-4o
当前用 Claude（通过 LiteLLM proxy），LiteLLM token 有超额风险。
评估：GPT-4o 在 browser-use 场景下的准确率是否足够，token 成本对比。
相关文件：`test_runner.py` `--model` 参数，`llm_config.py`

### 7. 调研升级 browser-use 的必要性
当前锁定在 v0.11.8，评估是否需要跟进上游版本：
- 查看 changelog，确认是否有影响稳定性或 rerun_history 的 breaking change
- 评估升级收益（新特性、bug fix）vs 迁移成本（API 变更、现有 patch 兼容性）
- 重点关注：`Agent.rerun_history()`、`DOMInteractedElement`、`AgentHistoryList` 接口变化

---

## 持续进行

### 8. 支持更多 site / test case
Nike 稳定后逐步扩展到其他 checkout site。
参考：`test_agent/skills/EC_TRIGGER_FIELD_SKILL.md` 获取新 site 的 trigger field。

---

**维护日期**：2026-04-08
