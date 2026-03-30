# Roadmap：脚本化回放 + 自愈式 CI/CD

## 背景

当前架构每个 checkout 测试需要 20+ 个 LLM step，每步 5-8s，总耗时 100-160s。
两个想法合在一起构成一个完整的**自愈式 CI/CD 闭环**：首次由 LLM 探索执行并录制脚本，后续直接回放；
检测到 regression 时自动定位根因、修复代码、回归验证，通过后提 PR 等人工确认。

---

## 想法1：脚本化回放 + LLM 兜底

### 目标

```
第一次运行：LLM 探索执行 → 录制成功路径 → 写入 replay_steps
后续运行：  直接 Playwright 回放（无 LLM，5-10s 完成）
失败时：    LLM 重新探索 → 更新 replay_steps
```

### 为什么必要

| 指标 | 当前（全 LLM） | 目标（脚本回放） |
|------|--------------|----------------|
| 单次测试耗时 | 100-160s | 5-10s |
| LLM 调用次数 | 20+ 次/测试 | 0（成功时） |
| 成本 | 每次全量 | 仅首次 + 失败时 |
| 可预测性 | 低（LLM 不确定性） | 高（脚本确定性） |

### 实现组件

#### ScriptRecorder
- 输入：`agent.run()` 返回的 `AgentHistoryList`
- 从 `DOMInteractedElement` 提取 stable selector（XPath 优先，CSS fallback）
- 输出：填充 `nike.test.json` 里每个 `test_case` 的 `replay_steps` 字段
- 关键挑战：browser-use 的动态 DOM index 每次加载可能变，必须转换为 XPath/CSS

#### ScriptRunner
- 直接用 Playwright 执行 `replay_steps`，不走 LLM
- 捕获失败（`TimeoutError` / assertion 失败 / element not found）
- 失败时触发 LLM Fallback

#### LLM Fallback
- ScriptRunner 失败 → 触发完整 LLM 重新探索
- 探索成功 → ScriptRecorder 更新 `replay_steps`
- 记录失败原因（selector 过期 / 页面流程变更 / 其他）

### 数据结构

`replay_steps` 字段已在 `models.py` 和 `nike.test.json` 中预留，当前为空数组：

```python
# models.py（已有）
class TestCaseReplayStep(BaseModel):
    stepIndex: int
    evaluation_previous_goal: str
    memory: str
    next_goal: str
    replayActions: list[TestCaseReplayAction] = []

class TestCaseReplayAction(BaseModel):
    action: dict[str, Any]      # {"click": {"selector": "//input[@id='email']"}}
    result: ActionResult
    element: Optional[DOMInteractedElement] = None
    stepIndex: int
    actionIndex: int
```

```json
// nike.test.json（已有预留字段，待填充）
{
  "test_case_name": "Nike_autofill_Guest",
  "replay_steps": []
}
```

### 执行流程

```
test_runner.py 启动
    ↓
检查 replay_steps 是否为空？
    ├── 空 → LLM 模式执行 → ScriptRecorder 录制 → 写入 replay_steps
    └── 非空 → ScriptRunner 直接回放
                    ↓
                成功 → 完成
                失败 → LLM Fallback → 重新录制 → 写入 replay_steps
```

### 关键未确认项

- `DOMInteractedElement` 是否保存了 xpath / css_selector 字段
  （决定 ScriptRecorder 的实现难度，需要查 browser-use 源码确认）

---

## 想法2：自动修复 + 回归验证 + 提 PR

### 目标

```
测试失败（regression 检测到）
    ↓
LLM 分析根因 → 修改代码（白名单目录）
    ↓
回归测试（想法1 的脚本套件）
    ↓
通过 → git commit + gh pr create（人工 review & merge）
失败 → 记录，人工介入
```

### 为什么合理

- LLM 改代码 → 有回归测试兜底，不会悄悄引入新问题
- 不自动合入 → 人工是最后一道门
- 只有通过测试的代码才暴露为 PR

### 可自动修改的代码范围（白名单）

| 类型 | 路径 | 可自动改 |
|------|------|---------|
| Selector 更新 | `test_case/*.test.json` | ✅ 最安全 |
| 测试脚本逻辑 | `test_agent/test_case/` | ✅ 安全 |
| 配置修改 | `test_agent/config.py` | ✅ 安全 |
| 自定义 action | `test_agent/actions/` | ⚠️ 谨慎 |
| 工具脚本 | `test_agent/scripts/` | ⚠️ 谨慎 |
| browser-use 核心 | `browser_use/` | ❌ 不碰 |

