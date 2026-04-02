# Roadmap：脚本化回放 + 自愈式 CI/CD

## 背景

当前架构每个 checkout 测试需要 LLM 探索执行，总耗时 80-160s。
目标是建立全自动精炼闭环：首次 LLM 探索，自动精炼出最短有效路径写入 `replay.json`，
后续直接回放（无 LLM，~25s）；回放失败时 LLM 断点续跑，自动精炼新段并合并，全程无人工介入。

**实测数据（Nike_autofill_Guest，checkout 阶段）：**
- explore（首次）：83.2s，5步 LLM 探索 → 精炼 → 存 replay.json
- replay（后续）：24.7s，确定性 rerun，无 LLM 推理，快 3.4×

---

## 架构决策记录

### 为什么不用 LLM 生成 Playwright 脚本（Idea 1，已废弃）

最初考虑让 LLM 把探索过程转写为 Playwright 脚本。**根本性缺陷**：

- **selector 静态化**：Playwright 脚本依赖 CSS selector / XPath 字符串，Nike 每次发版
  class/id 都会变，脚本立刻失效，且无自愈能力
- **生成质量不稳定**：LLM 生成的代码边界情况处理差，调试困难，出错只有 exception 没有上下文
- **额外维护成本**：需要独立的 Playwright 环境和脚本版本管理
- **无法利用 browser-use 的 6 级 fallback**：`Agent.rerun_history()` 内置
  `backend_node_id → element_hash → stable_hash → xpath → ax_name → attributes`
  逐级降级匹配，单个属性变了照样能找到元素——这是 Playwright 脚本完全没有的能力

**结论**：`replay.json` + `rerun_history()` 在稳定性、自愈能力、维护成本上全面优于 LLM 生成脚本。

### 为什么不用验证剪枝（逐步删除+验证）

验证剪枝理论上能找到最优最短路径，但在本场景有致命约束：

- Nike 真实网站有 Akamai 反爬，短时间内重复访问 checkout 15 次会触发封禁
- autofill 触发状态不可回滚，每次验证需完整从头跑一遍（80-160s × N 次）
- 代价比全量重跑高一个量级，且稳定性更差

### 选定方案：LLM 语义精炼 + 单次回放验证

```
LLM 探索完（N步 history）
    ↓
规则清洗（零成本）→ 删除明确无用步骤
    ↓
LLM 语义分析（1次调用）→ 输出可删除的 step index 列表
    ↓
删除后跑 1 次 rerun() 验证
    ↓
通过 → 写入 replay.json（精炼版）
失败 → 写入 replay.json（规则清洗版，功能正确优先）
```

代价：1次 LLM 调用 + 1次完整回放，相比验证剪枝节省 90% 时间。

### 为什么 replay.json 只录制 checkout 阶段

pre-checkout 阶段（登录、管理购物车、导航至 checkout）在不同运行间高度不稳定：
商品可能售罄、cart 状态各不相同、登录需要验证码。把这些步骤录入 replay.json
会导致回放在第一步就失败，自愈意义丧失。

**决策**：执行分为两阶段——
- **Phase 1**：LLM 每次全新执行 `pre_checkout_task`，到达 checkout 页面后结束，不录制
- **Phase 2**：在同一浏览器 session 上，对 checkout 交互走 replay / explore，只录制这部分

### 为什么去掉 replay_mode 配置项

早期设计了三种模式（`precheckout_skip`、`precheckout_llm`、`fully_llm`）允许 per-test-case override。
实践中发现：

- `precheckout_skip`（跳过 Phase 1，直接 rerun）需要 replay.json 第一步是 goto，
  录制时没有这一步，特殊处理增加复杂度
- heal 失败本质上就退化为 fully_llm，不需要单独模式
- guest 场景只要用正确的 profile（Profile 3），Phase 1 LLM 消耗 token 极少（直接到 checkout）

**结论**：所有 test case 统一走"Phase 1 LLM + 有 replay 就 rerun + 失败 heal"，
用 `profile` 字段控制哪个 Edge profile，足够覆盖所有场景，无需 replay_mode。

---

## 当前执行架构

```
test_runner.py 启动
    ↓
构建 pre_checkout_task / checkout_task（纯字符串，无副作用）
    ↓
启动 BrowserSession(keep_alive=True)
    ↓
Phase 1: LLM 执行 pre_checkout_task（每次全新跑，不录制）
    ↓ 到达 checkout 页面，浏览器 session 保持打开
Phase 2: 检查 {name}.replay.json 是否存在？
    │
    ├── 不存在 → LLM explore checkout_task → HistoryRefiner 精炼 → 存 replay.json
    │
    └── 存在 → ReplayManager.rerun_history()
                    ↓
                成功 → 完成（~25s）
                失败（step K）→ 浏览器保持打开
                    ↓
                LLM 从当前页面状态续跑剩余 checkout 任务（heal）
                    ↓
                新 tail history → HistoryRefiner 精炼 tail
                    ↓
                合并：replay[:K] + refined_tail → 写回 replay.json
```

