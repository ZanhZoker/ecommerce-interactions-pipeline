"""AWS Lambda adapter for the storage-independent core pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any
from urllib.parse import unquote_plus

try:  # Package import in tests/local development.
    from .archive_reader import ArchiveLimits
    from .pipeline import process_archive
except ImportError:  # Top-level modules when app/ is the Lambda CodeUri.
    from archive_reader import ArchiveLimits
    from pipeline import process_archive


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
_s3_client = None


def _client():
    global _s3_client
    if _s3_client is None:
        import boto3

        _s3_client = boto3.client("s3")
    return _s3_client


def create_run_id(
    bucket: str, key: str, version_id: str, etag: str, object_size: int
) -> str:
    stable_identity = json.dumps(
        [bucket, key, version_id, etag, object_size],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(stable_identity.encode("utf-8")).hexdigest()


def _put_outputs(s3, bucket: str, run_id: str, result) -> None:
    prefixes = {
        "processed": os.getenv("PROCESSED_PREFIX", "processed/").rstrip("/"),
        "rejected": os.getenv("REJECTED_PREFIX", "rejected/").rstrip("/"),
        "reports": os.getenv("REPORTS_PREFIX", "reports/").rstrip("/"),
    }
    artifacts = [
        (
            prefixes["processed"],
            "interactions_clean.csv",
            result.clean_csv,
            "text/csv; charset=utf-8",
        ),
        (
            prefixes["rejected"],
            "interactions_rejected.csv",
            result.rejected_csv,
            "text/csv; charset=utf-8",
        ),
        (
            prefixes["reports"],
            "data_quality_report.json",
            result.report_json,
            "application/json; charset=utf-8",
        ),
        (
            prefixes["reports"],
            "data_quality_report.md",
            result.report_markdown,
            "text/markdown; charset=utf-8",
        ),
    ]
    for prefix, filename, body, content_type in artifacts:
        encoded = body.encode("utf-8")
        for destination in (
            f"{prefix}/run_id={run_id}/{filename}",
            f"{prefix}/latest/{filename}",
        ):
            s3.put_object(
                Bucket=bucket,
                Key=destination,
                Body=encoded,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )


def _process_record(record: dict[str, Any]) -> dict[str, Any]:
    bucket = record["s3"]["bucket"]["name"]
    object_data = record["s3"]["object"]
    key = unquote_plus(object_data["key"])
    input_prefix = os.getenv("INPUT_PREFIX", "incoming/")
    if not key.startswith(input_prefix):
        return {"status": "SKIPPED", "bucket": bucket, "key": key, "reason": "PREFIX"}
    if not key.lower().endswith(".zip"):
        return {"status": "SKIPPED", "bucket": bucket, "key": key, "reason": "SUFFIX"}

    s3 = _client()
    version_id = str(object_data.get("versionId") or "")
    head_args: dict[str, Any] = {"Bucket": bucket, "Key": key}
    if version_id:
        head_args["VersionId"] = version_id
    head = s3.head_object(**head_args)
    object_size = int(head["ContentLength"])
    limits = ArchiveLimits.from_environment()
    if object_size > limits.max_zip_size_bytes:
        raise ValueError(
            f"S3 object exceeds MAX_ZIP_SIZE_MB ({object_size} > "
            f"{limits.max_zip_size_bytes} bytes)"
        )

    get_args = dict(head_args)
    response = s3.get_object(**get_args)
    archive_bytes = response["Body"].read()
    etag = str(head.get("ETag") or object_data.get("eTag") or "").strip('"')
    run_id = create_run_id(bucket, key, version_id, etag, object_size)
    result = process_archive(
        archive_bytes,
        source_archive=f"s3://{bucket}/{key}",
        run_id=run_id,
        limits=limits,
    )
    _put_outputs(s3, bucket, run_id, result)
    report = result.report
    return {
        "status": "SUCCESS",
        "bucket": bucket,
        "key": key,
        "run_id": run_id,
        "input_row_count": report["input_row_count"],
        "clean_row_count": report["clean_row_count"],
        "rejected_row_count": report["rejected_row_count"],
        "duplicate_row_count": report["duplicate_row_count"],
        "unique_user_count": report["unique_user_count"],
        "unique_item_count": report["unique_item_count"],
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    try:
        for record in event.get("Records", []):
            if record.get("eventSource") != "aws:s3":
                results.append({"status": "SKIPPED", "reason": "EVENT_SOURCE"})
                continue
            result = _process_record(record)
            results.append(result)
            LOGGER.info(
                json.dumps(
                    {
                        **result,
                        "pipeline_status": result["status"],
                        "processing_duration_seconds": round(
                            time.perf_counter() - started, 3
                        ),
                    },
                    separators=(",", ":"),
                )
            )
    except Exception:
        LOGGER.exception(
            "Pipeline failed after %.3f seconds", time.perf_counter() - started
        )
        raise
    return {"statusCode": 200, "processedRecords": results}

