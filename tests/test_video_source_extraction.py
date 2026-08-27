from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

import metis_model1.video_source_extraction as extraction
from metis_model1.video_semantics_contracts import (
    literal_sha256,
    manifest_digest,
    semantic_source_revision,
)
from metis_model1.video_source_extraction import (
    EXTRACTOR_ID,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    SUBPROCESS_TIMEOUT_SECONDS,
    SourceExtractionOutcome,
    VideoSourceExtractionError,
    extract_private_source,
    validate_private_envelope,
)


def _synthetic_pdf_bytes(marker: str = "Synthetic Marker") -> bytes:
    stream = f"BT /F1 24 Tf 72 720 Td ({marker}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, item in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode() + item + b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(document)


class FakeRunner:
    def __init__(self, text: bytes = b"extracted text\n") -> None:
        self.text = text
        self.calls: list[tuple[list[str], dict[str, str], float, int | None]] = []
        self.result: subprocess.CompletedProcess[bytes] | None = None
        self.on_extract = None

    def __call__(self, argv, env, timeout, stdin_fd):
        self.calls.append((list(argv), dict(env), timeout, stdin_fd))
        command = list(argv)[3:]
        if command[0] == "/bin/cat" and len(command) > 1:
            return subprocess.CompletedProcess(argv, 1, b"", b"denied")
        if command[0] in {"/usr/bin/touch", "/usr/bin/nc"}:
            return subprocess.CompletedProcess(argv, 1, b"", b"denied")
        if stdin_fd is not None:
            prefix = os.pread(stdin_fd, 64, 0)
            if prefix == b"synthetic-sandbox-canary":
                return subprocess.CompletedProcess(argv, 0, prefix, b"")
        if self.on_extract is not None:
            self.on_extract()
        if self.result is not None:
            return self.result
        if "JavaScript" in command:
            payload = json.dumps(
                {
                    "schema_version": 1,
                    "unit_kind": "page",
                    "units": [{"ordinal": 1, "text": self.text.decode("utf-8")}],
                },
                separators=(",", ":"),
            ).encode("utf-8")
            return subprocess.CompletedProcess(argv, 0, payload, b"")
        return subprocess.CompletedProcess(argv, 0, self.text, b"")


@pytest.fixture
def source_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict, Path, tuple[Path, ...]]:
    root = tmp_path / "sources"
    root.mkdir(mode=0o755)
    files = (root / "guide.pdf", root / "guide.txt")
    contents = (_synthetic_pdf_bytes(), b"synthetic plain bytes\n")
    sources = []
    entries = []
    receipts = []
    for index, (path, payload) in enumerate(zip(files, contents, strict=True), start=1):
        path.write_bytes(payload)
        path.chmod(0o644)
        source_id = f"source-{index:06d}"
        source_ref = f"source-ref-{index:06d}"
        sources.append(
            {
                "source_id": source_id,
                "source_ref": source_ref,
                "kind": "reserved_editorial",
                "identity_storage": "local-confidential-receipt",
                "repository_commit": None,
                "tenant": "private-tenant-v1",
                "catalog": "video",
                "sensitivity": "internal_editorial",
                "manifest_schema": 1,
                "content_sha256": literal_sha256(payload),
            }
        )
        entries.append(
            {
                "source_id": source_id,
                "source_ref": source_ref,
                "locator": path.name,
                "name": path.name,
                "format": "pdf" if path.suffix == ".pdf" else "txt",
                "size_bytes": len(payload),
            }
        )
    manifest = {
        "schema_version": 1,
        "manifest_id": "video-semantics/sources-v1",
        "semantic_source_revision": "sha256:" + "0" * 64,
        "sources": sources,
    }
    manifest["semantic_source_revision"] = semantic_source_revision(manifest)
    manifest_sha = manifest_digest(manifest)
    for index, source in enumerate(sources, start=1):
        receipt = {
            "schema_version": 1,
            "receipt_id": f"receipt-{index:06d}",
            "manifest_sha256": manifest_sha,
            "source_id": source["source_id"],
            "status": "VALID",
            "acquired_at": "2026-08-27T10:00:00Z",
            "duration_ms": 1,
            "run_id": f"run-{index:07d}",
            "runtime": {"python": "3.13", "tool_version": EXTRACTOR_ID},
            "counts": {"items_in": 1, "items_out": 1, "items_distinct": 1, "items_gaps": 0},
        }
        receipt["receipt_sha256"] = manifest_digest(receipt)
        receipts.append(receipt)
    document = {
        "schema_version": 1,
        "artifact_kind": "video-source-acquisition-bundle-v1",
        "manifest": manifest,
        "receipt_roster": {
            "schema_version": 1,
            "roster_id": "video-semantics/acquisition-receipts-v1",
            "manifest_sha256": manifest_sha,
            "receipts": receipts,
        },
        "locator_registry": {
            "schema_version": 1,
            "registry_id": "video-semantics/private-locators-v1",
            "manifest_sha256": manifest_sha,
            "root_locator": str(root.resolve()),
            "entries": entries,
        },
        "bundle_sha256": "",
    }
    document["bundle_sha256"] = manifest_digest(
        {key: value for key, value in document.items() if key != "bundle_sha256"}
    )
    monkeypatch.setattr(extraction, "SANDBOX_EXECUTABLE", sys.executable)
    monkeypatch.setattr(extraction, "PDF_EXECUTABLE", "/usr/bin/true")
    return document, root, files


