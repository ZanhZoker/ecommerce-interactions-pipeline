import csv
import io
import json
import zipfile

import pytest

from app.pipeline import PipelineValidationError, process_archive


BASE_ROWS = [
    ["user-001", "prod-008", "view", "1710000001"],
    ["user-133", "prod-070", "purchase", "1710000002"],
]
PRODUCTS = [{"id": "prod-008"}, {"id": "prod-070"}]


def make_zip(rows=None, products=None, header=None, include_items=True):
    rows = BASE_ROWS if rows is None else rows
    products = PRODUCTS if products is None else products
    header = header or ["USER_ID", "ITEM_ID", "EVENT_TYPE", "TIMESTAMP"]
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("nested/interactions.csv", csv_buffer.getvalue())
        zf.writestr("nested/Products.json", json.dumps(products))
        if include_items:
            zf.writestr("nested/items.csv", "ITEM_ID,PRICE\nprod-999,999\n")
    return stream.getvalue()


def csv_rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def clean_ids(result, column):
    return {row[column] for row in csv_rows(result.clean_csv)}


def test_preserves_user_001():
    assert "user-001" in clean_ids(process_archive(make_zip()), "USER_ID")


def test_preserves_user_133():
    assert "user-133" in clean_ids(process_archive(make_zip()), "USER_ID")


def test_preserves_prod_070():
    assert "prod-070" in clean_ids(process_archive(make_zip()), "ITEM_ID")


def test_preserves_prod_008_and_leading_zero():
    assert "prod-008" in clean_ids(process_archive(make_zip()), "ITEM_ID")


def test_does_not_generate_surrogate_or_integer_ids():
    result = process_archive(make_zip())
    values = clean_ids(result, "USER_ID") | clean_ids(result, "ITEM_ID")
    assert "U0001" not in values
    assert "P0042" not in values
    assert all(not value.isdigit() for value in values)
    assert result.report["generated_user_id_count"] == 0
    assert result.report["generated_item_id_count"] == 0


def test_unknown_product_is_rejected():
    result = process_archive(
        make_zip(rows=[["user-001", "prod-999", "view", "1710000001"]])
    )
    assert result.report["clean_row_count"] == 0
    assert csv_rows(result.rejected_csv)[0]["REJECTION_REASON"] == "UNKNOWN_ITEM_ID"


def test_missing_user_id_is_rejected():
    result = process_archive(make_zip(rows=[[" ", "prod-008", "view", "1"]]))
    assert "MISSING_USER_ID" in csv_rows(result.rejected_csv)[0]["REJECTION_REASON"]


def test_missing_item_id_is_rejected():
    result = process_archive(make_zip(rows=[["user-001", "", "view", "1"]]))
    assert "MISSING_ITEM_ID" in csv_rows(result.rejected_csv)[0]["REJECTION_REASON"]


def test_invalid_event_type_is_rejected():
    result = process_archive(make_zip(rows=[["user-001", "prod-008", "click", "1"]]))
    assert "INVALID_EVENT_TYPE" in csv_rows(result.rejected_csv)[0]["REJECTION_REASON"]


@pytest.mark.parametrize("timestamp", ["1.5", "-1", "NaN", "abc"])
def test_invalid_timestamp_is_rejected(timestamp):
    result = process_archive(
        make_zip(rows=[["user-001", "prod-008", "view", timestamp]])
    )
    assert "INVALID_TIMESTAMP" in csv_rows(result.rejected_csv)[0]["REJECTION_REASON"]


def test_zero_timestamp_is_rejected():
    result = process_archive(make_zip(rows=[["user-001", "prod-008", "view", "0"]]))
    assert "INVALID_TIMESTAMP" in csv_rows(result.rejected_csv)[0]["REJECTION_REASON"]


def test_missing_timestamp_is_rejected():
    result = process_archive(make_zip(rows=[["user-001", "prod-008", "view", " "]]))
    assert csv_rows(result.rejected_csv)[0]["REJECTION_REASON"] == "MISSING_TIMESTAMP"


