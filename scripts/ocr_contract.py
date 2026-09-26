from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pypdf import PdfReader
from pytesseract import Output


OCR_MODES = (3, 4, 6)

CRITICAL_TERMS = (
    "schedule",
    "rate",
    "rates",
    "price",
    "prices",
    "factor",
    "factors",
    "amendment",
    "supplement",
    "effective",
    "discount",
    "uplift",
    "adjustment",
    "retention",
    "cap",
    "limit",
    "limits",
    "minimum",
    "maximum",
    "once-only",
    "invoice",
    "payment",
    "commencement",
    "completion",
    "extension",
    "expiry",
    "rounding",
    "round",
    "vat",
    "tax",
)


def require_command(command: str) -> None:
    if shutil.which(command) is None:
        raise RuntimeError(
            f"Required system command '{command}' was not found."
        )


def render_page(
    pdf_path: Path,
    page_number: int,
    output_path: Path,
    dpi: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_prefix = output_path.with_suffix("")

    command = [
        "pdftoppm",
        "-f",
        str(page_number),
        "-l",
        str(page_number),
        "-r",
        str(dpi),
        "-png",
        "-singlefile",
        str(pdf_path),
        str(output_prefix),
    ]

    subprocess.run(command, check=True)


def estimate_skew_angle(gray_image: np.ndarray) -> float:
    blurred = cv2.GaussianBlur(gray_image, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)

    _, width = gray_image.shape

    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 1800,
        threshold=max(80, width // 10),
        minLineLength=max(100, width // 4),
        maxLineGap=max(20, width // 40),
    )

    if lines is None:
        return 0.0

    normalized_lines = np.asarray(lines).reshape(-1, 4)
    angles: list[float] = []

    for x1, y1, x2, y2 in normalized_lines:
        angle = np.degrees(
            np.arctan2(
                int(y2) - int(y1),
                int(x2) - int(x1),
            )
        )

        if -5.0 <= angle <= 5.0:
            angles.append(float(angle))

    if not angles:
        return 0.0

    median_angle = float(np.median(angles))

    if abs(median_angle) < 0.05:
        return 0.0

    return median_angle


def rotate_image(
    image: np.ndarray,
    angle: float,
    border_value: int = 255,
) -> np.ndarray:
    if angle == 0.0:
        return image

    height, width = image.shape[:2]
    center = (width / 2, height / 2)

    matrix = cv2.getRotationMatrix2D(
        center,
        angle,
        1.0,
    )

    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_value,
    )


def preprocess_image(
    input_path: Path,
    output_path: Path,
) -> float:
    image = cv2.imread(
        str(input_path),
        cv2.IMREAD_GRAYSCALE,
    )

    if image is None:
        raise RuntimeError(
            f"Could not read image: {input_path}"
        )

    denoised = cv2.fastNlMeansDenoising(
        image,
        None,
        h=7,
        templateWindowSize=7,
        searchWindowSize=21,
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )
    enhanced = clahe.apply(denoised)

    skew_angle = estimate_skew_angle(enhanced)
    corrected = rotate_image(enhanced, skew_angle)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not cv2.imwrite(str(output_path), corrected):
        raise RuntimeError(
            f"Could not write image: {output_path}"
        )

    return skew_angle


def reconstruct_text(data: dict[str, list]) -> str:
    lines: list[str] = []
    current_key: tuple[int, int, int, int] | None = None
    current_words: list[str] = []

    for index, raw_word in enumerate(data["text"]):
        word = str(raw_word).strip()

        if not word:
            continue

        key = (
            int(data["page_num"][index]),
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )

        if current_key is not None and key != current_key:
            lines.append(" ".join(current_words))
            current_words = []

        current_key = key
        current_words.append(word)

    if current_words:
        lines.append(" ".join(current_words))

    return "\n".join(lines).strip() + "\n"


def run_ocr(
    image_path: Path,
    psm: int,
) -> tuple[str, dict[str, float | int]]:
    image = cv2.imread(
        str(image_path),
        cv2.IMREAD_GRAYSCALE,
    )

    if image is None:
        raise RuntimeError(
            f"Could not read image: {image_path}"
        )

    config = (
        f"--oem 1 --psm {psm} "
        "-c preserve_interword_spaces=1"
    )

    data = pytesseract.image_to_data(
        image,
        lang="eng",
        config=config,
        output_type=Output.DICT,
    )

    text = reconstruct_text(data)

    confidences = [
        float(value)
        for value in data["conf"]
        if str(value) != "-1" and float(value) >= 0
    ]

    word_count = sum(
        1
        for word in data["text"]
        if str(word).strip()
    )

    mean_confidence = (
        round(float(np.mean(confidences)), 2)
        if confidences
        else 0.0
    )
    median_confidence = (
        round(float(np.median(confidences)), 2)
        if confidences
        else 0.0
    )
    low_confidence_words = sum(
        1 for value in confidences if value < 70
    )
    low_confidence_ratio = (
        round(low_confidence_words / word_count, 4)
        if word_count
        else 0.0
    )

    stats: dict[str, float | int] = {
        "word_count": word_count,
        "mean_confidence": mean_confidence,
        "median_confidence": median_confidence,
        "low_confidence_words": low_confidence_words,
        "low_confidence_ratio": low_confidence_ratio,
    }

    return text, stats


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def find_critical_terms(texts: list[str]) -> list[str]:
    combined_text = normalize_text(" ".join(texts))
    found_terms: list[str] = []

    for term in CRITICAL_TERMS:
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"

        if re.search(pattern, combined_text):
            found_terms.append(term)

    return found_terms


def calculate_similarities(
    texts: dict[int, str],
) -> dict[str, float]:
    similarities: dict[str, float] = {}

    mode_pairs = (
        (3, 4),
        (3, 6),
        (4, 6),
    )

    for first_mode, second_mode in mode_pairs:
        first_text = normalize_text(
            texts[first_mode]
        )
        second_text = normalize_text(
            texts[second_mode]
        )

        score = SequenceMatcher(
            None,
            first_text,
            second_text,
        ).ratio()

        key = f"psm{first_mode}_vs_psm{second_mode}"
        similarities[key] = round(score, 4)

    return similarities


def determine_review_reasons(
    texts: dict[int, str],
    stats: dict[int, dict[str, float | int]],
    similarities: dict[str, float],
) -> tuple[list[str], list[str]]:
    review_reasons: list[str] = []

    critical_terms = find_critical_terms(
        list(texts.values())
    )

    if critical_terms:
        review_reasons.append(
            "critical_contract_terms_present"
        )

    minimum_similarity = min(
        similarities.values(),
        default=0.0,
    )

    if minimum_similarity < 0.95:
        review_reasons.append(
            "ocr_modes_disagree"
        )

    for psm, mode_stats in stats.items():
        mean_confidence = float(
            mode_stats["mean_confidence"]
        )
        low_confidence_ratio = float(
            mode_stats["low_confidence_ratio"]
        )

        if mean_confidence < 90:
            review_reasons.append(
                f"psm{psm}_mean_confidence_below_90"
            )

        if low_confidence_ratio > 0.05:
            review_reasons.append(
                f"psm{psm}_low_confidence_ratio_above_5pct"
            )

    review_reasons = sorted(set(review_reasons))

    return review_reasons, critical_terms


def process_contract(
    pdf_path: Path,
    contract_name: str,
    output_root: Path,
    dpi: int,
    start_page: int,
    end_page: int | None,
    force: bool,
) -> None:
    require_command("pdftoppm")
    require_command("tesseract")

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}"
        )

    total_pages = len(
        PdfReader(str(pdf_path)).pages
    )

    final_page = (
        end_page
        if end_page is not None
        else total_pages
    )

    if start_page < 1 or final_page > total_pages:
        raise ValueError(
            f"Page range must be between 1 and {total_pages}."
        )

    if start_page > final_page:
        raise ValueError(
            "start_page cannot be greater than end_page."
        )

    image_root = (
        output_root / "images" / contract_name
    )
    raw_image_dir = image_root / "raw"
    clean_image_dir = image_root / "clean"
    text_dir = (
        output_root / "text" / contract_name
    )

    raw_image_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    clean_image_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    text_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata: list[dict] = []
    combined_texts: dict[int, list[str]] = {
        psm: [] for psm in OCR_MODES
    }

    for page_number in range(
        start_page,
        final_page + 1,
    ):
        page_stem = f"page_{page_number:03d}"

        raw_path = (
            raw_image_dir / f"{page_stem}.png"
        )
        clean_path = (
            clean_image_dir / f"{page_stem}.png"
        )
        metadata_path = (
            text_dir / f"{page_stem}_metadata.json"
        )

        print(
            f"[{contract_name}] Processing page "
            f"{page_number}/{final_page}"
        )

        if force or not raw_path.exists():
            render_page(
                pdf_path=pdf_path,
                page_number=page_number,
                output_path=raw_path,
                dpi=dpi,
            )

        skew_angle = preprocess_image(
            input_path=raw_path,
            output_path=clean_path,
        )

        page_texts: dict[int, str] = {}
        page_stats: dict[
            int,
            dict[str, float | int],
        ] = {}

        for psm in OCR_MODES:
            text, stats = run_ocr(
                image_path=raw_path,
                psm=psm,
            )

            page_texts[psm] = text
            page_stats[psm] = stats

            text_path = (
                text_dir
                / f"{page_stem}_psm{psm}.txt"
            )
            text_path.write_text(
                text,
                encoding="utf-8",
            )

            combined_texts[psm].append(
                f"\n===== PAGE {page_number} =====\n"
                f"{text}"
            )

        similarities = calculate_similarities(
            page_texts
        )

        review_reasons, critical_terms = (
            determine_review_reasons(
                texts=page_texts,
                stats=page_stats,
                similarities=similarities,
            )
        )

        page_metadata = {
            "page": page_number,
            "dpi": dpi,
            "primary_ocr_image": "raw",
            "estimated_skew_angle": round(
                skew_angle,
                3,
            ),
            "ocr_stats": {
                f"psm{psm}": page_stats[psm]
                for psm in OCR_MODES
            },
            "text_similarities": similarities,
            "critical_terms_found": critical_terms,
            "requires_review": bool(review_reasons),
            "review_reasons": review_reasons,
        }

        metadata_path.write_text(
            json.dumps(
                page_metadata,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        metadata.append(page_metadata)

    for psm in OCR_MODES:
        combined_path = (
            text_dir
            / f"{contract_name}_psm{psm}.txt"
        )
        combined_path.write_text(
            "".join(combined_texts[psm]).lstrip(),
            encoding="utf-8",
        )

    summary_path = (
        text_dir
        / f"{contract_name}_ocr_summary.json"
    )
    summary_path.write_text(
        json.dumps(
            {
                "contract": contract_name,
                "source_pdf": str(pdf_path),
                "total_pdf_pages": total_pages,
                "processed_pages": [
                    start_page,
                    final_page,
                ],
                "ocr_modes": list(OCR_MODES),
                "pages": metadata,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    review_count = sum(
        1
        for page in metadata
        if page["requires_review"]
    )

    print(
        f"Completed {len(metadata)} page(s). "
        f"{review_count} page(s) require review."
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render, preprocess, and OCR a scanned "
            "contract using multiple Tesseract modes."
        )
    )

    parser.add_argument(
        "--pdf",
        required=True,
        type=Path,
        help="Path to the scanned contract PDF.",
    )
    parser.add_argument(
        "--name",
        required=True,
        help=(
            "Short contract name used for "
            "output folders."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/ocr"),
        help="Root output directory.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Rendering resolution. Default: 300.",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First page to process.",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=None,
        help=(
            "Last page to process. Defaults "
            "to the final PDF page."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-render existing raw page images.",
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    process_contract(
        pdf_path=arguments.pdf,
        contract_name=arguments.name,
        output_root=arguments.output_root,
        dpi=arguments.dpi,
        start_page=arguments.start_page,
        end_page=arguments.end_page,
        force=arguments.force,
    )


if __name__ == "__main__":
    main()