def test_extracts_multi_source_bundle_and_redacts_public_result(source_bundle) -> None:
    bundle, root, _ = source_bundle
    runner = FakeRunner()
    outcome = extract_private_source(bundle, runner=runner)
    assert isinstance(outcome, SourceExtractionOutcome)
    assert len(outcome.private_envelope["sources"]) == 2
    assert outcome.private_envelope["sources"][0]["unit_kind"] == "page"
    assert outcome.private_envelope["sources"][0]["unit_counts"] == {
        "items_in": 1,
        "items_out": 1,
        "items_distinct": 1,
        "items_gaps": 0,
    }
    assert extraction.private_unit_roster(outcome.private_envelope) == {
        "source-ref-000001": ("page-000001",),
        "source-ref-000002": ("document-000001",),
    }
    validate_private_envelope(outcome.private_envelope, bundle["manifest"])
    public = outcome.public_result
    assert set(public) == extraction._PUBLIC_KEYS
    encoded = json.dumps(public, sort_keys=True)
    assert str(root) not in encoded
    assert "source-ref-" not in encoded
    assert "extracted text" not in encoded
    assert "sha256:" not in encoded
    assert public["status"] == "SYNTHETIC"
    assert public["sandbox_verified"] is False
    assert outcome.private_envelope["evidence_mode"] == "synthetic"
    assert len(runner.calls) == 5 * 2
    assert all(timeout == SUBPROCESS_TIMEOUT_SECONDS for _, _, timeout, _ in runner.calls)
    assert all(
        env == {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}
        for _, env, _, _ in runner.calls
    )
    for offset in (0, 5):
        profiles = {call[0][2] for call in runner.calls[offset : offset + 5]}
        assert len(profiles) == 1
        profile = next(iter(profiles))
        assert "(deny default)" in profile
        assert "(allow default)" not in profile
        assert "(deny network*)" in profile
        assert "(deny file-write*)" in profile
        assert "(deny file-read* (subpath" in profile


def test_original_source_modes_are_not_restricted(source_bundle) -> None:
    bundle, root, _ = source_bundle
    root.chmod(0o755)
    outcome = extract_private_source(bundle, runner=FakeRunner())
    assert outcome.public_result["status"] == "SYNTHETIC"


