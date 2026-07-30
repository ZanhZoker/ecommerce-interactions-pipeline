"""Create the machine-readable and workshop-friendly quality reports."""

from __future__ import annotations

import json
from typing import Any


def report_as_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _table(mapping: dict[str, Any]) -> list[str]:
    if not mapping:
        return ["_None._"]
    lines = ["| Value | Count |", "|---|---:|"]
    lines.extend(f"| `{key}` | {value} |" for key, value in mapping.items())
    return lines


def report_as_markdown(report: dict[str, Any]) -> str:
    id_check = report["id_preservation_check"]
    lines = [
        "# Data Quality Report",
        "",
        "## Run metadata",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Source archive: `{report['source_archive']}`",
        f"- Source size: {report['source_archive_size_bytes']} bytes",
        f"- Started (UTC): {report['processing_started_at_utc']}",
        f"- Finished (UTC): {report['processing_finished_at_utc']}",
        f"- Pipeline status: **{report['pipeline_status']}**",
        "",
        "## Row summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Input rows | {report['input_row_count']} |",
        f"| Clean rows | {report['clean_row_count']} |",
        f"| Rejected rows | {report['rejected_row_count']} |",
        f"| Duplicate rows removed | {report['duplicate_row_count']} |",
        f"| Unique clean users | {report['unique_user_count']} |",
        f"| Unique clean items | {report['unique_item_count']} |",
        f"| Product lookup IDs | {report['product_lookup_count']} |",
        "",
        "## ID preservation",
        "",
        f"Overall result: **{id_check['status']}**",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for key, value in id_check.items():
        if key != "status":
            lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            f"| `input_user_id_count` | {report['input_user_id_count']} |",
            f"| `output_user_id_count` | {report['output_user_id_count']} |",
            f"| `input_item_id_count` | {report['input_item_id_count']} |",
            f"| `output_item_id_count` | {report['output_item_id_count']} |",
            f"| `generated_user_id_count` | {report['generated_user_id_count']} |",
            f"| `generated_item_id_count` | {report['generated_item_id_count']} |",
            "",
            "## Timestamp range",
            "",
            f"- Minimum: `{report['minimum_timestamp']}` ({report['minimum_datetime_utc']})",
            f"- Maximum: `{report['maximum_timestamp']}` ({report['maximum_datetime_utc']})",
            "",
            "## Missing values by column",
            "",
            *_table(report["missing_value_count_by_column"]),
            "",
            "## Clean event distribution",
            "",
            *_table(report["event_type_distribution"]),
            "",
            "## Rejection reason distribution",
            "",
            *_table(report["rejection_reason_distribution"]),
            "",
            "## Other audit details",
            "",
            "- Unknown item IDs: "
            + (", ".join(f"`{x}`" for x in report["unknown_item_ids"]) or "None"),
            "- Ignored files: "
            + (", ".join(f"`{x}`" for x in report["ignored_files"]) or "None"),
            "- Output files:",
        ]
    )
    lines.extend(f"  - `{path}`" for path in report["output_files"])
    lines.extend(
        [
            "",
            "`items.csv` is intentionally ignored by the team data contract. Product "
            "validation uses only the `id` field from `Products.json`.",
            "",
        ]
    )
    return "\n".join(lines)

