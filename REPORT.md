# Audit Report

## Executive summary

The audit covers all 2,806 supplied invoices and produces one template-matched
submission row for each. It flags 196 invoices (6.99%): 77 of 900 civil
applications and 119 of 1,906 drilling invoices. The final file has no missing,
unexpected, or duplicate IDs and no null output cells.

Because the exercise provides no labels, precision, recall, F1, and accuracy
cannot be measured honestly. The reported performance evidence is therefore:

- complete invoice and evidence coverage;
- deterministic `Decimal` pricing and full line-to-total reconciliation;
- 10,320 parsed records, with parser anomalies surfaced rather than hidden;
- contract-boundary and full-dataset regression tests;
- evidence-rich line audit files that reproduce every expected total;
- a 6.99% flagged rate used only as a post-audit reasonableness check.

## Approach

1. The scanned contracts were OCR'd in multiple layout modes. Critical tables,
   amendments, factors, dates, limits, and rounding clauses were checked against
   page images before being encoded.
2. Civil records and drilling DDRs were parsed independently of invoice prices.
   The drilling parser maps ordinary rig language using Appendix G; the civil
   parser maps the finite record phrasings to priced items.
3. Each line was joined to its evidence and checked for identity, date, period,
   unit, content, quantity, duplication, and contract eligibility.
4. Payable rates and amounts were rebuilt in contractual order. Stateful rules
   such as bands, run events, prior claims, amendments, retention, discount, and
   VAT were then applied.
5. Invoice totals were reconciled, categorized, and merged into the original
   template order. Coverage and type checks fail closed before output.

## Findings by failure type

Category counts overlap because one error can affect the line amount, subtotal,
retention or VAT, and final total.

### 1. Rate and temporal-rule failures

Thirty-five civil applications and 61 drilling invoices contain a rate error.
These include superseded rates, incorrect indexed or FX-derived rates, wrong
factor ordering, and rates applied on the wrong side of an effective date.
Both contracts also omit a required retroactive adjustment: SAR 60,508.18 on
`PA-00006` and USD 309,965.52 on `MDS-01625`.

### 2. Evidence and quantity failures

Civil has 27 applications with evidence problems and 37 with quantity effects;
drilling has 43 invoices with quantity effects. Examples include absent civil
record files, the wrong record series, reused weekly dewatering logs, a gyro
charge whose DDR lacks required Part C, tool/personnel quantities beyond the
DDR, and metres beyond contractual tolerance.

### 3. Limits, duplicate, and event-eligibility failures

The audit detects civil daily-cap and exclusion breaches, duplicate civil
measurement, duplicate drilling events, extra mobilisation charges, unsupported
source-handling events, and services charged when tool/status evidence does not
permit them. These checks are stateful and cannot be found by testing arithmetic
or rate tables alone.

### 4. Invoice-level arithmetic failures

Civil retention is rebuilt from the corrected measured total and drilling VAT
from the corrected net. This propagates line corrections without double
counting them as new root causes. The audit also finds three direct line
arithmetic errors in each portfolio, 12 drilling discount errors, and the
missing civil retention release of SAR 4,027,429.62 on `PA-00678`.

## Error analysis of the approach

These are systematic ways the method can fail, rather than a list of detected
invoice errors.

### OCR table-boundary ambiguity

OCR can preserve prose while dropping a narrow numeric cell. On civil page 26,
the `C.32.010` daily cap repeatedly read as `an)`; it was resolved visually as
6. On the preceding band table, the middle `A.12.020` row was not recoverable
from OCR and was read as 97% using the surrounding boundaries plus independent
rate reconciliation. A wrong value here would propagate across many invoices.
Mitigation: multi-pass OCR, visual review for critical cells, and boundary tests.

### Finite-language evidence parsing

The parsers are deterministic and auditable, but depend on the terminology and
templates observed in this repository. A new civil phrase or rig synonym could
remain unmapped. Appendix G is intentionally non-obvious—for example report
terms do not always resemble the invoiced service. Mitigation: preserve raw
text, emit unmapped fields and parser errors, and treat unresolved evidence as
a query rather than guessing from price.

### Same-day ordering without timestamps

Three civil applications were submitted on the A3 issue date. The contract
requires the first application on or after issue to carry one adjustment, but
the data has dates rather than times. The implementation uses application
number as the deterministic tie-break and selects `PA-00006`. The three
same-day candidates receive lower confidence (0.90). A different intended
ordering would move the adjustment without changing its amount.

### Stateful-rule propagation

Rejecting an early line changes later cumulative quantity bands; choosing which
duplicate or weekly record is first changes which claim is payable. A single
evidence-classification error can therefore affect later rates. Mitigation:
order by contract-defined keys, separate eligibility from pricing, retain
line-level cumulative traces, and regression-test the full dataset.

## Reproducibility

Run `python scripts/build_submission.py` from the project root. It reparses all
raw evidence, reruns both audit engines, validates exact template coverage and
order, and rewrites `submission.csv`. Run `python -m pytest -q` for the complete
test suite.

