# Roadmap：自愈 CI/CD

## 目标

测试失败时，系统自动分析根因、修改代码、回归验证、提 PR，全程无人工介入。

这是独立于 Phase 1（replay 精炼 + 断点续跑）的项目，依赖 Phase 1 稳定后再推进。

---

## 核心流程

```
测试失败（replay 回放失败且 LLM 续跑也失败）
    ↓
LLM 分析根因
    ├── 页面结构变化（selector 失效）→ 更新 replay.json / shared_steps
    ├── 业务逻辑变化（流程改变）→ 更新 step_description
    └── 代码 bug（action 实现有问题）→ 修改白名单目录代码
    ↓
回归验证（重跑完整 test case）
    ↓
通过 → 提 PR（branch: auto-fix/{test_case_name}/{date}）
失败 → 上报，人工介入
```

---

## 约束：白名单目录

LLM 只允许修改以下目录的代码，禁止触碰核心库：

```
test_agent/test_case/          # *.test.json（step descriptions、params）
test_agent/shared_steps/       # 公共 shared steps（如果提取出来的话）
test_agent/actions/            # 自定义 action 实现
test_agent/scripts/            # 辅助脚本（uia_helper、log_file_monitor 等）
logs/*.replay.json             # 精炼后的黄金路径
```

禁止修改：
- `browser_use/`（核心库）
- `test_agent/replay/`（replay 基础设施）
- `test_runner.py`、`models.py`、`config.py`

---

## 依赖

- **Phase 1 稳定**：replay + 断点续跑已能可靠运行，失败信号足够清晰
- **结构化失败报告**：`ReplayManager` 需输出机器可读的失败摘要（失败步骤、action、error message、page URL）
- **PR 提交能力**：需要 git + GitHub CLI 权限，或 MCP GitHub 工具

---

## 现有工程基础

| 组件 | 文件 | 说明 |
|------|------|------|
| 失败检测 | `replay_manager.py` | 已能定位 failed_step_index |
| LLM 执行引擎 | `test_runner.py` | 可复用 Agent 实例分析根因 |
| 白名单目录 | `test_agent/` | 已有清晰的目录结构 |

---

**维护日期**：2026-03-31
