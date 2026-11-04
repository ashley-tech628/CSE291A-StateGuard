# StateGuard Phase 1 report

`StateGuard_Phase1_Report_Expanded.pdf` is the current compiled submission: two pages of main text and a third
page for the milestone/reproducibility appendix and references. Body text is
10pt on 12pt leading, in two columns with a 7in by 9in text block and page numbers.

The report describes the implemented workflow and runtime, the matched AWS /
TritonAI baseline experiment, its exclusions and limits, and the Phase 2 plan.
It does not present selective-recovery unit tests as real-model evaluation.

## Authors

Xinying Liu, Jingwen Zhang, and Haodi Yuan are filled in as provided. No individual contribution statement is included.

## Compile

Upload `main.tex` and both `figures/propagation-cost.pdf` and
`figures/architecture.pdf` together to Overleaf, or run:

```sh
pdflatex main.tex
pdflatex main.tex
```

Tectonic 0.17.0 also successfully compiles the source with automatic package
downloads. Packages include newtxtext/newtxmath, geometry, microtype, graphicx,
booktabs, hyperref, and caption. The bibliography is inline and needs no BibTeX.

Both figures are vector PDFs. To rebuild them from the repository root, install the
evaluation dependencies and run `python paper/phase1/build_figure.py` and
`python paper/phase1/build_architecture.py`.
The result-figure builder validates manifests, reads the nine baseline summaries via the common-valid-pair gate,
and checks the paired AV traces to distinguish correction from ignored faults. The matched experiment source
is revision `6930ac8`. All result values are descriptive measurements on one
deployment task, not significance claims across deployment workloads.

## Verification

- Integrated code: 156 tests pass.
- Final PDF: three letter-sized pages (two main-text pages plus appendix/references); all pages visually checked.
- No overfull text boxes in the final TeX log.
- Nine references checked against primary publisher, author, and repository pages.
- The original proposal's broader task/topology and ablation goals remain
  Phase 2 work; they are not claimed as completed experiments.

## Figure and scope

The report includes the three-panel propagation, token-cost, and latency figure
as a full-width vector graphic, reformatted for readable two-column printing.
The appendix includes a single-column vector runtime architecture diagram. In the result
figure, the 24 AV outputs labeled `corrected before Planner` were classified
from verification traces; the stored raw propagation verdicts remain `ignored`.
FR propagation is shown before restart, while its cost includes the restart.
Recovery-stage counts exclude AV verification retries, while call, token, and
latency metrics include them.
The outcome table preserves completion, unauthorized commits, calls, and
recomputation counts. See `COVERAGE.md` for proposal-to-report coverage.

The earlier `StateGuard_Phase1_Report.pdf` is superseded by the expanded version.
