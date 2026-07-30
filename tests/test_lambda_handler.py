import io

from app import lambda_handler as handler
from tests.test_pipeline import make_zip


def s3_record(key="incoming/export.zip"):
    return {
        "eventSource": "aws:s3",
        "s3": {
            "bucket": {"name": "workshop-bucket"},
            "object": {"key": key, "eTag": "abc", "size": 100},
        },
    }


class FakeS3:
    def __init__(self, archive):
        self.archive = archive
        self.puts = []
        self.heads = []
        self.gets = []

    def head_object(self, **kwargs):
        self.heads.append(kwargs)
        return {"ContentLength": len(self.archive), "ETag": '"abc"'}

    def get_object(self, **kwargs):
        self.gets.append(kwargs)
        return {"Body": io.BytesIO(self.archive)}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {}


def test_lambda_ignores_objects_outside_incoming(monkeypatch):
    fake = FakeS3(make_zip())
    monkeypatch.setattr(handler, "_s3_client", fake)
    response = handler.lambda_handler(
        {"Records": [s3_record("processed/export.zip")]}, None
    )
    assert response["processedRecords"][0]["status"] == "SKIPPED"
    assert fake.heads == []


def test_lambda_ignores_non_zip_objects(monkeypatch):
    fake = FakeS3(make_zip())
    monkeypatch.setattr(handler, "_s3_client", fake)
    response = handler.lambda_handler(
        {"Records": [s3_record("incoming/export.csv")]}, None
    )
    assert response["processedRecords"][0]["reason"] == "SUFFIX"
    assert fake.heads == []


def test_lambda_supports_multiple_records_and_url_decoding(monkeypatch):
    fake = FakeS3(make_zip())
    monkeypatch.setattr(handler, "_s3_client", fake)
    response = handler.lambda_handler(
        {
            "Records": [
                s3_record("incoming%2Fmy+export.zip"),
                s3_record("outside%2Fignored.zip"),
            ]
        },
        None,
    )
    assert len(response["processedRecords"]) == 2
    assert response["processedRecords"][0]["status"] == "SUCCESS"
    assert response["processedRecords"][0]["key"] == "incoming/my export.zip"
    assert response["processedRecords"][1]["status"] == "SKIPPED"


def test_lambda_uploads_run_and_latest_artifacts(monkeypatch):
    fake = FakeS3(make_zip())
    monkeypatch.setattr(handler, "_s3_client", fake)
    response = handler.lambda_handler({"Records": [s3_record()]}, None)
    run_id = response["processedRecords"][0]["run_id"]
    keys = {item["Key"] for item in fake.puts}
    assert len(keys) == 8
    assert f"processed/run_id={run_id}/interactions_clean.csv" in keys
    assert "processed/latest/interactions_clean.csv" in keys
    assert "rejected/latest/interactions_rejected.csv" in keys
    assert "reports/latest/data_quality_report.json" in keys


def test_aws_run_id_is_stable():
    first = handler.create_run_id("bucket", "incoming/a.zip", "", "etag", 10)
    second = handler.create_run_id("bucket", "incoming/a.zip", "", "etag", 10)
    changed = handler.create_run_id("bucket", "incoming/a.zip", "", "etag", 11)
    assert first == second
    assert first != changed


def test_non_s3_event_record_is_skipped():
    response = handler.lambda_handler({"Records": [{"eventSource": "other"}]}, None)
    assert response["processedRecords"] == [
        {"status": "SKIPPED", "reason": "EVENT_SOURCE"}
    ]