def test_exact_duplicate_is_removed_and_written_to_rejected():
    row = ["user-001", "prod-008", "view", "1710000001"]
    result = process_archive(make_zip(rows=[row, row]))
    assert result.report["clean_row_count"] == 1
    assert result.report["rejected_row_count"] == 1
    assert result.report["duplicate_row_count"] == 1
    assert csv_rows(result.rejected_csv)[0]["REJECTION_REASON"] == "DUPLICATE_ROW"


def test_events_with_different_timestamps_are_not_merged():
    rows = [
        ["user-001", "prod-008", "view", "1"],
        ["user-001", "prod-008", "view", "2"],
    ]
    assert process_archive(make_zip(rows=rows)).report["clean_row_count"] == 2


def test_events_with_different_event_types_are_not_merged():
    rows = [
        ["user-001", "prod-008", "view", "1"],
        ["user-001", "prod-008", "purchase", "1"],
    ]
    assert process_archive(make_zip(rows=rows)).report["clean_row_count"] == 2


def test_output_has_exact_four_columns_in_order():
    result = process_archive(make_zip())
    header = next(csv.reader(io.StringIO(result.clean_csv)))
    assert header == ["USER_ID", "ITEM_ID", "EVENT_TYPE", "TIMESTAMP"]


def test_all_clean_items_exist_in_products():
    result = process_archive(make_zip())
    assert clean_ids(result, "ITEM_ID") <= {"prod-008", "prod-070"}
    assert result.report["id_preservation_check"]["output_item_ids_exist_in_products"]


def test_output_ids_are_subsets_of_input_ids():
    result = process_archive(make_zip())
    assert clean_ids(result, "USER_ID") <= {row[0] for row in BASE_ROWS}
    assert clean_ids(result, "ITEM_ID") <= {row[1] for row in BASE_ROWS}
    assert result.report["id_preservation_check"]["status"] == "PASS"


def test_same_input_has_stable_run_id_and_clean_output():
    archive = make_zip()
    first = process_archive(archive)
    second = process_archive(archive)
    assert first.report["run_id"] == second.report["run_id"]
    assert first.clean_csv == second.clean_csv


def test_header_case_spaces_and_utf8_bom_are_supported():
    archive = make_zip(header=[" user_id ", "item_id", " Event_Type ", "timestamp "])
    result = process_archive(archive)
    assert result.report["clean_row_count"] == 2


def test_event_type_is_trimmed_and_lowercased():
    result = process_archive(
        make_zip(rows=[["user-001", "prod-008", " VIEW ", "1"]])
    )
    assert csv_rows(result.clean_csv)[0]["EVENT_TYPE"] == "view"


def test_ids_are_only_trimmed_at_the_edges():
    products = [{"id": "User-Product-008"}]
    rows = [[" User-AbC-001 ", " User-Product-008 ", "view", "1"]]
    result = process_archive(make_zip(rows=rows, products=products))
    row = csv_rows(result.clean_csv)[0]
    assert row["USER_ID"] == "User-AbC-001"
    assert row["ITEM_ID"] == "User-Product-008"


def test_multiple_rejection_reasons_use_pipe_separator():
    result = process_archive(make_zip(rows=[["", "", "bad", "abc"]]))
    reasons = csv_rows(result.rejected_csv)[0]["REJECTION_REASON"]
    assert reasons == (
        "MISSING_USER_ID|MISSING_ITEM_ID|INVALID_EVENT_TYPE|INVALID_TIMESTAMP"
    )


def test_items_csv_does_not_change_output():
    with_items = process_archive(make_zip(include_items=True))
    without_items = process_archive(make_zip(include_items=False))
    assert with_items.clean_csv == without_items.clean_csv


def test_missing_required_header_fails():
    with pytest.raises(PipelineValidationError, match="missing required column"):
        process_archive(make_zip(header=["USER_ID", "ITEM_ID", "EVENT_TYPE", "OTHER"]))

