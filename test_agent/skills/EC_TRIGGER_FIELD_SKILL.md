# EC Autofill Trigger Field 选择指南

**适用范围**：为任意使用 MSWallet Express Checkout 的 site 确定可用的 trigger field，用于 `trigger_autofill_popup` 步骤。

---

## 核心原理（来自 Edge 源码）

两个概念容易混淆，必须区分：

| 概念 | 作用 | 来源 |
|------|------|------|
| `same_page_selectors` | 整个 checkout page 的**所有** element selector | CDN 模板 `checkoutElements` 全部 |
| `trigger_selectors` | 用于判断**表单是否可见**的 selector 集合 | 由 type/triggerCondition/isTriggerElement 决定 |

### 实际触发逻辑（`InlineTriggerFieldFilter`）

```
用户 focus 某个 field
    ↓
该 field 的 field_global_id 是否在 same_page_selectors 里？
    ├── 否 → 不触发（该 field 不属于任何 EC checkout page）
    └── 是 → 继续
               ↓
           CheckFormVisibleStatus：trigger_selectors 里的 element 是否可见？
               ├── 否（表单不可见）→ 不弹 popup
               └── 是（表单可见）→ 弹出 popup ✅
```

**结论**：能触发 popup 的 field 是 `same_page_selectors` 中的**任意**字段，不限于 trigger_selectors。
`trigger_selectors` 的唯一用途是**判断表单当前是否处于可见/可填状态**。

### trigger_selectors 的构成（决定"表单可见"判断用哪个字段）

源码：`GetCheckoutCheckedSeletorName()` in `trigger_condition_utils.cc`

| page type | 默认 trigger field（用于可见性判断） |
|-----------|--------------------------------------|
| `ShippingAddress` | `address1` |
| `BillingAddress` | `address1` |
| `Payment` / `PaymentIframe` | `cardNumber` |
| `ContactInfo` | `email` |

覆盖规则（优先级高到低）：
1. CDN `triggerCondition` 字符串非空 → 解析表达式，以其中的 element 为准
2. `isTriggerElement: true` 的 element（需 site features 含 `explicitTriggerElement`）
3. 默认：上表的 type 映射

---

## 实际选哪个 field 来触发

### 可以用（`same_page_selectors` 内的任意非 Payment 字段）

对于 `ShippingAddress` 类型页面，CDN `checkoutElements` 里通常包含：
- `address1` ✅
- `email` ✅
- `firstName` / `lastName` ✅
- `phone` ✅
- `city` / `zipCode` ✅

这些字段 focus 后，只要 `address1`（trigger_selector）在页面上可见，popup 就会弹出。

### 不能用

- `Payment` / `PaymentIframe` 页面的 `cardNumber`：在 cross-origin iframe 内，`field_global_id` 无法被主 frame 的 autofill driver 匹配，且 Edge 不以 cardNumber focus 触发 ShippingAddress 的 popup
- 不在任何 checkout page 的 `checkoutElements` 里的字段

### 推荐选择顺序

```
email > firstName > address1
```

理由：
- `email` / `firstName` 通常在页面顶部，始终可见，不需要滚动
- `address1` 有时需要先点 Edit 按钮才出现
- 三者 focus 效果完全等价（只要 address1 可见，任何一个都能弹 popup）

---

## 如何为新 site 确认可用 field

### 第一步：获取 xpay CDN 模板

```
GET https://xpaywalletcdn-prod.azureedge.net/mswallet/ExpressCheckout/v1/GetSiteCheckoutData?website={site}&scenario=expressCheckout&ver=2
```

### 第二步：找到目标 checkout page（通常是 ShippingAddress）

```python
for page in data['checkout']:
    if page['type'] == 'ShippingAddress':
        same_page_fields = [e['name'] for e in page['checkoutElements']]
        # 这些字段都可以用来触发，选一个易访问的
```

### 第三步：确认 trigger_selector（表单可见性判断字段）

```
if page['triggerCondition'] != '':
    → 解析表达式，找出涉及的 element name/id（这些 element 需要在页面上可见）
elif any(e['isTriggerElement'] for e in page['checkoutElements']):
    → isTriggerElement=true 的 element 需要可见
else:
    → type='ShippingAddress' → address1 需要可见
    → type='ContactInfo'     → email 需要可见
```

trigger_selector 对应的 element **必须在页面上可见**，popup 才会弹出。如果该 element 被隐藏（如在未展开的 Edit 表单里），即使 focus 了其他字段也不会弹 popup。

---

## Nike 实例

```
ShippingAddress_1:
  type = "ShippingAddress"
  triggerCondition = ""
  isTriggerElement = false（全部为 false）
  → trigger_selector = address1（需可见）
  → same_page_fields = [address1, email, firstName, lastName, phone, city, zipCode, ...]
  → 任意 same_page_fields 中的字段 focus 均可触发，前提是 address1 可见
```

**Nike 页面行为**：默认显示已保存地址摘要（address1 不可见），需先点击 shipping 区域 Edit 按钮展开表单，address1 变为可见后，focus email/firstName/address1 任一字段即可弹出 popup。

---

## 执行步骤模板

1. 确认 trigger_selector 对应的 element 是否可见（如 address1）
2. 如不可见（页面处于摘要/折叠态），找并点击该区域的 Edit 按钮
3. 等待表单展开，trigger_selector element 变为可见
4. 选择一个易访问的字段（推荐 email 或 firstName）：clear it（type 空字符串，clear=true）
5. `cdp_click` 点击一次，等待 2 秒
6. 调用 `uia_wait_for_popup(timeout=5)`
7. 若未检测到 popup：改用 `os_click` 重试一次，等待 2 秒，再调用 `uia_wait_for_popup(timeout=5)`

**不要用 Payment/cardNumber 字段**：cross-origin iframe，无法被 EC 的 autofill driver 感知。

---

## 相关文件

- 源码：`inline_trigger_field_filter.cc` → `OnElementsQueryDone`, `CheckFormVisibleStatus`
- 源码：`trigger_condition_utils.cc` → `GetCheckoutCheckedSeletorName`, `GetPositiveElements`
- Nike 测试用例：`test_agent/test_case/nike.test.json`
- Filter profile 指南：`test_agent/skills/EC_FILTER_PROFILE_SKILL.md`
