"""Command-line interface.

Three verbs, matching the three things anyone actually wants to do:

    deckmaster build deck.json -o deck.pptx    build a deck
    deckmaster audit deck.json                 report findings without writing
    deckmaster check deck.pptx                 validate an existing package

`build` runs the audit first and refuses to write a deck carrying a blocking
finding. That ordering is the point: a broken slide should never reach a file,
because once it does, someone presents it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audit import AuditReport, audit_deck
from .layout import LayoutError, layout_deck
from .loader import DeckSpecError, deck_from_json
from .model import ContentTooLong
from .serialize.pptx import write_pptx
from .text.metrics import UnsupportedCharacter
from .theme import DEFAULT_THEME
from .validate.opc import validate_package


def _print_findings(report: AuditReport, stream) -> None:
    for finding in report.findings:
        location = f" [{finding.shape}]" if finding.shape else ""
        print(f"  {finding.severity:9} slide {finding.slide}{location}: {finding.message}", file=stream)


def _load(path: Path):
    try:
        return deck_from_json(path)
    except (DeckSpecError, ContentTooLong, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def cmd_build(args: argparse.Namespace) -> int:
    deck = _load(args.spec)
    try:
        rendered = layout_deck(deck, DEFAULT_THEME)
    except (LayoutError, UnsupportedCharacter) as exc:
        print(f"layout error: {exc}", file=sys.stderr)
        return 2

    report = audit_deck(rendered, DEFAULT_THEME)
    _print_findings(report, sys.stderr)
    if report.blocking and not args.force:
        print(
            f"refusing to write: {len(report.blocking)} blocking finding(s). "
            "Fix the content, or pass --force to write anyway.",
            file=sys.stderr,
        )
        return 1

    try:
        write_pptx(rendered, args.output)
    except OSError as exc:
        print(f"error: cannot write {args.output}: {exc}", file=sys.stderr)
        return 2

    result = validate_package(args.output)
    if not result.ok:
        # A package that fails here is a defect in this tool, not in the input,
        # so it is reported loudly rather than left for PowerPoint to discover.
        print(f"error: generated package is invalid ({len(result.errors)} problems):", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        return 3

    print(f"wrote {args.output} ({len(rendered.slides)} slides)")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    deck = _load(args.spec)
    try:
        rendered = layout_deck(deck, DEFAULT_THEME)
    except (LayoutError, UnsupportedCharacter) as exc:
        print(f"layout error: {exc}", file=sys.stderr)
        return 2

    report = audit_deck(rendered, DEFAULT_THEME)
    _print_findings(report, sys.stdout)
    print(
        f"{len(report.blocking)} blocking, {len(report.advisory)} advisory "
        f"across {len(rendered.slides)} slides"
    )
    return 1 if report.blocking else 0


def cmd_check(args: argparse.Namespace) -> int:
    result = validate_package(args.package)
    if result.ok:
        print(f"{args.package}: valid")
        return 0
    print(f"{args.package}: {len(result.errors)} problem(s)", file=sys.stderr)
    for error in result.errors:
        print(f"  - {error}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deckmaster", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build a .pptx from a deck spec")
    build.add_argument("spec", type=Path, help="deck spec as JSON")
    build.add_argument("-o", "--output", type=Path, default=Path("deck.pptx"))
    build.add_argument("--force", action="store_true", help="write even with blocking findings")
    build.set_defaults(func=cmd_build)

    audit = sub.add_parser("audit", help="report findings without writing a file")
    audit.add_argument("spec", type=Path, help="deck spec as JSON")
    audit.set_defaults(func=cmd_audit)

    check = sub.add_parser("check", help="validate an existing .pptx package")
    check.add_argument("package", type=Path)
    check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
