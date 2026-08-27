from __future__ import annotations

import argparse
import json
from pathlib import Path

from metis_model1.brain_server import run_brain_server
from metis_model1.contracts import ValidationReport, repository_root, validate_foundation
from metis_model1.pipeline import (
    DEFAULT_METIS_ROOT,
    assess_experiment_plan,
    render_experiment_plan_text,
    render_pilot_text,
    validate_pilot,
)
from metis_model1.video_private_artifacts import (
    prepare_artifact_boundary,
    validate_public_receipt,
)
from metis_model1.video_private_io import VideoPrivateIOError
from metis_model1.video_semantics_private_runner import (
    BLOCKED_ERROR_CODES,
    BLOCKED_PUBLIC_RESULT_KEYS,
    VideoSemanticsPrivateRunnerError,
    acquire_sources,
    blocked_result,
    extract_sources,
    freeze_sources,
    validate_ontology,
)
from metis_model1.video_semantics_tooling import ERROR_CODES as TOOLING_ERROR_CODES
from metis_model1.video_semantics_tooling import (
    PUBLIC_RESULT_KEYS as TOOLING_PUBLIC_RESULT_KEYS,
)
from metis_model1.video_source_acquisition import ERROR_CODES as ACQUISITION_ERROR_CODES
from metis_model1.video_source_acquisition import PUBLIC_KEYS as ACQUISITION_PUBLIC_KEYS
from metis_model1.video_source_acquisition import VideoSourceAcquisitionError
from metis_model1.video_source_acquisition import public_failure as source_acquisition_failure
from metis_model1.video_source_extraction import ERROR_CODES as EXTRACTION_ERROR_CODES
from metis_model1.video_source_extraction import (
    PUBLIC_RESULT_KEYS as EXTRACTION_PUBLIC_RESULT_KEYS,
)
from metis_model1.video_source_extraction import VideoSourceExtractionError
from metis_model1.video_source_extraction import public_failure as source_extraction_failure

_VIDEO_OPERATIONS = frozenset(
    {"acquire-sources", "extract-sources", "freeze-sources", "validate-ontology"}
)


def _valid_error_codes(value: object, allowed: frozenset[str]) -> bool:
    return (
        isinstance(value, list)
        and all(type(item) is str for item in value)
        and value == sorted(set(value))
        and set(value) <= allowed
    )


def _validated_video_result(command: str, value: object) -> dict[str, object]:
    """Accept only finite, exact public contracts before any CLI serialization."""

    if command not in _VIDEO_OPERATIONS or type(value) is not dict:
        raise ValueError("invalid public result")
    result = value
    if result.get("status") == "BLOCKED":
        if (
            set(result) != BLOCKED_PUBLIC_RESULT_KEYS
            or type(result.get("schema_version")) is not int
            or result.get("schema_version") != 1
            or result.get("operation") != command
            or result.get("private_roster_complete") is not False
            or type(result.get("gaps")) is not int
            or result["gaps"] < 1
            or result.get("sensitivity") != "internal_confidential"
            or result.get("raw_payloads_present") is not False
            or not _valid_error_codes(result.get("error_codes"), BLOCKED_ERROR_CODES)
            or not result["error_codes"]
        ):
            raise ValueError("invalid public result")
        return dict(result)

    if command == "acquire-sources":
        keys = ACQUISITION_PUBLIC_KEYS
        expected_operation = "acquire-video-source-roster"
        allowed_errors = ACQUISITION_ERROR_CODES
        sensitivity = "internal_editorial"
    elif command == "extract-sources":
        keys = EXTRACTION_PUBLIC_RESULT_KEYS
        expected_operation = "extract-sources"
        allowed_errors = EXTRACTION_ERROR_CODES
        sensitivity = None
    elif command == "freeze-sources":
        keys = TOOLING_PUBLIC_RESULT_KEYS - {"ontology_valid"}
        expected_operation = "freeze-sources"
        allowed_errors = TOOLING_ERROR_CODES
        sensitivity = "internal_confidential"
    else:
        keys = TOOLING_PUBLIC_RESULT_KEYS
        expected_operation = "validate-ontology"
        allowed_errors = TOOLING_ERROR_CODES
        sensitivity = "internal_confidential"

    status = result.get("status")
    if (
        set(result) != keys
        or type(result.get("schema_version")) is not int
        or result.get("schema_version") != 1
        or result.get("operation") != expected_operation
        or status not in {"VALID", "INVALID"}
        or type(result.get("private_roster_complete")) is not bool
        or type(result.get("gaps")) is not int
        or result["gaps"] < 0
        or result.get("raw_payloads_present") is not False
        or not _valid_error_codes(result.get("error_codes"), allowed_errors)
    ):
        raise ValueError("invalid public result")
    if sensitivity is not None and result.get("sensitivity") != sensitivity:
        raise ValueError("invalid public result")
    if status == "VALID" and (result["gaps"] != 0 or result["error_codes"]):
        raise ValueError("invalid public result")
    if status == "VALID" and result["private_roster_complete"] is not True:
        raise ValueError("invalid public result")
    if status == "INVALID" and (result["gaps"] < 1 or not result["error_codes"]):
        raise ValueError("invalid public result")
    if (
        status == "INVALID"
        and command != "validate-ontology"
        and result["private_roster_complete"] is not False
    ):
        raise ValueError("invalid public result")
    if command == "extract-sources" and (
        type(result.get("sandbox_verified")) is not bool
        or type(result.get("format_supported")) is not bool
        or result["sandbox_verified"] is not (status == "VALID")
        or (status == "VALID" and result["format_supported"] is not True)
    ):
        raise ValueError("invalid public result")
    if command == "validate-ontology" and result.get("ontology_valid") is not (status == "VALID"):
        raise ValueError("invalid public result")
    return dict(result)


