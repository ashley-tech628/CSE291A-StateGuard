# StateGuard

CSE 291A Option 5：多智能体故障传播与状态一致性恢复。当前仓库是 Milestone 0，只提供 Phase 1 的共同接口、字段版本状态库和可重复的 clean demo。固定输出用于验证执行与追踪链路，不代表真实 LLM 实验结果。

## 快速运行

需要 Python 3.11+。

    python -m pip install -e ".[dev]"
    pytest -q
    python scripts/demo.py

Demo 会把 SQLite 和 JSON trace 写入被忽略的 results/。预期结果是 success: true、2 个 agent results、1 个 tool action 和 1 个 committed state event。使用全新数据库运行；重复运行同一 run_id 会被唯一键拒绝，以免混合实验。

## 已确定的数据契约

- AgentResult.parent_result_ids 只写实际被消费的结果；read_set 写实际读取的字段版本。
- ToolAction.parent_result_ids 关联驱动动作的计划结果；expected_version 是条件写入的依据。
- 每次受控写入、StateEvent 和 action ledger 在同一 SQLite 事务提交。相同 action_id 和相同请求的重试返回原结果。
- run_id 隔离每次实验。正式实验要保存任务定义、seed、模型配置、故障 schedule、trace 和 checker 结果。

src/stateguard/schemas.py 是三人共同审查的接口；修改字段语义前先在 PR 中讨论。现在采用 Python 标准库 dataclass，避免 bootstrap 阶段依赖安装；需要严格模型输出校验时，可在 agent adapter 边界引入 Pydantic，而不改变 JSON 字段语义。

## Phase 1 分工

| 负责人 | 独立交付 | 首个集成检查 |
| --- | --- | --- |
| 你：repo + state/tracing | 本骨架；扩展 trace 到 read/timeout/rejected action；full restart + external event replay baseline | 可以从 result ID 追到实际消费、动作和字段版本 |
| A：workflow + tools | 三个分析 agent、Planner、Executor、结构化工具调用、可替换模型 adapter | clean deployment 通过 checker；确定性路径稳定后接入真实 LLM |
| B：fault + evaluation | 任务和 fault schedules、四类注入、correctness/authorization oracle、always verify baseline | 同一任务有匹配 clean/fault run；确认错误被下游消费 |

第一轮合并顺序：共同确认 schema → A/B 各用 mock 数据开发 → 集成 clean run → 集成错误端口传播 → 扩展 baseline 和测量。每人提交成功与失败各一条自动化测试。main 保持可运行，所有 PR 跑 CI。

## 你的交接点

本地 Milestone 0 已包含可安装包、可测状态库、SQLite 字段版本、原子事件记录、确定性 clean trace、CI 配置。交给 A/B 后，你继续完善 provenance 和 full restart baseline。Phase 1 不实现 selective recovery；Phase 2 才比较 dependency-only 与 state-aware recovery。

## Phase 1 完成定义

1. 三分析 agent → Planner → Executor → checker 的 clean run 能重复成功；记录消息、实际消费、读写版本、工具动作和成本。
2. 四类故障分别注入；accidental 与 adversarial 分开统计。未被消费的注入单独列出。
3. fault/no recovery、full restart + external-event replay、always verify + bounded retry 在相同任务、fault schedule 和预算下比较。
4. 一条命令重现 pilot 的 traces 和汇总指标；保留失败样本。先用 8–10 个任务试跑，再扩大任务矩阵。

课程 AWS 限额和 LLM 配置由团队在正式实验前核对；本骨架在本地 CPU 就能运行。
