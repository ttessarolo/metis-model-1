"""Fresh successor for the terminal DEMO_ACCURACY_V1 diagnosis.

The successor changes only the generic source-syntax prompt and benchmark
identity.  It executes the audited V1 engine inside a scoped configuration so
the default V1 replay contract is restored even when this module is exercised
in-process by tests.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from typing import Any

from metis_model1 import demo_accuracy as core

PROJECT_ROOT = core.PROJECT_ROOT
V1_TASKS_PATH = PROJECT_ROOT / "fixtures/demo-accuracy-v1/tasks.json"
V2_TASKS_PATH = PROJECT_ROOT / "fixtures/demo-accuracy-v2/tasks.json"
V2_TRUTH_PATH = PROJECT_ROOT / "manifests/demo-accuracy-truth-v2.json"
V2_FREEZE_PATH = PROJECT_ROOT / "manifests/demo-accuracy-freeze-v2.json"
V2_EVIDENCE_PATH = PROJECT_ROOT / "manifests/demo-accuracy-evaluation-v2.json"
V2_RUN_DIR = PROJECT_ROOT / "artifacts/demo-accuracy-v2"

_SCAFFOLD_ANCHOR = "- A complete catalog contains catalog, driver, index, id, and fields blocks."
_SCAFFOLD_CURE = "\n".join(
    (
        _SCAFFOLD_ANCHOR,
        "- A catalog and its `fields` declaration are brace-delimited blocks: open each ",
        "  with `{` and close it with its matching `}`. Newlines and indentation never ",
        "  replace either brace pair.",
        '- The `index` directive takes a double-quoted string: `index "<index-name>"`.',
    )
)
SUCCESSOR_SOURCE_SYSTEM_PROMPT = core.SOURCE_SYSTEM_PROMPT.replace(_SCAFFOLD_ANCHOR, _SCAFFOLD_CURE)
if SUCCESSOR_SOURCE_SYSTEM_PROMPT == core.SOURCE_SYSTEM_PROMPT:
    raise RuntimeError("successor scaffold anchor is absent")
if "demoacc_" in SUCCESSOR_SOURCE_SYSTEM_PROMPT or "public.video" in SUCCESSOR_SOURCE_SYSTEM_PROMPT:
    raise RuntimeError("successor scaffold contains benchmark-specific leakage")

_REPLACED_BOUND_PATHS = {
    "fixtures/demo-accuracy-v1/tasks.json",
    "manifests/demo-accuracy-truth-v1.json",
}
SUCCESSOR_BOUND_PATHS = (
    "fixtures/demo-accuracy-v2/tasks.json",
    "manifests/demo-accuracy-truth-v2.json",
    "fixtures/demo-accuracy-v1/tasks.json",
    "src/metis_model1/demo_accuracy_successor.py",
    "tests/test_demo_accuracy_successor.py",
    *(path for path in core.BOUND_PATHS if path not in _REPLACED_BOUND_PATHS),
)

_OVERRIDES: dict[str, Any] = {
    "TASKS_PATH": V2_TASKS_PATH,
    "TRUTH_PATH": V2_TRUTH_PATH,
    "FREEZE_PATH": V2_FREEZE_PATH,
    "EVIDENCE_PATH": V2_EVIDENCE_PATH,
    "RUN_DIR": V2_RUN_DIR,
    "BENCHMARK_ID": "demo-accuracy-v2",
    "TASK_ID_PREFIX": "demoacc_v2_",
    "SOURCE_PREFIX": "public-synthetic/demoacc/v2/",
    "TASK_AUTHORITY_SCOPE": "public_synthetic_catalog_domain_successor_only",
    "EXECUTION_AUTHORITY_SCOPE": (
        "public_synthetic_catalog_domain_mac_demo_accuracy_successor_only"
    ),
    "TRUTH_ID": "demo-accuracy-truth/v2",
    "FREEZE_ID": "demo-accuracy-freeze/v2",
    "EVIDENCE_ID": "demo-accuracy-evaluation/v2",
    "PASS_VERDICT": "DEMO_ACCURACY_V2_PASS",
    "DIAGNOSE_VERDICT": "DEMO_ACCURACY_V2_DIAGNOSE",
    "FRESHNESS_NAMESPACE": b"demoacc_v2_",
    "FRESHNESS_SOURCE_PATHS": (
        core.DATASET_TRAIN,
        core.DATASET_DEV,
        core.B12_ROSTER,
        V1_TASKS_PATH,
    ),
    "IDENTIFIER_RE": re.compile(r"\bdemoacc_v2_[a-z0-9_]+\b"),
    "SOURCE_SYSTEM_PROMPT": SUCCESSOR_SOURCE_SYSTEM_PROMPT,
    "BOUND_PATHS": SUCCESSOR_BOUND_PATHS,
}


@contextlib.contextmanager
def successor_configuration() -> Iterator[None]:
    """Install the complete V2 contract and restore V1 on every exit path."""

    previous = {name: getattr(core, name) for name in _OVERRIDES}
    try:
        for name, value in _OVERRIDES.items():
            setattr(core, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(core, name, value)


def main(argv: list[str] | None = None) -> int:
    with successor_configuration():
        return core.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
