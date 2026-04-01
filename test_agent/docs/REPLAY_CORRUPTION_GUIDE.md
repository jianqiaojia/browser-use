# Replay JSON 破坏指南（用于测试 Heal 流程）

## 背景

`rerun_history()` 通过元素匹配来定位 DOM 节点，匹配逻辑分三个层级（EXACT → FUZZY → FALLBACK）。
了解匹配机制才能有效破坏 replay.json，让 rerun 在指定步骤失败并触发 heal。

---

## 元素匹配机制

每个 `interacted_element` 记录了以下字段：

```json
{
  "node_id": 8296,
  "backend_node_id": 20039,
  "node_name": "BUTTON",
  "attributes": {
    "aria-label": "Edit,Delivery Options",
    "class": "nds-btn css-1gj4wv ...",
    "data-attr": "editButton"
  },
  "element_hash": 621193725657288954,
  "stable_hash": 10144109002646469741,
  "ax_name": "Edit,Delivery Options"
}
```

rerun 匹配顺序：

1. **EXACT**：用 `stable_hash` 在当前 DOM 的 selector map 里直接查找
2. **FUZZY**：用 `node_name` + `attributes` 组合做模糊匹配
3. **FALLBACK**：用 `element_hash`、`ax_name` 等其他特征

只要有一个层级命中就成功。**只改 `aria-label` 不够**——FUZZY 层会用 `class`、`data-attr` 等其他属性补救，仍然能匹配上。

---

## 有效的破坏方法

### ✅ 方法一：改 `stable_hash`（最简单，推荐）

`stable_hash` 是 EXACT 匹配的 key，直接改成不存在的值即可跳过 EXACT 层。
再把 `element_hash` 也改掉，防止 FALLBACK 层命中：

```json
"element_hash": 1,
"stable_hash": 1,
```

FUZZY 层仍可能命中（如果 `attributes` 没变）。如果 FUZZY 也要失败，继续看下面。

### ✅ 方法二：改 `stable_hash` + 清空 `attributes`

彻底断开所有特征匹配：

```json
"element_hash": 1,
"stable_hash": 1,
"attributes": {},
"ax_name": ""
```

### ✅ 方法三：改 `node_name` 为不存在的标签

`node_name` 不匹配时 FUZZY 层直接跳过：

```json
"node_name": "CORRUPTED",
"element_hash": 1,
"stable_hash": 1,
```

---

## 无效的破坏方法

| 改动 | 原因 |
|------|------|
| 只改 `node_id` / `backend_node_id` | 这两个只是引用，rerun 不直接用它们做匹配 |
| 只改 `aria-label` | FUZZY 层会用 `class`、`data-attr` 等其他属性补救 |
| 只改一个 `attributes` 字段 | 同上，其他字段仍能提供足够相似度 |

---

## 操作示例

破坏第 2 步（Edit Delivery Options 按钮），在 replay.json 里找到对应 step 的 `interacted_element`，改两行：

```json
// 改前
"element_hash": 621193725657288954,
"stable_hash": 10144109002646469741,

// 改后
"element_hash": 1,
"stable_hash": 1,
```

预期行为：rerun 第 2 步抛 `Could not find matching element` → RuntimeError → ReplayManager 触发 heal → LLM 从第 2 步当前页面状态续跑。

---

## 恢复方法

heal 成功后 ReplayManager 会把修复后的 history merge 写回 replay.json，覆盖破坏的内容。
无需手动恢复。

---

**维护日期**：2026-04-01
