#!/usr/bin/env python3
"""Extract textbook-style PDF tasks into a self-contained image/JSON bundle.

Expected layout:
- a red document header on the first page;
- task headings such as ``1. 439B4A``;
- one or more answer pages after the task pages, headed ``Ответы``;
- answer entries such as ``1. 34`` or table rows such as
  ``1 439B4A 34``, arranged in one or more columns.

Usage:
    python pdf_task_bundle_extractor.py /path/to/file.pdf
    python pdf_task_bundle_extractor.py /path/to/file.pdf --output-root ./bundles
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

try:
    import pdfplumber
    from PIL import Image
except ImportError as exc:  # pragma: no cover - friendly CLI error
    print(
        "Missing Python dependencies. Run: "
        "python -m pip install pdfplumber Pillow",
        file=sys.stderr,
    )
    raise SystemExit(3) from exc


TASK_HEADING_RE = re.compile(r"^(\d{1,4})\.\s*([0-9A-Za-z]{6})$")
ANSWER_NUMBER_RE = re.compile(r"^(\d{1,4})\.$")
PLAIN_NUMBER_RE = re.compile(r"^(\d{1,4})$")
TASK_ID_RE = re.compile(r"^[0-9A-Za-z]{6}$")
FOOTER_NUMBER_RE = re.compile(r"^\d{1,4}$")


class FormatError(RuntimeError):
    """Raised when a PDF does not match the supported template."""


TRANSLITERATION = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a supported PDF and create a folder containing source.pdf, "
            "images/, and meta.json."
        )
    )
    parser.add_argument("pdf", type=Path, help="Path to the source PDF")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path.cwd(),
        help="Parent directory for the generated bundle (default: current directory)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Rendering resolution for PNG crops (default: 200)",
    )
    return parser.parse_args()


def transliterate_slug(value: str) -> str:
    pieces: list[str] = []
    for char in unicodedata.normalize("NFC", value).lower():
        if char in TRANSLITERATION:
            pieces.append(TRANSLITERATION[char])
        elif char.isascii() and char.isalnum():
            pieces.append(char)
        else:
            pieces.append("-")
    slug = re.sub(r"-+", "-", "".join(pieces)).strip("-")
    return slug or "pdf-bundle"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_color(color: Any) -> tuple[float, ...] | None:
    if color is None:
        return None
    if isinstance(color, (int, float)):
        values = (float(color),)
    elif isinstance(color, (tuple, list)):
        try:
            values = tuple(float(value) for value in color)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if values and max(values) > 1.0:
        values = tuple(value / 255.0 for value in values)
    return values


def is_red(color: Any) -> bool:
    values = normalize_color(color)
    if not values:
        return False
    if len(values) == 3:
        red, green, blue = values
    elif len(values) == 4:
        cyan, magenta, yellow, black = values
        red = 1.0 - min(1.0, cyan + black)
        green = 1.0 - min(1.0, magenta + black)
        blue = 1.0 - min(1.0, yellow + black)
    else:
        return False
    return red >= 0.65 and red >= green + 0.25 and red >= blue + 0.25


def cluster_by_top(items: Iterable[dict[str, Any]], tolerance: float = 2.0) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda value: (float(value["top"]), float(value["x0"]))):
        for cluster in clusters:
            average_top = sum(float(value["top"]) for value in cluster) / len(cluster)
            if abs(float(item["top"]) - average_top) <= tolerance:
                cluster.append(item)
                break
        else:
            clusters.append([item])
    return sorted(clusters, key=lambda cluster: min(float(value["top"]) for value in cluster))


def join_chars(chars: list[dict[str, Any]]) -> str:
    output: list[str] = []
    previous_x1: float | None = None
    previous_size = 10.0
    for char in sorted(chars, key=lambda value: float(value["x0"])):
        text = str(char.get("text", ""))
        if not text:
            continue
        x0 = float(char["x0"])
        if (
            previous_x1 is not None
            and x0 - previous_x1 > max(1.5, previous_size * 0.28)
            and output
            and not output[-1].endswith(" ")
            and not text.isspace()
        ):
            output.append(" ")
        output.append(text)
        previous_x1 = float(char["x1"])
        previous_size = float(char.get("size", previous_size))
    return re.sub(r"\s+", " ", "".join(output)).strip()


def extract_red_header(page: Any) -> tuple[str, list[str]]:
    red_chars = [
        char
        for char in page.chars
        if str(char.get("text", ""))
        and is_red(char.get("non_stroking_color"))
    ]
    lines = [join_chars(cluster) for cluster in cluster_by_top(red_chars)]
    lines = [line for line in lines if line]
    return "\n".join(lines), lines


def extract_lines(page: Any) -> list[dict[str, Any]]:
    try:
        lines = page.extract_text_lines(strip=True, return_chars=False)
    except AttributeError as exc:
        raise FormatError(
            "pdfplumber is too old; install pdfplumber>=0.11"
        ) from exc
    return [line for line in lines if str(line.get("text", "")).strip()]


def find_task_headings(page: Any) -> list[dict[str, Any]]:
    """Find task headings even when PDF text-line extraction overlaps a header.

    Word-generated PDFs can assign an incorrect text coordinate to the repeating
    page header. When that coordinate overlaps ``3. ABC123``, line extraction
    interleaves the two strings. Task headings are bold in the supported
    template, so reconstructing bold character runs is more reliable.
    """
    candidates: list[dict[str, Any]] = []

    bold_chars = [
        char
        for char in page.chars
        if "bold" in str(char.get("fontname", "")).lower()
        and str(char.get("text", ""))
    ]
    for cluster in cluster_by_top(bold_chars, tolerance=1.5):
        text = join_chars(cluster)
        match = TASK_HEADING_RE.fullmatch(text)
        if match:
            x0, top, x1, bottom = union_bbox(cluster)
            candidates.append(
                {
                    "number": int(match.group(1)),
                    "id": match.group(2),
                    "x0": x0,
                    "top": top,
                    "x1": x1,
                    "bottom": bottom,
                }
            )

    # Fallback for compatible PDFs whose task heading font is not marked bold.
    for line in extract_lines(page):
        match = TASK_HEADING_RE.fullmatch(str(line["text"]).strip())
        if match:
            candidates.append(
                {
                    "number": int(match.group(1)),
                    "id": match.group(2),
                    "x0": float(line["x0"]),
                    "top": float(line["top"]),
                    "x1": float(line["x1"]),
                    "bottom": float(line["bottom"]),
                }
            )

    unique: dict[int, dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda item: float(item["top"])):
        existing = unique.get(candidate["number"])
        if existing is None:
            unique[candidate["number"]] = candidate
        elif existing["id"].lower() != candidate["id"].lower():
            raise FormatError(
                f"Conflicting IDs for task {candidate['number']}: "
                f"{existing['id']} and {candidate['id']}"
            )
    return sorted(unique.values(), key=lambda item: float(item["top"]))


def union_bbox(items: Iterable[dict[str, Any]]) -> tuple[float, float, float, float]:
    materialized = list(items)
    if not materialized:
        raise ValueError("Cannot calculate an empty bounding box")
    return (
        min(float(item["x0"]) for item in materialized),
        min(float(item["top"]) for item in materialized),
        max(float(item["x1"]) for item in materialized),
        max(float(item["bottom"]) for item in materialized),
    )


def pad_bbox(
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    horizontal: float,
    vertical: float,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (
        max(0.0, x0 - horizontal),
        max(0.0, y0 - vertical),
        min(page_width, x1 + horizontal),
        min(page_height, y1 + vertical),
    )


def source_metadata(
    page_number: int,
    bbox_top_left: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    x0, y0, x1, y1 = bbox_top_left
    return {
        "pdf": "source.pdf",
        "page": page_number,
        "page_url": f"source.pdf#page={page_number}",
        "bbox_top_left_points": [round(value, 3) for value in bbox_top_left],
        "bbox_pdf_points": [
            round(x0, 3),
            round(page_height - y1, 3),
            round(x1, 3),
            round(page_height - y0, 3),
        ],
        "bbox_normalized_top_left": [
            round(x0 / page_width, 8),
            round(y0 / page_height, 8),
            round(x1 / page_width, 8),
            round(y1 / page_height, 8),
        ],
    }


def find_tasks(pdf: Any) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for page_index, page in enumerate(pdf.pages):
        starts = find_task_headings(page)
        if not starts:
            continue

        page_width = float(page.width)
        page_height = float(page.height)
        content_cutoff = page_height - 65.0
        footer_tops = [
            float(line["top"])
            for line in extract_lines(page)
            if FOOTER_NUMBER_RE.fullmatch(str(line["text"]).strip())
            and float(line["top"]) > page_height - 90.0
            and abs(
                (float(line["x0"]) + float(line["x1"])) / 2.0
                - page_width / 2.0
            )
            < 50.0
        ]
        footer_top = min(footer_tops) if footer_tops else None

        for index, start in enumerate(starts):
            start_top = float(start["top"])
            next_top = (
                float(starts[index + 1]["top"])
                if index + 1 < len(starts)
                else None
            )
            # Thematic compilations can place a red section title between two
            # numbered tasks. It belongs to neither task crop, so treat it as
            # an earlier boundary for the preceding task.
            red_section_tops = [
                float(char["top"])
                for char in page.chars
                if str(char.get("text", "")).strip()
                and is_red(char.get("non_stroking_color"))
                and float(char["top"]) > start_top + 8.0
                and (next_top is None or float(char["top"]) < next_top)
            ]
            boundary_top = next_top
            if red_section_tops:
                boundary_top = min(red_section_tops)
            region_chars = [
                char
                for char in page.chars
                if str(char.get("text", "")).strip()
                and float(char["top"]) >= start_top - 1.0
                and (boundary_top is None or float(char["top"]) < boundary_top)
                and float(char["top"]) < content_cutoff
            ]
            region_images = [
                image
                for image in page.images
                if float(image["top"]) >= start_top - 1.0
                and (boundary_top is None or float(image["top"]) < boundary_top)
                and float(image["top"]) < content_cutoff
            ]

            if boundary_top is not None:
                y1 = boundary_top - 6.0
            else:
                bottoms = [float(char["bottom"]) for char in region_chars]
                bottoms.extend(float(image["bottom"]) for image in region_images)
                if not bottoms:
                    raise FormatError(
                        f"Could not determine the bottom of task {start['number']}"
                    )
                y1 = min(page_height, max(bottoms) + 8.0)
            if footer_top is not None:
                y1 = min(y1, footer_top - 1.0)

            horizontal_items = [*region_chars, *region_images]
            if not horizontal_items:
                raise FormatError(
                    f"Could not determine the width of task {start['number']}"
                )
            x0 = max(0.0, min(float(item["x0"]) for item in horizontal_items) - 8.0)
            x1 = min(page_width, max(float(item["x1"]) for item in horizontal_items) + 8.0)
            y0 = max(0.0, start_top - 6.0)
            bbox = (x0, y0, x1, y1)
            if x1 <= x0 or y1 <= y0:
                raise FormatError(f"Invalid crop for task {start['number']}: {bbox}")

            tasks.append(
                {
                    "id": start["id"],
                    "number": start["number"],
                    "page_index": page_index,
                    "page_number": page_index + 1,
                    "page_width": page_width,
                    "page_height": page_height,
                    "bbox": bbox,
                }
            )

    tasks.sort(key=lambda item: item["number"])
    return tasks


def find_answer_page_start(pdf: Any, last_task_page_index: int) -> int:
    for page_index in range(last_task_page_index + 1, len(pdf.pages)):
        page = pdf.pages[page_index]
        text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
        if re.search(r"(?im)^\s*Ответы\s*$", text):
            return page_index

        # In some Word-generated PDFs the answer heading overlaps the blue
        # repeating page header.  The general text extractor then merges the
        # two strings (for example, ``Онлайн-Оштквоелтаы``), while the heading
        # itself remains a separate bold character run.  Keep the exact
        # heading requirement and use that run only as a narrow fallback.
        bold_chars = [
            char
            for char in page.chars
            if "bold" in str(char.get("fontname", "")).lower()
            and str(char.get("text", ""))
        ]
        if any(
            join_chars(cluster) == "Ответы"
            for cluster in cluster_by_top(bold_chars, tolerance=1.5)
        ):
            return page_index
    raise FormatError("No answer section headed 'Ответы' was found after the tasks")


def find_answers(pdf: Any, first_page_index: int) -> dict[int, dict[str, Any]]:
    answers: dict[int, dict[str, Any]] = {}
    for page_index in range(first_page_index, len(pdf.pages)):
        page = pdf.pages[page_index]
        words = page.extract_words(
            x_tolerance=2,
            y_tolerance=3,
            keep_blank_chars=False,
            use_text_flow=False,
        )
        for line_words in cluster_by_top(words, tolerance=2.0):
            ordered = sorted(line_words, key=lambda word: float(word["x0"]))
            number_positions = [
                index
                for index, word in enumerate(ordered)
                if ANSWER_NUMBER_RE.fullmatch(str(word["text"]).strip())
            ]
            for position_index, word_index in enumerate(number_positions):
                number_word = ordered[word_index]
                number_match = ANSWER_NUMBER_RE.fullmatch(
                    str(number_word["text"]).strip()
                )
                if number_match is None:
                    continue
                number = int(number_match.group(1))
                next_number_x = (
                    float(ordered[number_positions[position_index + 1]]["x0"])
                    if position_index + 1 < len(number_positions)
                    else math.inf
                )
                answer_words = [
                    candidate
                    for candidate in ordered[word_index + 1 :]
                    if float(candidate["x0"]) < next_number_x
                ]
                if not answer_words:
                    continue
                segment = [number_word, *answer_words]
                bbox = pad_bbox(
                    union_bbox(segment),
                    float(page.width),
                    float(page.height),
                    horizontal=5.0,
                    vertical=4.0,
                )
                answer_text = " ".join(
                    str(candidate["text"]).strip() for candidate in answer_words
                ).strip()
                if number in answers:
                    raise FormatError(f"Duplicate answer number: {number}")
                answers[number] = {
                    "number": number,
                    "text": answer_text,
                    "page_index": page_index,
                    "page_number": page_index + 1,
                    "page_width": float(page.width),
                    "page_height": float(page.height),
                    "bbox": bbox,
                }

            # A newer template uses a table with repeating triplets:
            # ``task number | FIPI ID | answer``. A physical row can contain
            # several such triplets, so locate every number+ID start and crop
            # only up to the next triplet on that row.
            table_starts = [
                index
                for index in range(len(ordered) - 1)
                if PLAIN_NUMBER_RE.fullmatch(str(ordered[index]["text"]).strip())
                and TASK_ID_RE.fullmatch(
                    str(ordered[index + 1]["text"]).strip()
                )
            ]
            for start_index, word_index in enumerate(table_starts):
                end_index = (
                    table_starts[start_index + 1]
                    if start_index + 1 < len(table_starts)
                    else len(ordered)
                )
                segment = ordered[word_index:end_index]
                if len(segment) < 3:
                    continue

                number_match = PLAIN_NUMBER_RE.fullmatch(
                    str(segment[0]["text"]).strip()
                )
                if number_match is None:
                    continue
                number = int(number_match.group(1))
                task_id = str(segment[1]["text"]).strip()
                answer_words = segment[2:]
                answer_text = " ".join(
                    str(candidate["text"]).strip()
                    for candidate in answer_words
                ).strip()
                if not answer_text:
                    continue

                bbox = pad_bbox(
                    union_bbox(segment),
                    float(page.width),
                    float(page.height),
                    horizontal=5.0,
                    vertical=1.0,
                )
                if number in answers:
                    raise FormatError(f"Duplicate answer number: {number}")
                answers[number] = {
                    "number": number,
                    "task_id": task_id,
                    "text": answer_text,
                    "page_index": page_index,
                    "page_number": page_index + 1,
                    "page_width": float(page.width),
                    "page_height": float(page.height),
                    "bbox": bbox,
                }
    return answers


def validate_format(
    pdf: Any,
) -> tuple[
    str,
    list[str],
    list[dict[str, Any]],
    dict[int, dict[str, Any]],
    int,
    list[str],
]:
    if len(pdf.pages) < 2:
        raise FormatError("The PDF must contain task pages and at least one answer page")

    header, header_lines = extract_red_header(pdf.pages[0])
    if not header_lines:
        raise FormatError("No red header text was found on the first page")

    tasks = find_tasks(pdf)
    if not tasks:
        raise FormatError("No task headings matching 'NUMBER. SIX_CHAR_ID' were found")

    numbers = [task["number"] for task in tasks]
    expected_numbers = list(range(1, len(tasks) + 1))
    if numbers != expected_numbers:
        raise FormatError(
            f"Task numbering must be continuous from 1; found {numbers[:10]}..."
        )
    validation_warnings: list[str] = []
    id_occurrences: dict[str, list[int]] = {}
    id_spellings: dict[str, str] = {}
    for task in tasks:
        normalized_id = str(task["id"]).lower()
        id_occurrences.setdefault(normalized_id, []).append(task["number"])
        id_spellings.setdefault(normalized_id, str(task["id"]))
    for normalized_id, task_numbers in sorted(id_occurrences.items()):
        if len(task_numbers) > 1:
            validation_warnings.append(
                f"Task ID {id_spellings[normalized_id]} is repeated at task "
                f"numbers {', '.join(map(str, task_numbers))}"
            )

    last_task_page_index = max(task["page_index"] for task in tasks)
    answer_page_start = find_answer_page_start(pdf, last_task_page_index)
    answers = find_answers(pdf, answer_page_start)

    task_numbers = set(numbers)
    answer_numbers = set(answers)
    missing = sorted(task_numbers - answer_numbers)
    extra = sorted(answer_numbers - task_numbers)
    if missing or extra:
        raise FormatError(
            f"Task/answer mismatch; missing answers={missing}, extra answers={extra}"
        )

    task_ids_by_number = {task["number"]: task["id"] for task in tasks}
    mismatched_ids = [
        number
        for number, answer in sorted(answers.items())
        if answer.get("task_id")
        and str(answer["task_id"]).lower()
        != str(task_ids_by_number[number]).lower()
    ]
    if mismatched_ids:
        raise FormatError(
            "Task IDs in the answer table do not match the task pages: "
            f"{mismatched_ids}"
        )

    return (
        header,
        header_lines,
        tasks,
        answers,
        answer_page_start,
        validation_warnings,
    )


def locate_pdftoppm() -> str:
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise RuntimeError(
            "pdftoppm was not found. Install Poppler: "
            "'brew install poppler' on macOS or "
            "'sudo apt-get install poppler-utils' on Ubuntu/Debian."
        )
    return executable


def render_pdf(pdf_path: Path, render_dir: Path, dpi: int) -> dict[int, Path]:
    executable = locate_pdftoppm()
    prefix = render_dir / "page"
    completed = subprocess.run(
        [executable, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "pdftoppm failed:\n" + (completed.stderr or completed.stdout).strip()
        )
    rendered: dict[int, Path] = {}
    for path in render_dir.glob("page-*.png"):
        match = re.search(r"-(\d+)\.png$", path.name)
        if match:
            rendered[int(match.group(1))] = path
    if not rendered:
        raise RuntimeError("pdftoppm did not produce any page images")
    return rendered


def crop_image(
    page_image: Image.Image,
    bbox_points: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
) -> Image.Image:
    scale_x = page_image.width / page_width
    scale_y = page_image.height / page_height
    x0, y0, x1, y1 = bbox_points
    pixel_bbox = (
        max(0, round(x0 * scale_x)),
        max(0, round(y0 * scale_y)),
        min(page_image.width, round(x1 * scale_x)),
        min(page_image.height, round(y1 * scale_y)),
    )
    return page_image.crop(pixel_bbox)


def save_png(image: Image.Image, path: Path) -> dict[str, Any]:
    image.convert("RGB").save(path, format="PNG", optimize=True)
    return {
        "image": f"images/{path.name}",
        "image_width_px": image.width,
        "image_height_px": image.height,
        "image_sha256": sha256(path),
    }


def build_bundle(
    pdf_path: Path,
    output_root: Path,
    dpi: int,
    header: str,
    header_lines: list[str],
    tasks: list[dict[str, Any]],
    answers: dict[int, dict[str, Any]],
    answer_page_start: int,
    validation_warnings: list[str],
    page_count: int,
    first_page_size: tuple[float, float],
) -> Path:
    slug = transliterate_slug(pdf_path.stem)
    final_dir = (output_root / slug).resolve()
    if final_dir.exists():
        raise RuntimeError(
            f"Output directory already exists: {final_dir}. "
            "Move or remove it before running the extractor again."
        )

    output_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{slug}-building-", dir=output_root.resolve())
    )
    try:
        images_dir = staging_dir / "images"
        images_dir.mkdir()
        bundle_pdf = staging_dir / "source.pdf"
        shutil.copy2(pdf_path, bundle_pdf)

        with tempfile.TemporaryDirectory(prefix="pdf-task-render-") as temp_name:
            render_dir = Path(temp_name)
            rendered_pages = render_pdf(pdf_path, render_dir, dpi)
            page_cache: dict[int, Image.Image] = {}

            def get_page(page_number: int) -> Image.Image:
                if page_number not in rendered_pages:
                    raise RuntimeError(f"Rendered page {page_number} is missing")
                if page_number not in page_cache:
                    page_cache[page_number] = Image.open(
                        rendered_pages[page_number]
                    ).convert("RGB")
                return page_cache[page_number]

            output_tasks: list[dict[str, Any]] = []
            for task in tasks:
                number = task["number"]
                page_image = get_page(task["page_number"])
                task_crop = crop_image(
                    page_image,
                    task["bbox"],
                    task["page_width"],
                    task["page_height"],
                )
                task_image_path = images_dir / f"task-{number:04d}.png"
                task_image_meta = save_png(task_crop, task_image_path)

                answer = answers[number]
                answer_page_image = get_page(answer["page_number"])
                answer_crop = crop_image(
                    answer_page_image,
                    answer["bbox"],
                    answer["page_width"],
                    answer["page_height"],
                )
                answer_image_path = images_dir / f"answer-{number:04d}.png"
                answer_image_meta = save_png(answer_crop, answer_image_path)

                output_tasks.append(
                    {
                        "id": task["id"],
                        "number": number,
                        **task_image_meta,
                        "source": source_metadata(
                            task["page_number"],
                            task["bbox"],
                            task["page_width"],
                            task["page_height"],
                        ),
                        "answer": {
                            "text": answer["text"],
                            **answer_image_meta,
                            "source": source_metadata(
                                answer["page_number"],
                                answer["bbox"],
                                answer["page_width"],
                                answer["page_height"],
                            ),
                        },
                    }
                )

            for image in page_cache.values():
                image.close()

        meta = {
            "schema_version": 1,
            "header": header,
            "header_lines": header_lines,
            "validation_warnings": validation_warnings,
            "document": {
                "pdf": "source.pdf",
                "pdf_sha256": sha256(bundle_pdf),
                "original_filename": pdf_path.name,
                "page_count": page_count,
                "task_page_range": [
                    min(task["page_number"] for task in tasks),
                    max(task["page_number"] for task in tasks),
                ],
                "answer_page_range": [
                    min(answer["page_number"] for answer in answers.values()),
                    max(answer["page_number"] for answer in answers.values()),
                ],
                "page_size_points": [
                    round(first_page_size[0], 3),
                    round(first_page_size[1], 3),
                ],
                "render_dpi": dpi,
            },
            "coordinate_systems": {
                "bbox_top_left_points": (
                    "[x0, y0, x1, y1], PDF points, origin at top-left"
                ),
                "bbox_pdf_points": (
                    "[x0, y0, x1, y1], PDF points, origin at bottom-left"
                ),
                "bbox_normalized_top_left": (
                    "[x0, y0, x1, y1], values 0..1, origin at top-left"
                ),
            },
            "task_count": len(output_tasks),
            "tasks": output_tasks,
        }
        (staging_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        os.replace(staging_dir, final_dir)
        return final_dir
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise


def main() -> int:
    args = parse_args()
    pdf_path = args.pdf.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    if not pdf_path.is_file():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return 2
    if pdf_path.suffix.lower() != ".pdf":
        print(f"ERROR: Input file must have a .pdf extension: {pdf_path}", file=sys.stderr)
        return 2
    if args.dpi < 72 or args.dpi > 600:
        print("ERROR: --dpi must be between 72 and 600", file=sys.stderr)
        return 2

    try:
        with pdfplumber.open(pdf_path) as pdf:
            (
                header,
                header_lines,
                tasks,
                answers,
                answer_page_start,
                validation_warnings,
            ) = validate_format(pdf)
            page_count = len(pdf.pages)
            first_page_size = (
                float(pdf.pages[0].width),
                float(pdf.pages[0].height),
            )

        print(
            f"Format OK: {len(tasks)} tasks, {len(answers)} answers, "
            f"header={header!r}",
            file=sys.stderr,
        )
        for warning in validation_warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        final_dir = build_bundle(
            pdf_path=pdf_path,
            output_root=output_root,
            dpi=args.dpi,
            header=header,
            header_lines=header_lines,
            tasks=tasks,
            answers=answers,
            answer_page_start=answer_page_start,
            validation_warnings=validation_warnings,
            page_count=page_count,
            first_page_size=first_page_size,
        )
    except FormatError as exc:
        print(f"UNSUPPORTED FORMAT: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(final_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
