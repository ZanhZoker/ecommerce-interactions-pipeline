"""Core interaction validation and cleaning, independent from AWS."""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

try:  # Package import for local execution.
    from .archive_reader import ArchiveLimits, ArchiveValidationError, read_archive
    from .reporting import report_as_json, report_as_markdown
except ImportError:  # Top-level modules when app/ is the Lambda CodeUri.
    from archive_reader import ArchiveLimits, ArchiveValidationError, read_archive
    from reporting import report_as_json, report_as_markdown


REQUIRED_COLUMNS = ("USER_ID", "ITEM_ID", "EVENT_TYPE", "TIMESTAMP")
REJECTED_COLUMNS = REQUIRED_COLUMNS + ("REJECTION_REASON",)
VALID_EVENT_TYPES = {"view", "add_to_cart", "remove_from_cart", "purchase"}


class PipelineValidationError(ValueError):
    """Raised when an archive cannot be processed safely."""


@dataclass(frozen=True)
class PipelineResult:
    clean_csv: str
    rejected_csv: str
    report_json: str
    report_markdown: str
    report: dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _datetime_utc(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _timestamp(value: str) -> tuple[str, int | None]:
    stripped = value.strip()
    if not stripped:
        return stripped, None
    if not stripped.isascii() or not stripped.isdigit():
        return stripped, None
    parsed = int(stripped)
    if parsed <= 0:
        return stripped, None
    try:
        _datetime_utc(parsed)
    except (OverflowError, OSError, ValueError):
        return stripped, None
    return str(parsed), parsed


def _logical_header(raw_header: list[str]) -> tuple[list[str], dict[str, int]]:
    header = [value.strip().upper() for value in raw_header]
    duplicate_columns = sorted({name for name in header if header.count(name) > 1})
    if duplicate_columns:
        raise PipelineValidationError(
            "interactions.csv has duplicate logical column(s): "
            + ", ".join(duplicate_columns)
        )
    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing:
        raise PipelineValidationError(
            "interactions.csv is missing required column(s): " + ", ".join(missing)
        )
    return header, {name: header.index(name) for name in REQUIRED_COLUMNS}


def _source_label(source: object, source_archive: str | None) -> str:
    if source_archive:
        return source_archive
    if isinstance(source, (str, Path)):
        return Path(source).name
    return "archive.zip"


def process_archive(
    source: str | Path | bytes | bytearray | BinaryIO,
    *,
    source_archive: str | None = None,
    run_id: str | None = None,
    limits: ArchiveLimits | None = None,
) -> PipelineResult:
    """Process one export ZIP entirely in memory and return all four artifacts."""

    started_at = _utc_now()
    try:
        archive = read_archive(source, limits=limits)
    except ArchiveValidationError as exc:
        raise PipelineValidationError(str(exc)) from exc

    stable_run_id = run_id or archive.source_sha256
    clean_buffer = io.StringIO(newline="")
    rejected_buffer = io.StringIO(newline="")
    clean_writer = csv.writer(clean_buffer, lineterminator="\n")
    rejected_writer = csv.writer(rejected_buffer, lineterminator="\n")
    clean_writer.writerow(REQUIRED_COLUMNS)
    rejected_writer.writerow(REJECTED_COLUMNS)

    reader = csv.reader(io.StringIO(archive.interactions_text, newline=""))
    try:
        raw_header = next(reader)
    except StopIteration as exc:
        raise PipelineValidationError("interactions.csv is empty") from exc
    _, column_index = _logical_header(raw_header)

    input_row_count = 0
    rejected_row_count = 0
    duplicate_row_count = 0
    missing_counts = Counter({name: 0 for name in REQUIRED_COLUMNS})
    rejection_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    input_user_ids: set[str] = set()
    input_item_ids: set[str] = set()
    output_user_ids: set[str] = set()
    output_item_ids: set[str] = set()
    unknown_item_ids: set[str] = set()
    seen_rows: set[tuple[str, str, str, str]] = set()
    timestamps: list[int] = []

    try:
        for raw_row in reader:
            input_row_count += 1

            def value(column: str) -> str:
                index = column_index[column]
                return raw_row[index] if index < len(raw_row) else ""

            user_id = value("USER_ID").strip()
            item_id = value("ITEM_ID").strip()
            event_type = value("EVENT_TYPE").strip().lower()
            raw_timestamp = value("TIMESTAMP").strip()
            normalized_timestamp, parsed_timestamp = _timestamp(raw_timestamp)

            normalized_values = (user_id, item_id, event_type, normalized_timestamp)
            for column, normalized in zip(REQUIRED_COLUMNS, normalized_values):
                if not normalized:
                    missing_counts[column] += 1
            if user_id:
                input_user_ids.add(user_id)
            if item_id:
                input_item_ids.add(item_id)

            reasons: list[str] = []
            if not user_id:
                reasons.append("MISSING_USER_ID")
            if not item_id:
                reasons.append("MISSING_ITEM_ID")
            elif item_id not in archive.product_ids:
                reasons.append("UNKNOWN_ITEM_ID")
                unknown_item_ids.add(item_id)
            if event_type not in VALID_EVENT_TYPES:
                reasons.append("INVALID_EVENT_TYPE")
            if not raw_timestamp:
                reasons.append("MISSING_TIMESTAMP")
            elif parsed_timestamp is None:
                reasons.append("INVALID_TIMESTAMP")

            if reasons:
                rejected_row_count += 1
                rejection_counts.update(reasons)
                rejected_writer.writerow((*normalized_values, "|".join(reasons)))
                continue

            if normalized_values in seen_rows:
                duplicate_row_count += 1
                rejected_row_count += 1
                rejection_counts["DUPLICATE_ROW"] += 1
                rejected_writer.writerow((*normalized_values, "DUPLICATE_ROW"))
                continue

            seen_rows.add(normalized_values)
            clean_writer.writerow(normalized_values)
            output_user_ids.add(user_id)
            output_item_ids.add(item_id)
            event_counts[event_type] += 1
            timestamps.append(parsed_timestamp)  # type: ignore[arg-type]
    except csv.Error as exc:
        raise PipelineValidationError(f"Cannot parse interactions.csv: {exc}") from exc

    generated_user_ids = output_user_ids - input_user_ids
    generated_item_ids = output_item_ids - input_item_ids
    users_subset = output_user_ids.issubset(input_user_ids)
    items_subset = output_item_ids.issubset(input_item_ids)
    items_in_products = output_item_ids.issubset(archive.product_ids)
    id_check = {
        "user_ids_preserved": users_subset and not generated_user_ids,
        "item_ids_preserved": items_subset and not generated_item_ids,
        "output_user_ids_subset_of_input": users_subset,
        "output_item_ids_subset_of_input": items_subset,
        "output_item_ids_exist_in_products": items_in_products,
        "no_generated_user_ids": not generated_user_ids,
        "no_generated_item_ids": not generated_item_ids,
    }
    id_check["status"] = "PASS" if all(id_check.values()) else "FAIL"

    minimum_timestamp = min(timestamps) if timestamps else None
    maximum_timestamp = max(timestamps) if timestamps else None
    report = {
        "source_archive": _source_label(source, source_archive),
        "source_archive_size_bytes": archive.source_size_bytes,
        "processing_started_at_utc": started_at,
        "processing_finished_at_utc": _utc_now(),
        "pipeline_status": "SUCCESS",
        "input_row_count": input_row_count,
        "clean_row_count": len(seen_rows),
        "rejected_row_count": rejected_row_count,
        "duplicate_row_count": duplicate_row_count,
        "unique_user_count": len(output_user_ids),
        "unique_item_count": len(output_item_ids),
        "product_lookup_count": len(archive.product_ids),
        "missing_value_count_by_column": dict(missing_counts),
        "event_type_distribution": {
            event: event_counts.get(event, 0) for event in sorted(VALID_EVENT_TYPES)
        },
        "rejection_reason_distribution": dict(sorted(rejection_counts.items())),
        "unknown_item_ids": sorted(unknown_item_ids),
        "minimum_timestamp": minimum_timestamp,
        "maximum_timestamp": maximum_timestamp,
        "minimum_datetime_utc": _datetime_utc(minimum_timestamp),
        "maximum_datetime_utc": _datetime_utc(maximum_timestamp),
        "input_user_id_count": len(input_user_ids),
        "output_user_id_count": len(output_user_ids),
        "input_item_id_count": len(input_item_ids),
        "output_item_id_count": len(output_item_ids),
        "generated_user_id_count": len(generated_user_ids),
        "generated_item_id_count": len(generated_item_ids),
        "id_preservation_check": id_check,
        "ignored_files": list(archive.ignored_files),
        "output_files": [
            "processed/interactions_clean.csv",
            "rejected/interactions_rejected.csv",
            "reports/data_quality_report.json",
            "reports/data_quality_report.md",
        ],
        "run_id": stable_run_id,
    }

    return PipelineResult(
        clean_csv=clean_buffer.getvalue(),
        rejected_csv=rejected_buffer.getvalue(),
        report_json=report_as_json(report),
        report_markdown=report_as_markdown(report),
        report=report,
    )


def write_local_outputs(result: PipelineResult, output_directory: str | Path) -> dict[str, Path]:
    """Write the four pipeline artifacts below the requested local output folder."""

    output_root = Path(output_directory)
    paths = {
        "clean": output_root / "processed" / "interactions_clean.csv",
        "rejected": output_root / "rejected" / "interactions_rejected.csv",
        "json_report": output_root / "reports" / "data_quality_report.json",
        "markdown_report": output_root / "reports" / "data_quality_report.md",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    paths["clean"].write_text(result.clean_csv, encoding="utf-8", newline="")
    paths["rejected"].write_text(result.rejected_csv, encoding="utf-8", newline="")
    paths["json_report"].write_text(result.report_json, encoding="utf-8", newline="")
    paths["markdown_report"].write_text(
        result.report_markdown, encoding="utf-8", newline=""
    )
    return paths

