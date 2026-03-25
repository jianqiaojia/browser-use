# Nike Checkout Autofill Popup - 正确解决方案

## 问题

Nike checkout 页面的 email 字段点击后无法触发 Edge 的 Express Checkout autofill popup。

## ❌ 错误方案

创建自定义 `click_with_focus_action` 来手动触发 focus 事件。

**为什么错误**：Browser-use 的标准 click 已经使用 CDP 真实鼠标事件，完全可以触发 focus 事件。

## ✅ 正确方案

**多次点击 email 字段**，给页面 JavaScript 足够的初始化时间。

### 实现方式

在测试用例中使用标准 click action，连续点击 3 次，每次间隔 1 秒：

```json
{
  "step_description": "Click on the email input field multiple times to trigger the autofill popup. Use this action sequence in ONE step: click email field, wait 1 second, click email field again, wait 1 second, click email field a third time, then immediately call uia_wait_for_popup (timeout: 5 seconds). IMPORTANT: Multiple clicks are needed because the popup may not appear on the first click - the page's JavaScript needs time to initialize."
}
```

### Agent 会执行

```json
{
  "action": [
    { "click": { "index": <email_field_index> } },
    { "wait": { "seconds": 1 } },
    { "click": { "index": <email_field_index> } },
    { "wait": { "seconds": 1 } },
    { "click": { "index": <email_field_index> } },
    { "uia_wait_for_popup": { "timeout": 5.0 } }
  ]
}
```

## 为什么多次点击有效？

1. **页面 JavaScript 初始化** - Nike checkout 页面在加载后需要时间来设置 autofill 事件监听器
2. **浏览器状态激活** - 第一次点击可能激活浏览器内部状态，后续点击才触发 popup
3. **焦点竞争处理** - 多次点击确保最终焦点在正确的字段上

## 验证

此方案已在 GPT-4o 测试中验证成功（见 `test_agent/test_case/nike_checkout_page_autofill.history.json` line 1045-1070）。

## 相关文件

- 测试用例：`test_agent/test_case/checkout/nike.test.json`
- 问题分析：`test_agent/custom_actions/ENHANCED_CLICK.md`
- GPT-4o 成功日志：`test_agent/test_case/nike_checkout_page_autofill.history.json`

---

**日期**：2025-02-09
**状态**：✅ 已验证有效
