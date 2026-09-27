# Invoice Audit Exercise — Level 2

A reproducible, contract-first audit of 2,806 invoices across a civil works
subcontract and a directional drilling services contract. The solution parses
10,320 free-text records, applies the contracts and their later instruments in
date order, recalculates every payable line with contract-specific rounding,
and writes the completed `submission.csv` in the supplied template order.

## Result

| Portfolio | Invoices | Flagged | Clean |
|---|---:|---:|---:|
| Civil works | 900 | 77 | 823 |
| Directional drilling | 1,906 | 119 | 1,787 |
| **Total** | **2,806** | **196** | **2,610** |

The flagged rate is 6.99%, within the exercise's stated expectation of 5–8%.
That is a reasonableness check, not a tuning target: no detection threshold was
chosen to force this result.

There is no labelled answer set, so this repository does not claim measured
precision, recall, F1, or accuracy. Performance is reported through complete
coverage, deterministic reconciliation, evidence-level traces, contract
boundary tests, and explicit uncertainty. See [REPORT.md](REPORT.md).

## Quick start

Prerequisites: Python 3.11 and Tesseract OCR. The final audit rebuilds its
structured evidence from the repository's raw `.txt` records; OCR images and
intermediate OCR outputs are not required to reproduce `submission.csv`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/build_submission.py
python -m pytest -q
```

Expected final checks:

```text
Final rows: 2806
Civil rows: 900
Drilling rows: 1906
Flagged: 196
Clean: 2610
Coverage: complete; no missing, unexpected, or duplicate IDs
```

The generated submission is written to `submission.csv`. Detailed generated
traces are written under `artifacts/audit/` and are intentionally ignored by
Git.

## Pipeline

```text
Scanned contracts ──> multi-pass OCR + visual verification ──> encoded rules
Raw site records ───> civil evidence parser ──────────────────┐
Raw drilling reports -> drilling evidence parser ─────────────┤
Invoice headers + lines ───────────────────────────────────────┤
                                                              v
                                  civil and drilling audit engines
                                                              |
                                                              v
                                  template-ordered submission.csv
```

The pricing engines use `Decimal`, not binary floating point. Civil rates use
half-even rounding for index/FX conversions, half-up rounding for the final
built-up rate, and downward rounding for retention. Drilling rounds half-even
at every contractual pricing step.

## Repository structure

```text
civilwork/                         Civil contract, invoices, and site records
drilling_services/                 Drilling contract, invoices, and DDR records
scripts/ocr_contract.py            Multi-pass contract OCR and review metadata
scripts/parse_civil_records.py     Free-text civil evidence parser
scripts/parse_drilling_reports.py  DDR parser and Appendix G terminology map
scripts/audit_civil.py             Civil pricing and evidence audit
scripts/audit_drilling.py          Drilling pricing and evidence audit
scripts/build_submission.py        End-to-end rebuild and coverage validation
tests/                             Contract boundary and full-data controls
prompts/                           Versioned AI prompt and iteration log
DECISION_LOG.md                    Assumptions and ambiguity resolutions
REPORT.md                          Method, findings, and failure analysis
submission.csv                     Completed 2,806-row deliverable
```

## Audit coverage

The engines implement, among other rules:

- instrument issue dates versus effective dates, including retroactive single
  adjustments;
- indexed, monthly, substituted, and foreign-currency rates;
- ordered zone, ground, class, section, uplift, rebate, and discount factors;
- two distinct contractual rounding regimes;
- evidence existence, type, date, area, signature, and supported quantity;
- daily caps, minimums, exclusions, tolerances, once-per-run and once-per-well
  events;
- duplicate claims and reused weekly civil records;
- civil retention and release, drilling invoice discount, and VAT;
- invoice identity, period, submission window, arithmetic, and final total.

## Main outputs

- `submission.csv`: the required final file.
- `artifacts/audit/civil_line_audit.csv`: civil line evidence and pricing trace.
- `artifacts/audit/civil_application_audit.csv`: civil application reconciliation.
- `artifacts/audit/drilling_line_audit.csv`: drilling line evidence and pricing trace.
- `artifacts/audit/drilling_invoice_audit.csv`: drilling invoice reconciliation.
- `artifacts/audit/*_summary.json`: reproducibility controls and category counts.

## Testing strategy

The test suite combines unit tests for contractual boundaries with full-data
regression controls. It checks rounding, effective-date transitions, indexed
rates, standby factor ordering, evidence tolerances, lost-in-hole depreciation,
civil quantity bands, extension-period ground treatment, concurrent uplifts,
retroactive adjustments, exact template schema, row order, type integrity, and
complete ID coverage.

## AI assistance disclosure

AI assistance was used for OCR workflow design, rule transcription review,
parser and audit-engine implementation, test design, and documentation. Every
material result is produced by deterministic code and was rerun locally against
the supplied repository. Prompt iterations and constraints are versioned in
[`prompts/`](prompts/). Ambiguous readings are disclosed in
[DECISION_LOG.md](DECISION_LOG.md).

## Original exercise summary

The supplied exercise contains two amended contracts: 900 civil payment
applications with 7,746 lines and 2,169 site records, and 1,906 drilling
invoices with 91,244 lines and 8,151 daily reports. The required submission has
one row per invoice with a flag, error category, expected and billed totals in
minor units, and confidence. The contract governs wherever it differs from the
guidelines.