### 实现组件

#### BugDetector
- 监听测试运行结果：ScriptRunner 失败 / Python traceback / assertion 不符
- 分类失败原因：
  - `SELECTOR_STALE` — element not found，selector 过期
  - `FLOW_CHANGED` — 页面流程变化（新弹窗、新步骤）
  - `CODE_ERROR` — Python 异常，代码 bug
  - `INFRA_ERROR` — 网络/浏览器崩溃，非业务问题

#### RootCauseAnalyzer
- 输入：错误类型 + traceback + 相关代码文件 + history JSON + 截图（可选）
- LLM 分析现场，定位到具体文件和行
- 输出：`{file, line_range, diagnosis, suggested_fix}`

#### CodePatcher
- 接收 RootCauseAnalyzer 的输出
- LLM 在白名单目录内修改文件
- 记录所有变更（diff）

#### RegressionRunner
- 跑完整测试套件（想法1 的 ScriptRunner）
- 收集 pass/fail 结果
- 判断：新代码是否引入新的失败？

#### PRSubmitter
```python
# 伪代码
git checkout -b auto-fix/{bug_type}/{timestamp}
git add {changed_files}
git commit -m "auto-fix: {diagnosis}"
gh pr create --title "..." --body "..." --draft
```

### 执行流程

```
BugDetector 检测到失败
    ↓
RootCauseAnalyzer 分析根因
    ↓
失败类型判断：
    ├── SELECTOR_STALE → ScriptRecorder 重录（想法1 的 Fallback）
    ├── FLOW_CHANGED   → LLM 重探索 + 更新 test.json
    ├── CODE_ERROR     → CodePatcher 修改白名单内代码
    └── INFRA_ERROR    → 记录，跳过，人工处理
    ↓
RegressionRunner 跑回归
    ├── 通过 → PRSubmitter 提 PR
    └── 失败 → 记录完整 context，人工介入
```

---

## 依赖关系

```
想法1（Phase 1）
└── 是想法2（Phase 2）的前提
    └── 想法2 的回归测试 = 想法1 的 ScriptRunner
```

**想法1 必须先完成，想法2 才有意义。**

---

## 实施计划

### Phase 1（~2周）：脚本化回放

- [ ] 确认 `DOMInteractedElement` 的 xpath/css_selector 字段
- [ ] 实现 `ScriptRecorder`（`test_agent/recorder/script_recorder.py`）
- [ ] 实现 `ScriptRunner`（`test_agent/recorder/script_runner.py`）
- [ ] 修改 `test_runner.py`：首次录制 / 后续回放 / 失败兜底
- [ ] 验证：Nike checkout 回放稳定通过 5 次

### Phase 2（~2周，依赖 Phase 1）：自愈 CI/CD

- [ ] 实现 `BugDetector`（`test_agent/healing/bug_detector.py`）
- [ ] 实现 `RootCauseAnalyzer`（`test_agent/healing/root_cause_analyzer.py`）
- [ ] 实现 `CodePatcher`（`test_agent/healing/code_patcher.py`）
- [ ] 实现 `RegressionRunner`（`test_agent/healing/regression_runner.py`）
- [ ] 实现 `PRSubmitter`（`test_agent/healing/pr_submitter.py`）
- [ ] 端到端验证：人工引入一个 selector bug，观察全流程自愈

---

## 现有工程基础

已有、可直接复用：

| 组件 | 文件 | 复用方式 |
|------|------|---------|
| LLM 执行引擎 | `test_runner.py` | Phase 1 Fallback + Phase 2 探索 |
| Action 历史记录 | `agent.save_history()` | ScriptRecorder 输入源 |
| replay 数据结构 | `models.py` | 直接使用，无需修改 |
| replay 字段预留 | `nike.test.json` | 等待 ScriptRecorder 填充 |
| 日志监控 | `scripts/log_file_monitor.py` | BugDetector 输入源 |
| gh CLI | 已配置 | PRSubmitter 直接调用 |
| 自定义 actions | `register_custom_actions.py` | ScriptRunner 需要注册相同 actions |

---

**维护日期**：2026-03-30
