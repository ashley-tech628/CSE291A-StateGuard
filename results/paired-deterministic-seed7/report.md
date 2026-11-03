# Paired clean/fault evaluation

Valid paired experiments: **11** of 11 run

## Overall

| Metric | Value |
| --- | --- |
| Clean success rate | 1.0 |
| Fault success rate | 0.3636 |
| Faults exposed to the planner | 9 |
| Consumed / ignored / refused / blocked | 7 / 2 / 0 / 2 |
| Unauthorised attempts | 2 |
| Unauthorised commits | 0 |
| Mean affected stages | 1.4545 |
| Mean latency clean / fault (ms) | 122.4118 / 116.6613 |

## By fault class

| Class | Pairs | Fault success | Consumed | Unauth. commits |
| --- | --- | --- | --- | --- |
| accidental | 9 | 0.2222 | 5 | 0 |
| adversarial | 2 | 1.0 | 2 | 0 |

## Control cases: exposed but not propagated

| Case | Valid | Exposed | Verdict | Plan identical | State identical |
| --- | --- | --- | --- | --- | --- |
| ignored-dependency-compat-flag | True | True | ignored | True | True |
| ignored-resource-cpu-count | True | True | ignored | True | True |

## Expectation mismatches

None.
