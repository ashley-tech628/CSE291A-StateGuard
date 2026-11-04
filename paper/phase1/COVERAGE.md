# Proposal and evidence coverage

| Essential item | Report location | Evidence status |
| --- | --- | --- |
| Failure propagation, valid reuse, bookkeeping tradeoff | Section 1, RQ1-RQ3 | Research questions |
| API/worker/database; Config/Dependency/Resource/Planner/Executor | Section 1 | Implemented |
| Python, Pydantic, SQLite, CLI, model adapter | Section 1 | Implemented |
| Typed provenance, field versions, invalidation and reuse equation | Section 2 | Implemented; conservative dependencies |
| Conditional writes, action ledger, lost-ACK deduplication | Section 2 | Controlled-tool tests |
| External-event replay, conflict handling, irreversible effects | Section 2 | Implemented/tested; not in real-model baseline matrix |
| TritonAI model, AWS, Python, temperature, retry/pacing, seeds, revision | Section 3 | Recorded configuration |
| Four fault families, two controls, paired clean/fault evaluation | Section 3 | 11 cases, 99 attempted pairs |
| No recovery, full restart, oracle always verify | Section 3 | Real-model baselines |
| Provider failures, clean-control failure, matched exclusions | Section 4 | 96 valid pairs; 30 common combinations |
| Task success, unauthorized commits, tokens, latency, calls, recomputation | Table 1 | Measured |
| Consumed/ignored/corrected/refused/blocked and cost distributions | Figure 1 | Measured; AV correction is derived from verifier traces; FR path precedes restart while cost includes it |
| Persistent-port, compatibility control, separate adversarial analysis | Section 4 | Measured; ignored attacks are not recovery evidence |
| Dependency-only vs state-aware recovery; 24-36 tasks and three topologies | Section 5 | Planned Phase 2 evaluation |
| External updates, shared-resource conflicts, three ablations | Section 5 and appendix | Planned expanded evaluation |
| Invalidation precision/recall, stale reuse, retained work, tracking overhead | Appendix | Planned metrics; no invented results |
| Runtime and recovery architecture | Figure 2 (single-column appendix) | Implemented; selective replay not in real-model matrix |
| Milestones through December 10 | Appendix table | Planned |
| Primary benchmark references and reproducibility artifacts | Appendix/references | Sources and repository link |

The two-page main text combines the whole-project proposal with Phase 1 evidence; page three contains the appendix and references.
It does not claim that planned experiments, selective-recovery LLM comparisons,
or arbitrary remote-side-effect rollback have already been completed.
The full case-by-case success heatmap remains in the repository; the report
retains its main failures in prose to keep the required two-page limit.
