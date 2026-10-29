# StateGuard

CSE 291A Option 5：多智能体系统中的故障传播与状态一致性恢复。

这个仓库现在包含一个可重复执行的 Phase 1 deterministic pilot。它不是单条 happy-path demo：实验会执行三个分析 agent、Planner、Executor、版本化 SQLite 状态库、权限检查、四类故障、三个对照策略、最终 correctness checker，并导出逐次 trace 和汇总表。

## 当前实验覆盖

- 8 个部署任务变体
- 1 个 clean condition
- 4 类故障：incorrect result、stale result、timeout、adversarial message
- 3 个策略：no recovery、full restart、always verify
- 总计 8 × 5 × 3 = 120 场运行
- full restart 会重建初始环境并重放合法管理员更新
- adversarial write 会到达 Planner 和 Executor，但受控工具层拒绝 protected-field 修改
- 每次状态写入、字段版本、result dependency、tool action 和 checker 结果写入 trace

当前 backend 是固定结构化输出，用于验证 Phase 1 的执行和评估方法。simulated_tokens 是确定性成本单位，不是真实模型 token；不能作为 LLM 性能结论。下一步接真实模型时保留相同的数据契约和实验 runner。

## 环境和运行

需要 Python 3.11+。

Windows PowerShell：

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    .\.venv\Scripts\python.exe -m pytest -q
    .\.venv\Scripts\python.exe scripts\run_phase1.py --output results\phase1-pilot --seed 7

macOS/Linux：

    python3.11 -m venv .venv
    .venv/bin/python -m pip install -e ".[dev]"
    .venv/bin/python -m pytest -q
    .venv/bin/python scripts/run_phase1.py --output results/phase1-pilot --seed 7

安装后也可以运行：

    stateguard-experiment --output results/phase1-pilot --seed 7

runner 每次会清理指定的 output directory，因此不要把手工文件放入该目录。

## 实验输出

- results/phase1-pilot/summary.csv：120 场运行的逐场指标
- results/phase1-pilot/report.json：按策略汇总的 clean success、fault success、调用成本与安全指标
- results/phase1-pilot/runs/<scenario>/trace.json：结果依赖、验证、动作、事件、最终状态与 checker
- results/phase1-pilot/runs/<scenario>/*.sqlite3：每个 attempt 的版本化状态和 action ledger

一条故障 trace 的关键链路是：

    faulty AgentResult
      -> Planner.parent_result_ids
      -> ToolAction.parent_result_ids
      -> StateEvent(action_id, before_version, after_version)
      -> final checker

fault_consumed 只有在 Planner 实际使用了故障结果时才为 true。timeout 在上游停止，always verify 检出的错误会重试，因此不会被误报为传播成功。

## 当前已验证结果

在 seed 7 的 120 场 pilot 中：

- 所有 24 个 clean run 全部成功。
- no recovery 的 32 个故障场景中，错误端口和 stale protocol 造成失败，timeout 停在 Config Agent，8 个 adversarial 场景由工具层阻断后仍完成合法任务。
- full restart 的 32 个故障场景全部得到正确最终状态，并保留 worker 管理员扩容。
- always verify 的 32 个故障场景全部在 Planner 消费前被修正；没有越权工具尝试。
- 所有策略中 unauthorized commits 均为 0。

这些是 deterministic pilot 结果，只证明实验 harness、传播路径、baseline 语义和 checker 工作正常。真实 LLM 实验需要另外报告模型、prompt、temperature、真实 token、延迟和重复运行统计。

## 代码结构

- src/stateguard/schemas.py：共享的 AgentResult、ToolAction、StateEvent 和 FaultSpec
- src/stateguard/state.py：SQLite 字段版本、原子事件记录和 action-id 幂等
- src/stateguard/workflow.py：分析 agents、Planner、Executor、故障和 checker
- src/stateguard/experiment.py：120 场矩阵、full restart、always verify 和结果导出
- tests/test_state.py：状态冲突和幂等测试
- tests/test_experiment.py：故障传播、权限、baseline、外部更新与完整矩阵测试

## Phase 1 分工

| 负责人 | 主要 ownership | 下一步 |
| --- | --- | --- |
| 你：runtime、state、tracing | schema、字段版本、action ledger、trace、full restart | 加真实 model adapter；扩展 provenance/成本统计 |
| 队友 A：workflow、tools | 三分析 agent、Planner/Executor、结构化工具 | 用真实模型替换 deterministic backend；保留 schema |
| 队友 B：fault、evaluation | workload、fault schedule、checker、always verify、分析 | 扩大 seed；生成图表和 Phase 1 报告 |

三人先审查 schemas.py 和 trace JSON，再各自开分支。任何 schema 变化必须同时更新 runner、checker 和测试。

## Phase 1 完成标准

1. 固定模型配置后，clean workflow 能稳定完成。
2. 每类故障都有匹配 clean run，并确认故障是否被实际消费。
3. accidental 和 adversarial 分开报告。
4. no recovery、full restart、always verify 使用相同任务、故障 schedule 和资源预算。
5. 保存 seed、模型配置、trace、最终状态、失败原因和汇总指标。
6. 至少重复多个 seed，报告真实 token、p50/p95 latency 和失败明细。

当前仓库已经完成前四项的 deterministic 版本和完整导出链路。接入真实 LLM、重复 seed 和统计分析后，才是可用于课程结论的 Phase 1 正式实验。
