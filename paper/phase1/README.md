# StateGuard Phase 1 report

`StateGuard_Phase1_Report.pdf` is the compiled two-page submission. It includes
the milestone appendix and references within the two-page total. Body text is
10pt on 12pt leading, in two columns with a 7in by 9in text block and page numbers.

The report describes the implemented workflow and runtime, the matched AWS /
TritonAI baseline experiment, its exclusions and limits, and the Phase 2 plan.
It does not present selective-recovery unit tests as real-model evaluation.

## Authors

Xinying Liu and Jingwen Zhang are filled in as provided. Before submission, add
the third member to `ThirdAuthor` and `ThirdEmail` in `main.tex`, then recompile
and verify the page count. No individual contribution statement is included.

## Compile

Upload `main.tex` and `figures/propagation-cost.pdf` together to Overleaf, or run:

```sh
pdflatex main.tex
pdflatex main.tex
```

Tectonic 0.17.0 also successfully compiles the source with automatic package
downloads. Packages include newtxtext/newtxmath, geometry, microtype, graphicx,
booktabs, hyperref, and caption. The bibliography is inline and needs no BibTeX.

The figure is vector PDF. To rebuild it from the repository root, install the
evaluation dependencies and run `python paper/phase1/build_figure.py`.
It validates manifests and reads the nine baseline summaries via the common-valid-pair gate; the matched experiment source
is revision `6930ac8`. All result values are descriptive measurements on one
deployment task, not significance claims across deployment workloads.

## Verification

- Integrated code: 156 tests pass.
- Final PDF: two letter-sized pages; visual rendering checked on both pages.
- No overfull text boxes in the final TeX log.
- Citation metadata checked against AgentDojo's arXiv page, Microsoft's TAMAS
  repository, and the A2ASecBench project page.
- The original proposal's broader task/topology and ablation goals remain
  Phase 2 work; they are not claimed as completed experiments.

## Figure and scope

The report includes the three-panel propagation, token-cost, and latency figure
as a full-width vector graphic, reformatted for readable two-column printing.
The outcome table preserves completion, unauthorized commits, calls, and
recomputation counts. See `COVERAGE.md` for proposal-to-report coverage.
