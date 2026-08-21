"""Focused, payload-free adversarial tests for the W4 full-state wrapper.

Run with the isolated qualification interpreter:

    qualification/.venv/bin/python -m unittest qualification.test_full_state

These tests exercise only metadata, tiny MLX arrays and temporary files. They
never load the Qwen checkpoint and never start training.
"""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mlx.core as mx

from qualification import train_full_state as full_state


class FullStateHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.training_config = {
            "batch_size": 1,
            "gradient_accumulation_steps": 1,
            "max_seq_length": 128,
            "learning_rate": 1e-5,
            "lora_rank": 8,
            "lora_alpha": 16.0,
            "lora_dropout": 0.0,
            "train_on_completions": True,
            "assistant_id": 77091,
            "seed": 17,
        }
        self.model_identity = {"revision": "r1", "payload": [{"sha256": "a"}]}
        self.runtime_identity = {"packages": {"mlx": "0.32.1"}, "uv_lock_sha256": "b"}
        self.dataset_fingerprint = {"path": "/tmp/train.jsonl", "sha256": "c"}

    @staticmethod
    def adapter_config() -> dict[str, object]:
        return {
            "fine_tune_type": "lora",
            "num_layers": -1,
            "lora_parameters": {
                "rank": 8,
                "dropout": 0.0,
                "scale": 2.0,
                "keys": [
                    "language_model.layers.0.self_attn.q_proj",
                    "language_model.layers.1.self_attn.q_proj",
                ],
            },
        }

    @staticmethod
    def checkpoint_files(root: Path) -> Path:
        checkpoint = root / "step-00000006"
        checkpoint.mkdir(parents=True)
        payloads = {
            full_state.STATE_FILE: b"{}\n",
            full_state.ARRAYS_FILE: b"arrays",
            full_state.ADAPTER_FILE: b"adapter",
            full_state.ADAPTER_CONFIG_FILE: json.dumps(
                FullStateHardeningTests.adapter_config(), sort_keys=True
            ).encode()
            + b"\n",
        }
        for name, payload in payloads.items():
            (checkpoint / name).write_bytes(payload)
        files = {
            name: {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for name, payload in payloads.items()
        }
        (checkpoint / full_state.MANIFEST_FILE).write_text(
            json.dumps(
                {"schema_version": 1, "status": "complete", "global_step": 6, "files": files},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return checkpoint

    def valid_sampler(self) -> dict[str, object]:
        return full_state._sampler_state(
            1,
            2,
            4,
            full_state.capture_numpy_rng(),
            full_state.capture_python_rng(),
        )

    def valid_metadata(self) -> dict[str, object]:
        return {
            "model": self.model_identity,
            "runtime": self.runtime_identity,
            "dataset": {"split": "train", "fingerprint": self.dataset_fingerprint},
            "training_config": self.training_config,
            "global_step": 6,
            "sampler": self.valid_sampler(),
            "rng": {
                "mlx": full_state.capture_mlx_rng(),
                "numpy": full_state.capture_numpy_rng(),
                "python": full_state.capture_python_rng(),
            },
            "optimizer": {},
            "arrays_signature": [],
            "distributed": {"world_size": 1, "rank": 0},
        }

    def test_nonfinite_tree_rejected_but_zero_gradient_is_allowed(self) -> None:
        full_state._assert_tree_finite({"weight": mx.zeros((2, 2))}, "zero gradient")
        with self.assertRaises(full_state.FullStateError):
            full_state._assert_tree_finite({"weight": mx.array([float("nan")])}, "nan gradient")
        with self.assertRaises(full_state.FullStateError):
            full_state._assert_tree_finite({"weight": mx.array([float("inf")])}, "inf gradient")

    def test_sampler_type_and_global_step_tampering_fail_closed(self) -> None:
        sampler = self.valid_sampler()
        full_state._validate_sampler_state(sampler, global_step=6)
        sampler["cursor"] = 1
        with self.assertRaises(full_state.FullStateError):
            full_state._validate_sampler_state(sampler, global_step=6)
        sampler = self.valid_sampler()
        sampler["cursor"] = "2"
        with self.assertRaises(full_state.FullStateError):
            full_state._validate_sampler_state(sampler, global_step=6)

    def test_adapter_config_is_bound_to_training_config(self) -> None:
        expected_keys = [
            "language_model.layers.0.self_attn.q_proj",
            "language_model.layers.1.self_attn.q_proj",
        ]
        full_state._validate_adapter_config(
            self.adapter_config(), self.training_config, expected_keys=expected_keys
        )
        tampered = self.adapter_config()
        tampered["lora_parameters"]["scale"] = 1.0  # type: ignore[index]
        with self.assertRaises(full_state.FullStateError):
            full_state._validate_adapter_config(
                tampered, self.training_config, expected_keys=expected_keys
            )
        extra = self.adapter_config()
        extra["lora_parameters"]["unregistered_option"] = True  # type: ignore[index]
        with self.assertRaises(full_state.FullStateError):
            full_state._validate_adapter_config(
                extra, self.training_config, expected_keys=expected_keys
            )
        for invalid_keys in (
            ["arbitrary.unregistered.module"],
            expected_keys[:1],
            [*expected_keys, "language_model.layers.2.self_attn.q_proj"],
        ):
            invalid = self.adapter_config()
            invalid["lora_parameters"]["keys"] = invalid_keys  # type: ignore[index]
            with self.assertRaises(full_state.FullStateError):
                full_state._validate_adapter_config(
                    invalid,
                    self.training_config,
                    expected_keys=expected_keys,
                )

    def test_checkpoint_manifest_tamper_and_symlink_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = self.checkpoint_files(Path(temporary))
            full_state._validate_checkpoint_manifest(checkpoint)
            (checkpoint / full_state.ARRAYS_FILE).write_bytes(b"tampered")
            with self.assertRaises(full_state.FullStateError):
                full_state._validate_checkpoint_manifest(checkpoint)

            checkpoint = self.checkpoint_files(Path(temporary) / "symlink")
            target = checkpoint / full_state.ADAPTER_FILE
            target.unlink()
            outside = Path(temporary) / "outside-adapter"
            outside.write_bytes(b"adapter")
            try:
                target.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            with self.assertRaises(full_state.FullStateError):
                full_state._read_checkpoint(checkpoint)

    def test_malformed_metadata_is_full_state_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = self.checkpoint_files(Path(temporary))
            (checkpoint / full_state.STATE_FILE).write_text("[]\n", encoding="utf-8")
            with self.assertRaises(full_state.FullStateError):
                full_state._load_json_object(
                    checkpoint / full_state.STATE_FILE,
                    label="checkpoint metadata",
                )

    def test_sampler_rejects_nonfinite_python_gaussian_cache(self) -> None:
        sampler = self.valid_sampler()
        sampler["epoch_start_python"]["gaussian"] = float("nan")  # type: ignore[index]
        with self.assertRaises(full_state.FullStateError):
            full_state._validate_sampler_state(sampler, global_step=6)

    def test_model_and_runtime_identity_mismatch_fail_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary)
            (checkpoint / full_state.ADAPTER_CONFIG_FILE).write_text(
                json.dumps(self.adapter_config()), encoding="utf-8"
            )
            metadata = self.valid_metadata()
            metadata["model"] = {"revision": "different"}
            with self.assertRaises(full_state.FullStateError):
                full_state._validate_resume(
                    metadata=metadata,
                    checkpoint=checkpoint,
                    model_identity=self.model_identity,
                    runtime=self.runtime_identity,
                    dataset_fingerprint=self.dataset_fingerprint,
                    split="train",
                    training_config=self.training_config,
                    target_iters=8,
                )

            metadata = self.valid_metadata()
            metadata["runtime"] = {"packages": {"mlx": "different"}}
            with self.assertRaises(full_state.FullStateError):
                full_state._validate_resume(
                    metadata=metadata,
                    checkpoint=checkpoint,
                    model_identity=self.model_identity,
                    runtime=self.runtime_identity,
                    dataset_fingerprint=self.dataset_fingerprint,
                    split="train",
                    training_config=self.training_config,
                    target_iters=8,
                )

    def test_runtime_pin_binds_wrapper_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / "qualification/uv.lock"
            pin = root / "qualification/runtime-pin.json"
            lock.parent.mkdir()
            lock.write_bytes(b"lock")
            package_versions = {
                name: full_state.version(name) for name in full_state.RUNTIME_PACKAGES
            }
            system = platform.system()
            machine = platform.machine()
            platform_pin = f"{'macos' if system == 'Darwin' else system.lower()}-{machine}"
            pin.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "python": platform.python_version(),
                        "platform": platform_pin,
                        "packages": package_versions,
                        "lock_sha256": full_state._sha256_file(lock),
                        "upstream_revisions": {},
                        "qualification_wrapper_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(full_state, "REPOSITORY_ROOT", root),
                self.assertRaises(full_state.FullStateError),
            ):
                full_state.runtime_identity()


if __name__ == "__main__":
    unittest.main()
