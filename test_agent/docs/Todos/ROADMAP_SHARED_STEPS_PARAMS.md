# Roadmap：Shared Step 参数化

## 背景

当前 `shared_steps` 是静态的 —— step_description 是固定字符串，不同 site 复用同一个 step 时无法注入 site-specific 信息。

典型问题：`trigger_autofill_popup` 步骤需要告知 LLM 该 site 的 trigger field 和 CSS selector，但这些信息每个 site 不同，不能硬编码进 shared step。

目前的临时方案是把信息写进 `test_case_description`，但 `test_case_description` 根本没有传给 LLM（只被 print 了），所以实际上 LLM 看不到。

---

## 方案：`params` 字段 + 占位符替换

### 数据结构改动

**`models.py` — `TestStep` 加 `params` 字段**

```python
class TestStep(BaseModel):
    ref: Optional[str] = None
    params: Optional[Dict[str, str]] = None  # 替换 step_description 中的 {key} 占位符
    step_name: Optional[str] = None
    step_description: Optional[str] = None
    expected_result: Optional[str] = None
```

**`test_runner.py` — `build_task_from_steps` 做替换**

```python
def build_task_from_steps(steps: list[TestStep]) -> str:
    task_parts = []
    for step in steps:
        description = step.step_description or ""
        if step.params:
            for key, value in step.params.items():
                description = description.replace(f"{{{key}}}", value)
        task_parts.append(f"{step.step_name}: {description}")
    return "\n".join(task_parts)
```

### JSON 用法

shared step 用 `{placeholder}` 占位：

```json
"trigger_autofill_popup": {
    "step_name": "Trigger autofill popup",
    "step_description": "Goal: focus the site's EC trigger field. {trigger_field_hint} The page may show a pre-filled summary — look for an Edit button and click it first. Once the target input is visible: clear it (clear=true), cdp_click once, wait 2s, uia_wait_for_popup(timeout=5). If not detected, retry with os_click. Do NOT use Payment/cardNumber fields.",
    "expected_result": "..."
}
```

test case 的 step ref 传 params：

```json
{
    "ref": "trigger_autofill_popup",
    "params": {
        "trigger_field_hint": "For Nike (ShippingAddress page): any field in the form (email, firstName, address1) can trigger the popup once the form is visible. address1 is the visibility-check sentinel — it must be visible for the popup to appear. Recommended: focus email or firstName (selector: [data-attr*=AddressForm] input#email or input#firstName)."
    }
}
```

---

## 实施步骤

1. `models.py`：`TestStep` 加 `params: Optional[Dict[str, str]] = None`
2. `test_runner.py`：`build_task_from_steps` 加占位符替换逻辑
3. 把现有公共 shared steps 提取到独立文件（如 `test_agent/shared_steps/ec_common.json`），各 site test.json 通过 import 或 merge 引用
4. `nike.test.json`：`trigger_autofill_popup` step_description 改用 `{trigger_field_hint}` 占位，两个 test case 的 ref 加 `params`
5. 把 `test_case_description` 也传给 LLM（作为 task 的 preamble），或者废弃该字段

---

## 注意事项

- `params` 只支持 `str` → `str` 替换，不支持嵌套结构，保持简单
- 占位符格式用 `{key}`，与 Python str.format 一致，但用 replace 实现（避免 step_description 里其他大括号被误解析）
- shared steps 提取到公共文件是独立任务，参数化机制不依赖它，可以先做参数化

---

**维护日期**：2026-03-31
