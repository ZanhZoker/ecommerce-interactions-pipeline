"""Command-line entry point for local processing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import PipelineValidationError, process_archive, write_local_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean an e-commerce interactions export ZIP."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input ZIP path")
    parser.add_argument(
        "--output", required=True, type=Path, help="Output directory (for example output)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.input.is_file():
        print(f"Pipeline failed: input file does not exist: {args.input}", file=sys.stderr)
        return 2
    try:
        result = process_archive(args.input, source_archive=args.input.name)
        write_local_outputs(result, args.output)
    except (OSError, PipelineValidationError) as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1

    report = result.report
    print("Pipeline completed successfully")
    print(f"Input rows: {report['input_row_count']}")
    print(f"Clean rows: {report['clean_row_count']}")
    print(f"Rejected rows: {report['rejected_row_count']}")
    print(f"Duplicate rows: {report['duplicate_row_count']}")
    print(f"Unique users: {report['unique_user_count']}")
    print(f"Unique items: {report['unique_item_count']}")
    print(f"IDs preserved: {report['id_preservation_check']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

