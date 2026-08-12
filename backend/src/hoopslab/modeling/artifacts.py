"""Local model bundle, portable manifest, and selection-lock integrity helpers."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from hoopslab.modeling.protocol import ModelingProtocolError, sha256_file

BUNDLE_FILENAME = "shot-quality-model.joblib"
MANIFEST_FILENAME = "model-manifest.json"
LOCK_FILENAME = "selection-lock.json"
TEST_REPORT_FILENAME = "final-test-report.json"
FINAL_TEST_RESERVATION_FILENAME = ".final-test-reservation.json"


def utc_timestamp() -> str:
    """Return an explicit UTC timestamp for local reproducibility records."""
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write deterministic, portable JSON with no machine-specific paths."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def reserve_final_test(output_dir: Path) -> Path:
    """Atomically reserve the one final-test attempt before any test-data access.

    The marker remains after any post-access failure so retry requires explicit
    human review and manual artifact-directory intervention; this is fail-closed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / FINAL_TEST_RESERVATION_FILENAME
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ModelingProtocolError(
            "final test already reserved; retry is fail-closed"
        ) from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"status": "reserved", "created_at": utc_timestamp()}) + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    return path


def read_json(path: Path) -> dict[str, Any]:
    """Read one generated JSON object with a useful boundary error."""
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ModelingProtocolError(
            f"cannot read generated record {path.name}"
        ) from error
    if not isinstance(value, dict):
        raise ModelingProtocolError(f"generated record {path.name} is not an object")
    return value


def persist_bundle(
    output_dir: Path, *, selected_model: object, logistic_model: object
) -> tuple[Path, str]:
    """Persist only the locked selected model and tuned logistic comparator."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / BUNDLE_FILENAME
    temporary = path.with_suffix(f"{path.suffix}.part")
    joblib.dump(
        {"selected_model": selected_model, "logistic_comparator": logistic_model},
        temporary,
    )
    temporary.replace(path)
    return path, sha256_file(path)


def validate_bundle(path: Path, expected_sha256: str) -> dict[str, object]:
    """Verify the binary identity and required persisted estimators before use."""
    if sha256_file(path) != expected_sha256:
        raise ModelingProtocolError("model bundle SHA-256 does not match manifest")
    try:
        bundle = joblib.load(path)
    except (OSError, ValueError) as error:
        raise ModelingProtocolError("cannot load model bundle") from error
    if not isinstance(bundle, dict) or set(bundle) != {
        "selected_model",
        "logistic_comparator",
    }:
        raise ModelingProtocolError("model bundle has an unexpected structure")
    return bundle


def validate_record_schema(
    lock: dict[str, Any], manifest: dict[str, Any], report: dict[str, Any] | None = None
) -> None:
    """Validate minimal reproducibility record shape and cross-record identities."""
    required = {
        "artifact_sha256",
        "feature_sha256",
        "split_manifest_sha256",
        "selected_variant",
        "logistic_comparator_variant",
        "protocol",
        "segments",
        "folds",
        "all_calibration_variants",
        "development_elapsed_seconds",
    }
    missing = required.difference(manifest)
    if missing:
        raise ModelingProtocolError(
            f"manifest misses required fields: {sorted(missing)}"
        )
    if lock.get("artifact_sha256") != manifest["artifact_sha256"]:
        raise ModelingProtocolError("lock and manifest artifact hashes disagree")
    if lock.get("feature_sha256") != manifest["feature_sha256"]:
        raise ModelingProtocolError("lock and manifest feature hashes disagree")
    if lock.get("split_manifest_sha256") != manifest["split_manifest_sha256"]:
        raise ModelingProtocolError("lock and manifest split hashes disagree")
    if lock.get("selected_variant") != manifest["selected_variant"]:
        raise ModelingProtocolError("lock and manifest selected variants disagree")
    if (
        lock.get("logistic_comparator_variant")
        != manifest["logistic_comparator_variant"]
    ):
        raise ModelingProtocolError("lock and manifest logistic comparators disagree")
    if report is not None:
        if report.get("status") != "final_test_complete":
            raise ModelingProtocolError("final test report has an invalid status")
        if report.get("lock_artifact_sha256") != manifest["artifact_sha256"]:
            raise ModelingProtocolError("final report artifact hash disagrees")
        if report.get("feature_sha256") != manifest["feature_sha256"]:
            raise ModelingProtocolError("final report feature hash disagrees")
        if report.get("split_manifest_sha256") != manifest["split_manifest_sha256"]:
            raise ModelingProtocolError("final report split manifest hash disagrees")
        if report.get("selected_variant") != manifest["selected_variant"]:
            raise ModelingProtocolError("final report selected variant disagrees")
        if (
            report.get("logistic_comparator_variant")
            != manifest["logistic_comparator_variant"]
        ):
            raise ModelingProtocolError("final report logistic comparator disagrees")


def validate_lock_for_final_test(
    output_dir: Path, feature_sha256: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, object]]:
    """Require a locked, audited development record before touching test rows."""
    lock = read_json(output_dir / LOCK_FILENAME)
    manifest = read_json(output_dir / MANIFEST_FILENAME)
    validate_record_schema(lock, manifest)
    if lock.get("status") != "locked":
        raise ModelingProtocolError("selection lock is not locked")
    if (
        lock.get("test_accessed") is not False
        or lock.get("test_metrics_generated") is not False
    ):
        raise ModelingProtocolError("development lock records prior test access")
    if lock.get("feature_sha256") != feature_sha256:
        raise ModelingProtocolError(
            "selection lock feature hash differs from requested data"
        )
    expected_sha256 = manifest.get("artifact_sha256")
    if (
        not isinstance(expected_sha256, str)
        or lock.get("artifact_sha256") != expected_sha256
    ):
        raise ModelingProtocolError("selection lock and model manifest disagree")
    bundle = validate_bundle(output_dir / BUNDLE_FILENAME, expected_sha256)
    return lock, manifest, bundle


def audit_development_records(output_dir: Path) -> dict[str, Any]:
    """Prove generated development metadata contains no test access or metrics."""
    lock = read_json(output_dir / LOCK_FILENAME)
    manifest = read_json(output_dir / MANIFEST_FILENAME)
    report_path = output_dir / TEST_REPORT_FILENAME
    report = read_json(report_path) if report_path.exists() else None
    validate_record_schema(lock, manifest, report)
    if (
        lock.get("test_accessed") is not False
        or lock.get("test_metrics_generated") is not False
    ):
        raise ModelingProtocolError(
            "development metadata records prohibited test access"
        )
    for record in (lock, manifest):
        encoded = json.dumps(record, sort_keys=True).lower()
        if "2023-24" in encoded or "final-test-report" in encoded:
            raise ModelingProtocolError(
                "development metadata contains final-test evidence"
            )
    return {
        "lock_status": lock.get("status"),
        "artifact_sha256": manifest.get("artifact_sha256"),
    }
