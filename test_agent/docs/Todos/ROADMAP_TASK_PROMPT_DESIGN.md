# Roadmap：Task Prompt 设计

## 核心设计原则（新）

**步骤描述不应该描述路径，只应该描述约束。**

导航路径（怎么找到 checkout、怎么展开地址表单、怎么填 cart）属于 `replay.json` 的职责——由 explore 阶段让 LLM 自由探索后固化。在 step 描述里用自然语言硬编码路径，等于用 prompt engineering 写了一份劣化版的 replay.json，而且还不稳定。

三层职责划分：

```
task_preamble.txt     ← 最终目标 + 优先级心智模型（全局，不变）
*.test.json           ← 这个 test case 的特殊性（工具调用约束 + site/case 说明）
replay.json           ← 怎么做（路径）——由 explore 生成，不在 prompt 里描述
```

---

## 整体架构

```
test_agent/test_case/
├── actions.json         ← 全局 action 调用约束库（什么时候/为什么调用某个 action）
├── task_preamble.txt    ← 全局 preamble（LLM 目标 + 优先级）
├── nike.test.json       ← Nike：最终目标 + case 特殊性说明 + action 调用顺序
└── adidas.test.json     ← Adidas：同上
```

### 不再需要的概念

- `common_steps.json`：step 描述本质上是在用 prompt 替代 replay.json 的工作，废弃
- `step_description` 里的路径指引：这是 explore 的工作
- `{site_specific_hint}` 占位符注入路径细节：路径不应该在 prompt 里

---

## task_preamble.txt（✅ 保持不变）

给 LLM 建立正确的优先级心智模型：前置步骤是前置条件，核心目标是
到达 checkout → trigger popup → 点击 → 验证。

---

## *.test.json 新设计

极简。只写两件事：

1. **`description`**：这个 test case 的特殊性——site 的 UI 特点、preconditions、
   已知卡点的提示。LLM 在 explore 时可以参考，但不约束路径。

2. **`action_sequence`**：必须按顺序调用的 action 列表（工具调用约束），
   不含路径描述，只含 action 名 + 触发时机说明（可选）。

```json
{
    "test_cases": [
        {
            "name": "Nike_autofill_Guest",
            "description": "Guest checkout. Nike shows a saved address list by default; click Edit on an existing address to expand the inline form and expose the email/firstName input.",
            "action_sequence": [
                "clear_site_data",
                "logmonitor_init",
                "uia_wait_for_popup",
                "uia_select_autofill",
                "logmonitor_wait_for_state"
            ]
        },
        {
            "name": "Nike_autofill_Signed_In",
            "description": "Signed-in user. Preconditions: one fully valid saved address in Edge, plus 5 profiles each with exactly one invalid field (name/zip/phone/email/city). Expect all 5 invalid profiles to be filtered before autofill popup appears.",
            "action_sequence": [
                "email_mark_baseline",
                "clear_site_data",
                "logmonitor_init",
                "uia_wait_for_popup",
                "logmonitor_get_filter_results",
                "uia_select_autofill",
                "logmonitor_wait_for_state"
            ]
        }
    ]
}
```

LLM 拿到的 task 字符串只有：
- preamble（目标 + 优先级）
- case description（特殊性说明）
- action_sequence（必须调用的 action 及顺序）
- 每个 action 的 description（来自 register_custom_actions.py 的 @tools.action(description=...)）

---

## actions.json（替代 common_steps.json）

不描述路径，只描述**每个 action 的触发时机**——补充 register_custom_actions.py 里
action description 里说不清楚的上下文。

```json
{
    "email_mark_baseline": "Call before any login step that will trigger a verification email.",
    "clear_site_data": "Call at the start of guest-mode test cases to ensure unauthenticated state.",
    "logmonitor_init": "Call before navigating to checkout, so log monitoring is ready before autofill is triggered.",
    "uia_wait_for_popup": "Call immediately after focusing a checkout input field (email or firstName).",
    "logmonitor_get_filter_results": "Call after uia_wait_for_popup detects the popup but before uia_select_autofill."
}
```

---

## explore → refine → replay 流程（不变）

```
EXPLORE:  LLM 自由探索，找到完成 action_sequence + 最终目标的路径
            ↓
REFINE:   HistoryRefiner 清理冗余步骤，保留 protected actions
            ↓
REPLAY:   确定性回放，失败时 heal + merge
```

replay.json 才是"怎么做"的权威来源。prompt 只负责"做什么"和"为什么"。

---

## 新旧对比

| | 旧设计 | 新设计 |
|---|---|---|
| step 描述 | 详细路径指引（"click Edit to expand"） | 无路径描述 |
| site 特殊性 | `{site_specific_hint}` 占位符注入 | `description` 字段直接写 |
| action 顺序 | step 列表（含路径步骤） | `action_sequence`（纯 action 名列表） |
| 路径存储 | prompt 里的自然语言 | replay.json |
| 新 site 成本 | 需要写详细 step 描述 | 只需写 description + action_sequence |

---

**维护日期**：2026-04-01
