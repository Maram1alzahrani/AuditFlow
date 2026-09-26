# Invoice Audit Exercise — Level 2

Two contractors bill against two long-running contracts: a civil engineering
term subcontract and a directional drilling services contract. Both contracts
were amended while they ran. Both contractors invoice monthly against site
paperwork. Some of those invoices are wrong — a rate that was superseded, a
quantity beyond what the record supports, an uplift where the contract
suspends it, an adjustment omitted or taken early, a charge billed twice.

Your job is to audit **every** invoice under both contracts and say which ones
are wrong.

## What you have

```
civilwork/
  contract/CW-2025-0417-CIV.pdf           43 scanned pages, no text layer
  guidelines/INVOICE_AUDIT_GUIDELINES.md  the 12 checks, in order
  invoices/applications.csv               900 payment applications
  invoices/application_lines.csv          7,746 lines
  records/                                2,169 site records (.txt)

drilling_services/
  contract/DDS-2025-118.pdf               42 scanned pages, no text layer
  guidelines/INVOICE_AUDIT_GUIDELINES.md  the same 12 checks, for this contract
  invoices/invoices.csv                   1,906 invoices
  invoices/invoice_lines.csv              91,244 lines
  records/                                8,151 daily drilling reports (.txt)

submission_template.csv                   2,806 rows — one per invoice
```

**The contracts are scans.** Each PDF is a photograph of a paper contract:
skewed pages, uneven illumination, scanner grain, JPEG artefacts, and no text
layer at all. Getting the terms out of them is the first part of the task, not
a preliminary to it. Everything you need to price a line is in there —
schedules of rates, the supplements and amendments that change them, the
definitions that decide what is chargeable.

**The records are free text.** A site record or a daily report is written the
way the site writes it, not the way the contract does. The same contracted
item is described several ways, and a record rarely quotes an item code.
Establishing which priced item a charge belongs to, and which record evidences
it, is part of the task.

**No answers are included.** There is no development set and no labelled
sample. Calibrate against the contract itself: if your reading of a clause
reprices invoices that reconcile exactly as billed, your reading is probably
wrong.

## The data

Both invoice files carry one row per invoice and one row per line in the
`_lines` file, joined on the invoice number (`application_no` for civil works,
`invoice_no` for drilling). Line rows carry the reference of the record that
evidences them (`record_ref`, `report_ref`); those references are the join
into `records/`.

Money in the CSVs is printed in the contract's own currency with two decimal
places — SAR for the civil works subcontract, USD for the drilling contract.
**The submission file takes integer minor units**: multiply by 100, so
`265123.89` is `26512389`. There are no fractional amounts in a submission.

The figure you are judging on is the invoice total as billed:
`application_total` for a civil works application, `invoice_total` for a
drilling invoice.

## The task

Apply the twelve checks in `INVOICE_AUDIT_GUIDELINES.md` to every invoice
under both contracts, and record the outcome for each one in a **single
submission file**. Start from `submission_template.csv`, which already lists
every invoice id in the exercise, and fill it in.

| column | meaning |
|---|---|
| `invoice_id` | the invoice this row is about — leave the ids as they are |
| `flagged` | `1` if you believe the invoice is wrong, `0` if you believe it is correct |
| `error_category` | your own short label for what is wrong; free text, blank when not flagged |
| `expected_total_cents` | what you believe the invoice should have totalled, in minor units |
| `billed_total_cents` | what it actually totalled, in minor units |
| `confidence` | how sure you are of this row, between 0 and 1 |

Return all 2,806 rows in one file. A `0` is a claim, not a blank: it says you
audited the invoice and found nothing. Rows you cannot price are still rows —
flag them if you believe they are wrong, give your confidence honestly, and
say in your report what you could not determine.

Between 5% and 8% of the invoices are wrong. Some of the ones that look odd
are correct, and are there to be left alone.

## How it is scored

* **Detection.** Precision, recall and F1 on `flagged`, overall and by
  severity.
* **Cost.** `5 × false negatives + 1 × false positives`, lower is better. A
  missed error costs five times what a needless flag costs, and flagging
  everything costs more than flagging nothing.
* **Amounts.** Where you flag an invoice, whether `expected_total_cents` is
  the figure the contract actually supports.
* **Calibration.** Your stated `confidence` against your precision in each
  band. A confidently wrong extraction is worse than a flagged uncertainty: an
  extracted rate that is wrong propagates silently into every invoice that
  touches it, while a stated doubt costs a reviewer a few minutes.
* **Category.** Whether your `error_category` separates the kinds of error you
  found — your own vocabulary is fine, consistency is what matters.

## Ground rules

- The data is synthetic. There is no real contractor, well or site.
- Everything you need is in this repository. There is nothing to look up
  externally.
- Where the guidelines and the contract differ, the contract governs — and the
  difference is worth reporting.
- If a clause is genuinely ambiguous, it may well be. Record your reading in
  the decision log and move on; do not spend the budget on it.

## AI assistance

Using AI assistance is permitted and expected. It must be disclosed. Include
your prompts as versioned files in your repository, so we can see how you
worked and not only what you produced.

## Deliverables

1. **A runnable repository.** We should be able to clone it, follow your
   README, and reproduce your submission file. Pin your dependencies.
2. **`submission.csv`**, in the template format, covering all 2,806 invoices.
3. **A short report**: how the approach performs, and an error analysis
   grouped by *failure type* — the three or four systematic ways your approach
   goes wrong, with an example of each, rather than a list of individual
   misses.
4. **Your prompts, as versioned files.** If you iterated on a prompt, we would
   like to see that it was iterated on.
5. **A one-page decision log**: the assumptions you made, the ambiguities you
   found and could not resolve, and what you decided about each. If you read a
   clause two ways and had to pick one, that belongs here.
