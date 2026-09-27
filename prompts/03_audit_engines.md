# Prompt 03 — Audit engines

## Initial prompt

Implement deterministic civil and drilling invoice audit engines from the
verified contracts and parsed evidence. Reprice every line with `Decimal`,
respect each contract's rounding stage, issue/effective dates, amendments,
factors, quantity tolerances, evidence conditions, duplicates, limits, invoice
arithmetic, and final total. Emit line-level explanations and invoice-level
submission fields. Do not use a statistical anomaly threshold or the expected
5–8% error rate to choose flags.

## Important follow-ups

- Civil: implement global contract-year bands in work-date, application-number,
  line-number order; split a line crossing a band and sum its rounded parts.
- Civil: force G2 only in the extension period, suppress night uplift when the
  zone factor exceeds 1.1, and use rest-day uplift alone without a written
  concurrent-uplift instruction.
- Civil: records are conditions of payment; apply 2% surveyed tolerance, daily
  caps, mutual exclusions, duplicate rules, retention, release, and A3.
- Drilling: round half-even at each build-up step; handle standby, minimum and
  chargeable hours, depth bands, run/well events, 1% metre tolerance, lost-tool
  FX/depreciation, discount, VAT, and A3.
- Recalculate downstream totals from corrected lines. Do not patch only the
  visible billed total.