def test_global_deadline_caps_each_canary_without_sleeping(
    source_bundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    del source_bundle
    ticks = iter((100.0, 100.3))
    monkeypatch.setattr(extraction.time, "monotonic", lambda: next(ticks))
    runner = FakeRunner()
    with pytest.raises(VideoSourceExtractionError) as error:
        extraction.verify_sandbox_boundary(
            extraction._sandbox_profile(["/bin/cat"]),
            runner=runner,
            deadline=100.25,
        )
    assert error.value.code == "EXTRACTION_TIMEOUT"
    assert len(runner.calls) == 1
    assert runner.calls[0][2] == pytest.approx(0.25)


def test_sandbox_attestation_rejects_bytes_from_denied_read() -> None:
    class LeakingDeniedReadRunner(FakeRunner):
        def __call__(self, argv, env, timeout, stdin_fd):
            command = list(argv)[3:]
            if command[0] == "/bin/cat" and len(command) > 1:
                return subprocess.CompletedProcess(argv, 1, b"forbidden-bytes", b"denied")
            return super().__call__(argv, env, timeout, stdin_fd)

    with pytest.raises(VideoSourceExtractionError) as error:
        extraction.verify_sandbox_boundary(
            extraction._sandbox_profile(["/bin/cat"]),
            runner=LeakingDeniedReadRunner(),
            deadline=time.monotonic() + 10.0,
        )
    assert error.value.code == "SANDBOX_CANARY_FAILED"


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="requires the pinned macOS sandbox boundary",
)
def test_real_macos_sandbox_canaries_and_inherited_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extraction, "SANDBOX_EXECUTABLE", "/usr/bin/sandbox-exec")
    command = ["/bin/cat"]
    profile = extraction._sandbox_profile(command)
    deadline = time.monotonic() + 20.0
    extraction.verify_sandbox_boundary(profile, deadline=deadline)
    with tempfile.TemporaryDirectory(dir=Path.home(), prefix=".metis-video-sandbox-") as temp:
        source = Path(temp) / "synthetic-input.txt"
        source.write_bytes(b"synthetic-local-input")
        with source.open("rb") as handle:
            result = extraction._invoke(
                command,
                profile,
                None,
                stdin_fd=handle.fileno(),
                deadline=deadline,
            )
    assert result.returncode == 0
    assert result.stdout == b"synthetic-local-input"
    assert result.stderr == b""

    pdf_command, _ = extraction._format_command("pdf")
    pdf_profile = extraction._sandbox_profile(pdf_command)
    extraction.verify_sandbox_boundary(pdf_profile, deadline=deadline)
    with tempfile.TemporaryFile(prefix="metis-video-real-pdf-") as handle:
        handle.write(_synthetic_pdf_bytes())
        handle.flush()
        handle.seek(0)
        pdf_result = extraction._invoke(
            pdf_command,
            pdf_profile,
            None,
            stdin_fd=handle.fileno(),
            deadline=deadline,
        )
    assert pdf_result.returncode == 0
    unit_kind, units, extracted_bytes = extraction._decode_extracted_units("pdf", pdf_result.stdout)
    assert unit_kind == "page"
    assert units == [
        {
            "source_locator": "page-000001",
            "ordinal": 1,
            "text_sha256": extraction._sha256_bytes(b"Synthetic Marker"),
            "text": "Synthetic Marker",
        }
    ]
    assert extracted_bytes == len(b"Synthetic Marker")


@pytest.mark.skipif(os.getuid() == 0, reason="requires a non-root test owner")
def test_user_owned_parser_is_not_eligible_for_real_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = tmp_path / "parser"
    parser.write_bytes(b"synthetic parser")
    parser.chmod(0o500)
    monkeypatch.setattr(extraction, "PDF_EXECUTABLE", str(parser))
    with pytest.raises(VideoSourceExtractionError) as error:
        extraction._format_command("pdf")
    assert error.value.code == "TOOL_INVALID"


@pytest.mark.parametrize("field", ["root_locator", "entries"])
def test_real_bundle_registry_tampering_fails_closed(source_bundle, field: str) -> None:
    bundle, _, _ = source_bundle
    tampered = json.loads(json.dumps(bundle))
    if field == "root_locator":
        tampered["locator_registry"]["root_locator"] = "/tmp/outside"
    else:
        tampered["locator_registry"]["entries"][0]["locator"] = "../outside.pdf"
    with pytest.raises(VideoSourceExtractionError):
        extract_private_source(tampered, runner=FakeRunner())