def _emit_video_result(command: str, value: object) -> int:
    try:
        safe = _validated_video_result(command, value)
    except Exception:
        safe = dict(blocked_result(command))
    print(json.dumps(safe, sort_keys=True))
    return 0 if safe["status"] == "VALID" else 1


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
    brain = subparsers.add_parser(
        "brain-serve",
        description="Run the authenticated numeric-loopback Metis Brain service.",
    )
    brain.add_argument("--config", type=Path, required=True)
    video_semantics = subparsers.add_parser(
        "video-semantics",
        description="Run bounded local preparation for video semantic grounding.",
    )
    video_commands = video_semantics.add_subparsers(dest="video_semantics_command", required=True)
    video_commands.add_parser(
        "bootstrap-artifacts",
        description="Verify the fixed ignored private artifact boundary.",
    )
    acquire = video_commands.add_parser(
        "acquire-sources",
        description="Acquire a bounded authorized source roster into the private store.",
    )
    acquire.add_argument("--source-root", type=Path, required=True)
    video_commands.add_parser(
        "freeze-sources",
        description="Freeze the complete private source roster.",
    )
    video_commands.add_parser(
        "validate-ontology",
        description="Validate the fixed private editorial ontology JSONL.",
    )
    video_commands.add_parser(
        "extract-sources",
        description="Extract the frozen source roster inside the local sandbox.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "brain-serve":
        return run_brain_server(args.config)
    if args.command == "video-semantics":
        operation = args.video_semantics_command
        if operation == "bootstrap-artifacts":
            try:
                receipt = prepare_artifact_boundary()
                validate_public_receipt(receipt)
            except Exception:
                print(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "operation": "bootstrap-artifacts",
                            "status": "BLOCKED",
                            "error_code": "ARTIFACT_BOUNDARY_INVALID",
                        },
                        sort_keys=True,
                    )
                )
                return 1
            print(json.dumps(receipt, sort_keys=True))
            return 0
        try:
            if operation == "acquire-sources":
                result = acquire_sources(args.source_root)
            elif operation == "freeze-sources":
                result = freeze_sources()
            elif operation == "validate-ontology":
                result = validate_ontology()
            elif operation == "extract-sources":
                result = extract_sources()
            else:
                raise AssertionError(f"unhandled video semantics command: {operation}")
        except VideoSourceAcquisitionError as error:
            result = source_acquisition_failure(error)
            return _emit_video_result(operation, result)
        except VideoSourceExtractionError as error:
            result = source_extraction_failure(error)
            return _emit_video_result(operation, result)
        except (VideoPrivateIOError, VideoSemanticsPrivateRunnerError) as error:
            code = error.code if isinstance(error, VideoSemanticsPrivateRunnerError) else None
            result = blocked_result(operation, code or "PRIVATE_OPERATION_BLOCKED")
            return _emit_video_result(operation, result)
        except Exception:
            return _emit_video_result(operation, blocked_result(operation))
        return _emit_video_result(operation, result)
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

    try:
        report = validate_foundation(args.root)
    except Exception:
        report = ValidationReport(errors=["foundation validation failed closed"])
    if args.as_json:
        _render_json(report)
    else:
        _render_text(report)
    return 0 if report.ok else 1
