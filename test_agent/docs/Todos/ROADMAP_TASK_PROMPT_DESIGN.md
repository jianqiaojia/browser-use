# Roadmap：Task Prompt 设计

## 核心设计原则

**步骤描述不应该描述路径，只应该描述约束。**

导航路径（怎么找到 checkout、怎么展开地址表单、怎么填 cart）属于 `replay.json` 的职责——由 explore 阶段让 LLM 自由探索后固化。在 prompt 里用自然语言硬编码路径，等于写了一份劣化版的 replay.json，而且不稳定。

三层职责划分：

```
preambles.py          ← 最终目标 + 全局硬性约束（两阶段，不变）
*.test.json           ← 这个 test case / site 的特殊性（instructions + guidance）
replay.json           ← 怎么做（路径）——由 explore 生成，不在 prompt 里描述
```

---

## 整体架构（当前实现）

```
test_agent/test_case/
├── preambles.py         ← Phase 1 / Phase 2 preamble 模板（多行字符串，所见即所得）
├── nike.test.json       ← Nike：domain + site/case instructions + guidance
└── *.test.json          ← 其他 site：同上
```

### preambles.py 占位符

- `{--Domain--}`：目标 URL
- `{--Instructions--}`：硬性约束条目（来自 site/case instructions，追加到固定指令后）
- `{--Guidance--}`：建议性操作参考（来自 site/case guidance）

### task_builder.py 构建逻辑

```
build_pre_checkout_task(test, preamble, site_guidance, domain)
build_checkout_task(test, preamble, site_guidance, domain)
```

`_fill_preamble` 规则：
- instructions 有值 → `{--Instructions--}` 替换为条目文本（追加在固定指令后）
- instructions 为空 → 移除 `{--Instructions--}` 占位符（固定 `# Instructions` 块保留）
- guidance 有值 → `{--Guidance--}` 替换为 `# Guidance` + 条目文本
- guidance 为空 → 整个 `{--Guidance--}` 占位符移除

---

## *.test.json 结构

```json
{
    "domain": "https://www.nike.com",
    "site_pre_checkout_guidance": ["适用于所有 test case 的 Phase 1 建议"],
    "site_checkout_guidance":     ["适用于所有 test case 的 Phase 2 建议"],
    "test_cases": [
        {
            "name": "Nike_autofill_Guest",
            "pre_checkout_instructions": ["Phase 1 硬性约束"],
            "pre_checkout_guidance":     ["Phase 1 建议（可选）"],
            "checkout_instructions":     ["Phase 2 硬性约束（可选）"],
            "checkout_guidance":         ["Phase 2 建议（可选）"]
        }
    ]
}
```

字段语义：
- `instructions`：硬性约束，LLM 必须遵守
- `guidance`：建议性参考，LLM 根据实际页面状态判断是否适用
- `site_*`：适用于该 site 所有 test case；`test.*`：仅适用于该 test case

---

## preambles.py 固定指令（当前）

**Phase 2 checkout 固定指令**（不依赖 test case）：
- `logmonitor_init` 在触发 popup 前调用
- `logmonitor_wait_for_state(expected_state='AutofillSucceeded')` 在 autofill 完成后调用
- `logmonitor_get_filter_results` 在 wait_for_state 成功后调用

**Phase 1 pre_checkout 固定指令**：无（全由 test case instructions 提供）

---

## explore → refine → replay 流程

```
Phase 1:  LLM 每次全新执行 pre_checkout_task，抵达 checkout 页面
            ↓
Phase 2 (首次):  LLM explore checkout_task → HistoryRefiner 精炼 → 保存 replay.json
Phase 2 (后续):  确定性 rerun replay.json
                  ↓ rerun 结束但 done(success=True) 未被调用
                LLM heal（从失败步骤续跑）→ 精炼 tail → merge → 更新 replay.json
```

`replay.json` 是"怎么做"的权威来源。prompt 只负责"做什么"和"为什么"。

---

## 新旧对比

| | 旧设计 | 当前设计 |
|---|---|---|
| preamble 存储 | `task_preamble.txt`（单文件，含 `\n`） | `preambles.py`（多行字符串，两阶段分离） |
| site 特殊性 | `{site_specific_hint}` 占位符注入 | `site_checkout_guidance` / `site_pre_checkout_guidance` |
| 路径指引 | prompt 里的自然语言 step 描述 | replay.json |
| heal 触发条件 | rerun 抛 RuntimeError | rerun 结束后检查 `done(success=True)` 是否被调用 |
| preamble 固定指令 | 无 | checkout 阶段固定 logmonitor 三步调用顺序 |

---

**维护日期**：2026-04-01