def test_symlink_and_hardlink_entries_fail_closed(source_bundle, tmp_path: Path) -> None:
    bundle, root, files = source_bundle
    files[0].unlink()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"synthetic pdf bytes\n")
    outside.chmod(0o600)
    files[0].symlink_to(outside)
    with pytest.raises(VideoSourceExtractionError):
        extract_private_source(bundle, runner=FakeRunner())

    files[0].unlink()
    files[0].write_bytes(b"synthetic pdf bytes\n")
    files[0].chmod(0o644)
    os.link(files[0], tmp_path / "hardlink.pdf")
    with pytest.raises(VideoSourceExtractionError):
        extract_private_source(bundle, runner=FakeRunner())


def test_source_replacement_during_extraction_is_rejected(source_bundle) -> None:
    bundle, _, files = source_bundle
    replacement = files[0].with_name("replacement.pdf")
    replacement.write_bytes(b"replacement bytes\n")
    replacement.chmod(0o600)
    runner = FakeRunner()
    runner.on_extract = lambda: os.replace(replacement, files[0])
    with pytest.raises(VideoSourceExtractionError):
        extract_private_source(bundle, runner=runner)


def test_canary_failure_and_output_limits_are_redacted(source_bundle) -> None:
    bundle, _, _ = source_bundle

    def failed_canary(argv, env, timeout, stdin_fd):
        return subprocess.CompletedProcess(argv, 9, b"", b"private diagnostic")

    with pytest.raises(VideoSourceExtractionError) as error:
        extract_private_source(bundle, runner=failed_canary)
    assert str(error.value) == "video source extraction blocked"

    for stdout, stderr in (
        (b"x" * (MAX_STDOUT_BYTES + 1), b""),
        (b"ok", b"x" * (MAX_STDERR_BYTES + 1)),
    ):
        runner = FakeRunner()
        runner.result = subprocess.CompletedProcess([], 0, stdout, stderr)
        with pytest.raises(VideoSourceExtractionError):
            extract_private_source(bundle, runner=runner)


def test_private_envelope_tamper_and_runner_error_are_generic(source_bundle) -> None:
    bundle, _, _ = source_bundle
    outcome = extract_private_source(bundle, runner=FakeRunner())
    tampered = dict(outcome.private_envelope)
    tampered["sources"] = list(tampered["sources"])
    tampered["sources"][0] = dict(tampered["sources"][0])
    tampered["sources"][0]["units"] = list(tampered["sources"][0]["units"])
    tampered["sources"][0]["units"][0] = dict(tampered["sources"][0]["units"][0], text="tampered")
    with pytest.raises(VideoSourceExtractionError):
        validate_private_envelope(tampered, bundle["manifest"])

    def raises(*args):
        raise RuntimeError("private path and payload")

    with pytest.raises(VideoSourceExtractionError) as error:
        extract_private_source(bundle, runner=raises)
    assert str(error.value) == "video source extraction blocked"