---

## 核心组件

### HistoryRefiner（`test_agent/replay/history_refiner.py`）

**职责**：把含弯路的 `AgentHistoryList`（checkout 阶段）精炼为最短有效路径。

**步骤 1：规则清洗（零成本，无需 LLM）**

删除明确无用的步骤：
- `action == [None]`（纯思考步骤）
- `result.error` 非空（原本就失败的步骤）
- 连续相同 `stable_hash` + 相同 `action_type`（重复点击同一元素）
- `action_type` 为 `extract`/`screenshot` 且 `interacted_element` 为 None（无副作用观察步骤）

**步骤 2：LLM 语义精炼（1次调用）**

将清洗后的 history 序列化为结构化摘要喂给 LLM，输出可删除的 step index。

硬性约束（LLM 不得违反）：
- `is_protected=true`（`action_type` 为 `uia_*` / `logmonitor_*`）→ 绝对不能删
- `result_success=false` → 绝对不能删
- 第一步和最后一步 → 绝对不能删

**步骤 3：单次 rerun() 验证**

用精炼后的步骤跑 1 次完整回放：
- 通过 → 返回精炼版
- 失败 → 返回规则清洗版（兜底）

---

### ReplayManager（`test_agent/replay/replay_manager.py`）

**职责**：Phase 1 LLM + Phase 2 checkout replay/explore/heal 全生命周期管理。

**关键设计：rerun() 失败时不关闭浏览器**

`BrowserSession` 由 `test_runner.py` 创建并传入，rerun 失败后保持打开，
LLM heal agent 接管时看到的是失败那一刻的真实页面状态。

**rerun() 失败判断**

捕获 `RuntimeError("Step N failed after X attempts: ...")` 后用正则解析
`failed_step_index`，精确定位断点。

**回放速度优化**

所有回放参数集中在 `config.py`：
- `RERUN_MAX_RETRIES = 2`
- `RERUN_DELAY_BETWEEN_ACTIONS = 1.0`（每步固定等待）
- `RERUN_MAX_STEP_INTERVAL = 2.0`（压缩 LLM 探索时的 saved interval，避免 replay 时等太久）

**rerun() 失败判断逻辑**

优先检查 `rerun_history()` 返回的实际执行结果（`list[ActionResult]`）：
- 有 `error` 的 result → 尝试从错误消息解析 `Step N failed` → 映射到 history index → 触发 heal
- 无 error 但 AI summary 报失败 → 从末尾触发 heal
- 全部成功 → 回放通过

注意：`replay.history[i].result` 是 explore 阶段录制的原始结果，不反映本次 rerun 实际执行情况，不能用于判断失败。

**heal 后合并去重**

heal 产生的 tail 与 head 拼接时，自动检测 head 末尾和 tail 开头的 action type 是否重复
（例如 `logmonitor_init` 在两段都出现），重复则删除 tail[0]。

---

## 文件结构

```
test_agent/
├── replay/
│   ├── history_refiner.py    # HistoryRefiner
│   └── replay_manager.py     # ReplayManager（Phase 1 + Phase 2）
├── test_case/
│   └── nike/
│       ├── nike.test.json                        # 测试用例定义（profile 字段区分 signed-in/guest）
│       ├── nike_autofill_guest.replay.json        # 精炼后黄金路径（checkout 阶段）
│       └── nike_autofill_signed_in.replay.json    # 精炼后黄金路径（checkout 阶段）
├── config.py                                     # 所有配置集中管理（含 replay 参数）
└── test_runner.py                                # 入口，输出耗时日志
```

---

## 现有工程基础

| 组件 | 文件 | 用途 |
|------|------|------|
| LLM 执行引擎 | `test_runner.py` | 两阶段执行，Phase 1 LLM + Phase 2 replay/explore |
| Agent.rerun_history() | `browser_use/agent/service.py` | 回放驱动，6级元素 fallback |
| AgentHistoryList | `browser_use/agent/views.py` | replay.json 格式，save/load |
| DOMInteractedElement | `browser_use/dom/views.py` | 含 x_path、stable_hash、ax_name |
| 自定义 actions | `register_custom_actions.py` | rerun 时需同样注册 |
| 回放配置 | `config.py` | RERUN_* 常量统一管理 |

---

**维护日期**：2026-04-02
