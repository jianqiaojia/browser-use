# EC Autofill Filter Profile 构建指南

**适用范围**：为任意使用 MSWallet Express Checkout 模板的 site 构建 invalid test profile，精确触发各字段的 filter reason code，用于验证 Edge autofill popup 的 profile filtering 功能。

---

## 第一步：获取 site 的 filter 模板

xpay CDN 端点，无需鉴权，直接 GET：

```
https://xpaywalletcdn-prod.azureedge.net/mswallet/ExpressCheckout/v1/GetSiteCheckoutData?website={site}&scenario=expressCheckout&ver=2
```

示例（Nike）：
```
curl "https://xpaywalletcdn-prod.azureedge.net/mswallet/ExpressCheckout/v1/GetSiteCheckoutData?website=nike.com&scenario=expressCheckout&ver=2"
```

响应中找 `pages` → `ShippingAddress_1` → `elements`，每个字段关注三个属性：

| 属性 | 含义 |
|------|------|
| `filterRule` | v1：直接正则字符串，如 `"^[a-zA-Z\\s]{2,40}$"` |
| `filterPolicies` | v2：数组，每项含 `type` / `parameter` / `precondition` |
| `isMandatory` | `true` = 字段为空也会被过滤（NonEmpty 检查） |

---

## 第二步：理解过滤逻辑链

来源：`shipping_address_form.cc` — `ProfileFilterPolicy` 构建逻辑。

每个 mandatory 字段依次经过：

```
1. NonEmptyProfileFilter  → 字段值为空字符串 → FILTERED
2. RegexProfileFilter     → filterRule 不匹配 → FILTERED（仅当 filterRule 存在）
3. Policy 链（filterPolicies）：
   - Basic    → email 格式验证：^[^\s@]+@[^\s@]+\.[^\s@]+$
   - Regex    → 自定义正则（可带 precondition）
   - Whitelist → 值必须在 parameters 列表中
   - Blacklist → 值不能在 parameters 列表中
```

**precondition**：`{"key": "country", "op": "eq", "value": "US"}` — 仅当另一字段满足条件时才执行本 policy。如果 precondition 不满足，该 policy 跳过（不过滤）。

---

## 第三步：TriggerFailedReason 代码表

来源：`wallet_checkout_trigger_funnel_manager.h`，仅列 profile 字段相关部分：

| Code | 枚举名 | 对应字段 |
|------|--------|---------|
| 23 | INVALID_PROFILE_FIRSTNAME | firstName |
| 24 | INVALID_PROFILE_LASTNAME | lastName |
| 25 | INVALID_PROFILE_FULLNAME | fullName |
| 26 | INVALID_PROFILE_EMAIL | email |
| 27 | INVALID_PROFILE_PHONE | phone |
| 28 | INVALID_PROFILE_COUNTRY | country |
| 29 | INVALID_PROFILE_STREET_ADDRESS | address1 |
| 30 | INVALID_PROFILE_CITY | city |
| 31 | INVALID_PROFILE_ZIP | zipCode |
| 32 | INVALID_PROFILE_STATE | state |
| 33 | INVALID_PROFILE_ADDRESS_MAPPING | — |
| 34 | NO_PROFILE | — |
| 35 | INSUFFICIENT_PROFILE_FIELDS | — |

Log 中对应：
```
ec-trigger profile <guid> failed reason: 31
ec-trigger profile <guid> is valid profile
```

---

## 第四步：构建 invalid profile 的决策流程

**原则：最小破坏** — 每个 invalid profile 只破坏一个字段，其余字段全部合法。

```
对每个要测试的字段：
  1. 查 filterRule / filterPolicies
  2. 选一个"恰好违反"该规则的值：
     - Regex：选不匹配的最短字符串（如单个数字 "1" 违反 alpha-only 规则）
     - Basic（email）：去掉 @ 符号
     - Regex with length：选长度不足或含非法字符的值
     - Whitelist：选一个不在列表中的值
     - Blacklist：选列表中的任意一个值
  3. 确认其他字段的值对该 site 合法（参考同 site 的有效 profile）
  4. 记录预期 reason code
```

**注意**：`isMandatory=false` 的字段（如 state、country）过滤失败不一定阻断整个 profile，具体行为取决于 C++ 逻辑版本，构建时优先选 `isMandatory=true` 的字段。

---

## Nike 完整实例

### 字段规则（来自 xpay CDN，2026-03）

