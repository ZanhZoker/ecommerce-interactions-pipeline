import io
import json
import zipfile

import pytest

from app.archive_reader import ArchiveLimits, ArchiveValidationError, read_archive


def archive_bytes(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members:
            zf.writestr(name, content)
    return stream.getvalue()


def valid_members():
    return [
        (
            "export/export/interactions.csv",
            "USER_ID,ITEM_ID,EVENT_TYPE,TIMESTAMP\nuser-001,prod-008,view,1\n",
        ),
        ("export/export/Products.json", json.dumps([{"id": "prod-008"}])),
        ("export/export/items.csv", "this,file,is,intentionally,ignored\n"),
    ]


def test_nested_required_files_are_found_by_basename():
    result = read_archive(archive_bytes(valid_members()))
    assert result.product_ids == {"prod-008"}
    assert "user-001" in result.interactions_text


def test_utf8_bom_is_removed_from_interactions():
    members = valid_members()
    members[0] = (
        "export/export/interactions.csv",
        "\ufeffUSER_ID,ITEM_ID,EVENT_TYPE,TIMESTAMP\nuser-001,prod-008,view,1\n",
    )
    result = read_archive(archive_bytes(members))
    assert result.interactions_text.startswith("USER_ID")


def test_items_csv_is_recognized_but_not_read():
    members = valid_members()
    members[-1] = ("export/export/items.csv", b"\xff\xfe invalid but ignored")
    result = read_archive(archive_bytes(members))
    assert result.ignored_files == ("items.csv",)


def test_missing_interactions_csv_fails():
    with pytest.raises(ArchiveValidationError, match="interactions.csv"):
        read_archive(archive_bytes(valid_members()[1:]))


def test_missing_products_json_fails():
    with pytest.raises(ArchiveValidationError, match="Products.json"):
        read_archive(archive_bytes(valid_members()[:1]))


def test_duplicate_interactions_basename_fails():
    members = valid_members() + [("other/interactions.csv", "a,b,c,d\n")]
    with pytest.raises(ArchiveValidationError, match="multiple files"):
        read_archive(archive_bytes(members))


def test_posix_path_traversal_is_blocked():
    members = valid_members() + [("../escape.txt", "unsafe")]
    with pytest.raises(ArchiveValidationError, match="unsafe path"):
        read_archive(archive_bytes(members))


def test_windows_path_traversal_is_blocked():
    members = valid_members() + [("..\\escape.txt", "unsafe")]
    with pytest.raises(ArchiveValidationError, match="unsafe path"):
        read_archive(archive_bytes(members))


def test_absolute_windows_path_is_blocked():
    members = valid_members() + [("C:\\escape.txt", "unsafe")]
    with pytest.raises(ArchiveValidationError, match="unsafe path"):
        read_archive(archive_bytes(members))


def test_zip_size_limit_is_enforced():
    limits = ArchiveLimits(
        max_zip_size_bytes=10,
        max_uncompressed_size_bytes=10_000,
        max_member_count=100,
    )
    with pytest.raises(ArchiveValidationError, match="ZIP size"):
        read_archive(archive_bytes(valid_members()), limits=limits)


def test_uncompressed_size_limit_is_enforced():
    limits = ArchiveLimits(
        max_zip_size_bytes=10_000,
        max_uncompressed_size_bytes=10,
        max_member_count=100,
    )
    with pytest.raises(ArchiveValidationError, match="Uncompressed ZIP size"):
        read_archive(archive_bytes(valid_members()), limits=limits)


def test_member_count_limit_is_enforced():
    limits = ArchiveLimits(
        max_zip_size_bytes=10_000,
        max_uncompressed_size_bytes=10_000,
        max_member_count=2,
    )
    with pytest.raises(ArchiveValidationError, match="member count"):
        read_archive(archive_bytes(valid_members()), limits=limits)


def test_invalid_zip_fails_clearly():
    with pytest.raises(ArchiveValidationError, match="valid ZIP"):
        read_archive(b"not a zip")


def test_duplicate_product_ids_fail_the_job():
    members = valid_members()
    members[1] = (
        "export/export/Products.json",
        json.dumps([{"id": "prod-008"}, {"id": "prod-008"}]),
    )
    with pytest.raises(ArchiveValidationError, match="duplicate product"):
        read_archive(archive_bytes(members))
