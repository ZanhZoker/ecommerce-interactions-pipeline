"""Safe, in-memory access to the required files inside an export ZIP."""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO


class ArchiveValidationError(ValueError):
    """Raised when an input archive violates the pipeline data contract."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_zip_size_bytes: int = 50 * 1024 * 1024
    max_uncompressed_size_bytes: int = 150 * 1024 * 1024
    max_member_count: int = 100

    @classmethod
    def from_environment(cls) -> "ArchiveLimits":
        return cls(
            max_zip_size_bytes=_positive_megabytes("MAX_ZIP_SIZE_MB", 50),
            max_uncompressed_size_bytes=_positive_megabytes(
                "MAX_UNCOMPRESSED_SIZE_MB", 150
            ),
            max_member_count=_positive_integer("MAX_MEMBER_COUNT", 100),
        )


@dataclass(frozen=True)
class ArchiveData:
    interactions_text: str
    product_ids: frozenset[str]
    ignored_files: tuple[str, ...]
    member_names: tuple[str, ...]
    source_size_bytes: int
    source_sha256: str


def _positive_integer(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ArchiveValidationError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ArchiveValidationError(f"{name} must be a positive integer")
    return value


def _positive_megabytes(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ArchiveValidationError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ArchiveValidationError(f"{name} must be a positive number")
    return int(value * 1024 * 1024)


def _read_source(source: str | Path | bytes | bytearray | BinaryIO) -> bytes:
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            raise ArchiveValidationError(f"Input ZIP does not exist: {path}")
        return path.read_bytes()
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if hasattr(source, "read"):
        value = source.read()
        if not isinstance(value, bytes):
            raise ArchiveValidationError("Archive stream must return bytes")
        return value
    raise ArchiveValidationError("Unsupported archive source")


def _is_dangerous_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    first_part = path.parts[0] if path.parts else ""
    return (
        normalized.startswith("/")
        or path.is_absolute()
        or ".." in path.parts
        or bool(re.match(r"^[A-Za-z]:", first_part))
    )


def _one_member_by_basename(
    members: list[zipfile.ZipInfo], basename: str
) -> zipfile.ZipInfo:
    matches = [
        member
        for member in members
        if not member.is_dir()
        and PurePosixPath(member.filename.replace("\\", "/")).name.casefold()
        == basename.casefold()
    ]
    if not matches:
        raise ArchiveValidationError(f"Archive is missing required file: {basename}")
    if len(matches) > 1:
        names = ", ".join(member.filename for member in matches)
        raise ArchiveValidationError(
            f"Archive contains multiple files named {basename}: {names}"
        )
    return matches[0]


def _read_utf8(zf: zipfile.ZipFile, member: zipfile.ZipInfo) -> str:
    try:
        with zf.open(member, "r") as raw:
            return raw.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ArchiveValidationError(
            f"{member.filename} must use UTF-8 or UTF-8 with BOM"
        ) from exc
    except RuntimeError as exc:
        raise ArchiveValidationError(
            f"Cannot read encrypted or invalid ZIP member: {member.filename}"
        ) from exc


def _product_ids(products_text: str) -> frozenset[str]:
    try:
        payload = json.loads(products_text)
    except json.JSONDecodeError as exc:
        raise ArchiveValidationError(f"Products.json is not valid JSON: {exc}") from exc

    if isinstance(payload, list):
        products = payload
    elif isinstance(payload, dict) and isinstance(payload.get("products"), list):
        products = payload["products"]
    else:
        raise ArchiveValidationError(
            "Products.json must be a list or an object containing a products list"
        )

    identifiers: list[str] = []
    for index, product in enumerate(products, start=1):
        if not isinstance(product, dict) or "id" not in product:
            raise ArchiveValidationError(
                f"Products.json entry {index} does not contain an id"
            )
        product_id = str(product["id"]).strip()
        if not product_id:
            raise ArchiveValidationError(
                f"Products.json entry {index} contains an empty id"
            )
        identifiers.append(product_id)

    duplicates = sorted(
        identifier for identifier in set(identifiers) if identifiers.count(identifier) > 1
    )
    if duplicates:
        raise ArchiveValidationError(
            "Products.json contains duplicate product id(s): " + ", ".join(duplicates)
        )
    return frozenset(identifiers)


def read_archive(
    source: str | Path | bytes | bytearray | BinaryIO,
    limits: ArchiveLimits | None = None,
) -> ArchiveData:
    """Validate a ZIP and read only interactions.csv and Products.json."""

    limits = limits or ArchiveLimits.from_environment()
    archive_bytes = _read_source(source)
    if len(archive_bytes) > limits.max_zip_size_bytes:
        raise ArchiveValidationError(
            "ZIP size exceeds MAX_ZIP_SIZE_MB "
            f"({len(archive_bytes)} > {limits.max_zip_size_bytes} bytes)"
        )

    stream = io.BytesIO(archive_bytes)
    if not zipfile.is_zipfile(stream):
        raise ArchiveValidationError("Input is not a valid ZIP archive")
    stream.seek(0)

    try:
        with zipfile.ZipFile(stream, "r") as zf:
            members = zf.infolist()
            if len(members) > limits.max_member_count:
                raise ArchiveValidationError(
                    "ZIP member count exceeds MAX_MEMBER_COUNT "
                    f"({len(members)} > {limits.max_member_count})"
                )

            dangerous = [m.filename for m in members if _is_dangerous_member(m.filename)]
            if dangerous:
                raise ArchiveValidationError(
                    "ZIP contains unsafe path(s): " + ", ".join(dangerous)
                )

            total_size = sum(member.file_size for member in members)
            if total_size > limits.max_uncompressed_size_bytes:
                raise ArchiveValidationError(
                    "Uncompressed ZIP size exceeds MAX_UNCOMPRESSED_SIZE_MB "
                    f"({total_size} > {limits.max_uncompressed_size_bytes} bytes)"
                )

            interactions_member = _one_member_by_basename(members, "interactions.csv")
            products_member = _one_member_by_basename(members, "Products.json")
            ignored_files = tuple(
                sorted(
                    {
                        PurePosixPath(m.filename.replace("\\", "/")).name
                        for m in members
                        if not m.is_dir()
                        and PurePosixPath(m.filename.replace("\\", "/"))
                        .name.casefold()
                        == "items.csv"
                    }
                )
            )

            interactions_text = _read_utf8(zf, interactions_member)
            products_text = _read_utf8(zf, products_member)
    except zipfile.BadZipFile as exc:
        raise ArchiveValidationError("Input is not a valid ZIP archive") from exc

    return ArchiveData(
        interactions_text=interactions_text,
        product_ids=_product_ids(products_text),
        ignored_files=ignored_files,
        member_names=tuple(member.filename for member in members),
        source_size_bytes=len(archive_bytes),
        source_sha256=sha256(archive_bytes).hexdigest(),
    )

