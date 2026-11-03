# Paired clean/fault evaluation

Paired experiments: **11**

## Overall

| Metric | Value |
| --- | --- |
| Clean success rate | 1.0 |
| Fault success rate | 0.3636 |
| Faults exposed to the planner | 9 |
| Consumed / ignored / blocked | 7 / 2 / 2 |
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

| Case | Exposed | Verdict | Plan identical | State identical |
| --- | --- | --- | --- | --- |
| ignored-resource-cpu-count | True | ignored | True | True |
| ignored-dependency-compat-flag | True | ignored | True | True |

## Expectation mismatches

None.
