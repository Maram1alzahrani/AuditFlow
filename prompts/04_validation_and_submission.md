# Prompt 04 — Validation and submission

## Initial prompt

Challenge the audit results before submission. Look for false positives caused
by parser schema differences, band-crossing arithmetic, missing evidence, date
joins, and duplicated records. Require full-dataset regression tests. Then build
one submission in the exact supplied schema and row order; fail if any ID is
missing, unexpected, duplicated, null, or type-invalid.

## Iterations that changed the result

1. A full ground label (`G4 Weathered Rock`) was incorrectly compared with a
   parsed code (`G4`), producing hundreds of false positives. Normalize the
   comparison.
2. Weekly records use `week_beginning`, not `record_date`. Validate the work
   date within the seven-day week.
3. An invalid use of a record must not consume that record before its valid use;
   filter record-reuse ordering to valid type/item matches.
4. A band-crossing civil line is the sum of its parts; do not report ordinary
   `quantity × displayed rate` arithmetic as an error for that line.
5. Rebuild parsed evidence from raw records inside the final builder so a fresh
   clone reproduces the output without committed artifacts.

## Final controls requested

- Run every test, not only portfolio-specific tests.
- Confirm 2,806 rows and 2,806 unique IDs.
- Confirm exact template order and columns.
- Confirm no nulls, duplicate IDs, or flagged rows without a category.
- Keep confidence lower where a material ordering ambiguity remains.