| 字段 | 规则类型 | 规则内容 | isMandatory |
|------|---------|---------|------------|
| firstName | filterRule | `^[a-zA-Z\s]{2,40}$` | true |
| lastName | filterRule | `^[a-zA-Z\s]{2,40}$` | true |
| city | filterRule | `^[a-zA-Z\s]{2,25}$` | true |
| address1 | filterRule | `^[a-zA-Z0-9\,\s]{2,35}$` | true |
| phone | filterRule | `^[0-9\(\)\-\s\+]{1,}$` | true |
| email | filterPolicies | Basic（`^[^\s@]+@[^\s@]+\.[^\s@]+$`） | true |
| zipCode | filterPolicies | Regex `^\d{5}$`（precondition: country=US） | true |
| state | filterPolicies | Whitelist（US 各州缩写）（precondition: country=US） | false |
| country | filterPolicies | Blacklist `["JP", "KR", "GB"]` | false |

### 5 个 invalid profile（针对 Nike）

| Profile | 破坏字段 | 使用值 | 违反规则 | 预期 reason |
|---------|---------|------|---------|------------|
| P1 | firstName | `"1"` | 数字不匹配 `^[a-zA-Z\s]{2,40}$` | 23 |
| P2 | lastName | `"1"` | 同上 | 24 |
| P3 | email | `"notanemail"` | 无 `@`，不匹配 Basic filter | 26 |
| P4 | zipCode | `"9805X"` | 含非数字字符，不匹配 `^\d{5}$` | 31 |
| P5 | city | `"1"` | 数字 + 长度<2，不匹配 `^[a-zA-Z\s]{2,25}$` | 30 |

**为什么不用 `phone="1"`**：Nike 的 phone 规则是 `^[0-9\(\)\-\s\+]{1,}$`，最少 1 位且允许纯数字，`"1"` 合法，无法触发过滤。

---

## 新 site 操作 Checklist

```
□ 1. curl xpay CDN，替换 website= 参数
□ 2. 找 ShippingAddress_1 → elements，逐字段记录 filterRule / filterPolicies / isMandatory
□ 3. 对照 TriggerFailedReason 代码表，确定要覆盖的 reason code（优先 mandatory 字段）
□ 4. 为每个目标 reason code 选一个最小破坏值
□ 5. 注意 precondition：如果规则依赖 country=US，确保 profile 的 country 字段是 US
□ 6. 在 Edge 中手动创建这些 profile（Settings → Addresses and more）
□ 7. 在 test_case/<site>.test.json 的 Nike_autofill_Signed_In 的 test_case_description 中
     写明每个 profile 的字段值和预期 reason（参考下方 JSON 模板）
□ 8. 运行测试，调用 logmonitor_get_filter_results 确认结果（参考下方验证方法）
```

---

## test_case_description 写法模板

在 `test_case/<site>.test.json` 的 `test_case_description` 字段中，Preconditions 部分按如下格式描述 invalid profile：

```
Preconditions: (1) Edge has at least one fully valid saved address.
(2) Edge also has N additional saved address profiles each with exactly one
invalid field (all other fields valid):
  firstName='1'   (fails ^[a-zA-Z\s]{2,40}$, reason=23),
  lastName='1'    (fails ^[a-zA-Z\s]{2,40}$, reason=24),
  email='notanemail' (no @ sign, fails Basic filter, reason=26),
  zipCode='9805X' (non-digit char, fails ^\d{5}$, reason=31),
  city='1'        (digit, fails ^[a-zA-Z\s]{2,25}$, reason=30).
```

每项格式：`字段='值'  (违反原因描述, reason=<code>)`

---

## 验证方法：logmonitor_get_filter_results 返回结构

调用 `logmonitor_get_filter_results` 后，agent 会收到如下结构：

```json
{
  "failed_profiles": {
    "<guid-1>": 23,
    "<guid-2>": 24,
    "<guid-3>": 26,
    "<guid-4>": 31,
    "<guid-5>": 30
  },
  "valid_profiles": ["<guid-valid>"],
  "db_profiles": {
    "<guid-1>": {"firstName": "1", "lastName": "Smith", ...},
    ...
  }
}
```

**判断通过的条件**：
- `failed_profiles` 中每个 invalid guid 的 reason code 与预期一致
- `valid_profiles` 至少有 1 个 guid（存在合法 profile）
- 没有 invalid profile 出现在 `valid_profiles` 中

---

## 相关文件

- 过滤 action 实现：`test_agent/register_custom_actions.py` → `logmonitor_get_filter_results`
- log 解析器：`test_agent/scripts/log_file_monitor.py`
- Nike 测试用例：`test_agent/test_case/nike.test.json`
