# Prompt 01 — Contract extraction

## Initial prompt

Act as a senior contract auditor and OCR engineer. Build a reproducible Python
pipeline for both scanned contracts. Use multiple Tesseract layout modes,
preserve page-level text and metadata, and flag pages where OCR modes disagree,
confidence is low, or critical contractual terms occur. Do not silently repair
uncertain rates, dates, factors, limits, or item codes. I will visually verify
critical pages.

## Iterations

1. A Hough-line result caused a NumPy unpacking error. Update the full script to
   normalize OpenCV line shapes before unpacking.
2. Raw images produced cleaner table text than deskewed images. Keep both, use
   raw as the primary OCR source, and compare PSM 3, 4, and 6.
3. Do not treat the presence of contractual keywords alone as an OCR failure;
   preserve it as a review reason.
4. For unreadable critical cells, stop and request a page image instead of
   guessing. This resolved civil `C.32.010` as 6.

## Constraints retained

- The contract overrides the guidelines.
- Report uncertainty explicitly.
- Never tune a rule merely to reduce the number of flags.
- Send complete replacement files when code changes.

