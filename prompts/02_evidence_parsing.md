# Prompt 02 — Evidence parsing

## Initial prompt

Parse every civil site record and drilling Daily Drilling Report into structured
evidence. Infer meaning only from the record text and contract terminology, not
from billed prices or amounts. Preserve the raw phrase, mapped item/service,
date, location or well, quantity, unit, signatures, report parts, tools,
personnel, run data, and parse errors. Produce CSV and JSON summaries and make
unmapped language visible.

## Iterations

1. Profile every distinct free-text template before writing mappings.
2. For civil records, validate ticket series, area, date/week, signature pair,
   inferred item, quantity, and unit.
3. For drilling, use Appendix G even when the report term is counter-intuitive;
   parse Parts A–E independently.
4. Surface `gyro_count_without_part_c` rather than synthesizing the missing
   evidence.
5. Confirm that all referenced report IDs join to source files and list missing,
   unused, repeated, or wrongly typed civil references.