def test_real_mode_requires_independent_real_recomputation(
    source_bundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, _, _ = source_bundle
    synthetic = extract_private_source(bundle, runner=FakeRunner()).private_envelope
    promoted = json.loads(json.dumps(synthetic))
    promoted["evidence_mode"] = "real"
    body = {key: value for key, value in promoted.items() if key != "envelope_sha256"}
    promoted["envelope_sha256"] = extraction._sha256_bytes(extraction._canonical_json(body))

    with pytest.raises(VideoSourceExtractionError):
        validate_private_envelope(promoted, bundle["manifest"], require_real=True)

    trusted = json.loads(json.dumps(promoted))
    trusted_unit = trusted["sources"][0]["units"][0]
    trusted_unit["text"] = "independently recomputed text\n"
    trusted_unit["text_sha256"] = extraction._sha256_bytes(trusted_unit["text"].encode("utf-8"))
    trusted["sources"][0]["unit_roster_sha256"] = extraction._sha256_bytes(
        extraction._canonical_json(trusted["sources"][0]["units"])
    )
    trusted["extraction_input_sha256"] = extraction._extraction_input_sha(
        bundle["manifest"], trusted["sources"]
    )
    body = {key: value for key, value in trusted.items() if key != "envelope_sha256"}
    trusted["envelope_sha256"] = extraction._sha256_bytes(extraction._canonical_json(body))
    trusted_outcome = SourceExtractionOutcome(
        private_envelope=trusted,
        public_result={"status": "VALID", "sandbox_verified": True},
    )
    monkeypatch.setattr(extraction, "extract_private_source", lambda bundle: trusted_outcome)

    with pytest.raises(VideoSourceExtractionError):
        validate_private_envelope(
            promoted,
            bundle["manifest"],
            require_real=True,
            source_bundle=bundle,
        )
    validate_private_envelope(
        trusted,
        bundle["manifest"],
        require_real=True,
        source_bundle=bundle,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_ref",
        "extra_key",
        "tool_identity",
        "command",
        "sandbox_profile",
        "unit_count",
        "schema_bool",
        "gaps_bool",
        "unit_count_bool",
    ],
)
def test_rehashed_semantic_envelope_tamper_is_rejected(source_bundle, mutation: str) -> None:
    bundle, _, _ = source_bundle
    envelope = json.loads(
        json.dumps(extract_private_source(bundle, runner=FakeRunner()).private_envelope)
    )
    if mutation == "unknown_ref":
        envelope["sources"][0]["source_ref"] = "source-ref-unknown"
    elif mutation == "extra_key":
        envelope["sources"][0]["extra"] = "not-allowed"
    elif mutation == "tool_identity":
        envelope["sources"][0]["tool_identity_sha256"] = "sha256:" + "0" * 64
    elif mutation == "command":
        envelope["sources"][0]["command_sha256"] = "sha256:" + "0" * 64
    elif mutation == "sandbox_profile":
        envelope["sources"][0]["sandbox_profile_sha256"] = "sha256:" + "0" * 64
    elif mutation == "unit_count":
        envelope["sources"][0]["unit_counts"]["items_out"] = 0
    elif mutation == "schema_bool":
        envelope["schema_version"] = True
    elif mutation == "gaps_bool":
        envelope["gaps"] = False
    else:
        envelope["sources"][0]["unit_counts"] = {
            "items_in": True,
            "items_out": True,
            "items_distinct": True,
            "items_gaps": False,
        }
    envelope["extraction_input_sha256"] = extraction._extraction_input_sha(
        bundle["manifest"], envelope["sources"]
    )
    body = {key: value for key, value in envelope.items() if key != "envelope_sha256"}
    envelope["envelope_sha256"] = extraction._sha256_bytes(extraction._canonical_json(body))
    with pytest.raises(VideoSourceExtractionError):
        validate_private_envelope(envelope, bundle["manifest"])


def test_content_detected_format_blocks_renamed_parser_switch(source_bundle) -> None:
    bundle, _, files = source_bundle
    renamed = files[0].with_name("guide-renamed.txt")
    files[0].rename(renamed)
    changed = json.loads(json.dumps(bundle))
    entry = changed["locator_registry"]["entries"][0]
    entry.update(locator=renamed.name, name=renamed.name, format="txt")
    body = {key: value for key, value in changed.items() if key != "bundle_sha256"}
    changed["bundle_sha256"] = manifest_digest(body)
    with pytest.raises(VideoSourceExtractionError) as error:
        extract_private_source(changed, runner=FakeRunner())
    assert error.value.code == "FORMAT_MISMATCH"


def test_total_extraction_output_is_bounded(source_bundle, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, _, _ = source_bundle
    monkeypatch.setattr(extraction, "MAX_TOTAL_EXTRACTED_BYTES", 8)
    with pytest.raises(VideoSourceExtractionError) as error:
        extract_private_source(bundle, runner=FakeRunner(text=b"12345678"))
    assert error.value.code == "EXTRACTION_OUTPUT_TOO_LARGE"
