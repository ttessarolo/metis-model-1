from __future__ import annotations

import argparse
import json
from pathlib import Path

from metis_model1.contracts import ValidationReport, repository_root, validate_foundation
from metis_model1.pipeline import (
    DEFAULT_METIS_ROOT,
    assess_experiment_plan,
    render_experiment_plan_text,
    render_pilot_text,
    validate_pilot,
)


def _render_text(report: ValidationReport) -> None:
    for item in report.passes:
        print(f"PASS {item}")
    for wave, decision_ids in report.open_by_wave.items():
        print(f"OPEN wave={wave} decisions={','.join(decision_ids)}")
    if report.open_nonblocking:
        print(f"OPEN nonblocking decisions={','.join(report.open_nonblocking)}")
    for item in report.errors:
        print(f"ERROR {item}")
    status = "VALID" if report.ok else "INVALID"
    print(
        f"FOUNDATION {status} passes={len(report.passes)} errors={len(report.errors)} "
        f"files={report.repository_files}"
    )


def _render_json(report: ValidationReport) -> None:
    print(
        json.dumps(
            {
                "status": "valid" if report.ok else "invalid",
                "passes": report.passes,
                "errors": report.errors,
                "open_by_wave": report.open_by_wave,
                "open_nonblocking": report.open_nonblocking,
                "repository_files": report.repository_files,
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metis-model1")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate-foundation", description="Validate W0 contracts and artifact boundaries."
    )
    validate.add_argument("--root", type=Path, default=repository_root())
    validate.add_argument("--json", action="store_true", dest="as_json")
    experiment = subparsers.add_parser(
        "assess-experiment",
        description="Assess the tracked W5-XS plan without authorizing execution.",
    )
    experiment.add_argument("--root", type=Path, default=repository_root())
    experiment.add_argument("--json", action="store_true", dest="as_json")
    for command, description in (
        ("validate-pilot", "Validate the integrated offline pilot contracts."),
        ("assess-w5", "Assess strict Accuracy-99 promotion readiness."),
    ):
        pilot = subparsers.add_parser(command, description=description)
        pilot.add_argument("--root", type=Path, default=repository_root())
        pilot.add_argument("--metis-root", type=Path, default=DEFAULT_METIS_ROOT)
        pilot.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "assess-experiment":
        report = assess_experiment_plan(args.root)
        if args.as_json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(render_experiment_plan_text(report))
        return 0 if report["ready"] else 1

    if args.command in {"validate-pilot", "assess-w5"}:
        report = validate_pilot(args.root, args.metis_root)
        if args.as_json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(render_pilot_text(report))
        if args.command == "validate-pilot":
            return 0 if report["contract_valid"] else 1
        return 0 if report["w5_readiness"]["ready"] else 1

    if args.command != "validate-foundation":
        raise AssertionError(f"unhandled command: {args.command}")

    report = validate_foundation(args.root)
    if args.as_json:
        _render_json(report)
    else:
        _render_text(report)
    return 0 if report.ok else 1
