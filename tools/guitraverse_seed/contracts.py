from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class ManifestError(ValueError):
    pass


class DeviceGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class SystemSeed:
    airplane_mode: bool
    wifi: bool
    rotation: str
    locale: str


@dataclass(frozen=True)
class ContactSeed:
    name: str
    number: str


@dataclass(frozen=True)
class FileSeed:
    path: str
    kind: str
    content: str = ""
    title: str = ""


@dataclass(frozen=True)
class MessageSeed:
    sender: str
    body: str


@dataclass(frozen=True)
class CalendarSeed:
    title: str
    offset_days: int
    hour: int
    duration_minutes: int


@dataclass(frozen=True)
class PhotoSeed:
    path: str
    label: str
    color: str


@dataclass(frozen=True)
class SeedManifest:
    schema: str
    profile: str
    avd_name: str
    snapshot_name: str
    required_packages: tuple[str, ...]
    system: SystemSeed
    contacts: tuple[ContactSeed, ...]
    files: tuple[FileSeed, ...]
    messages: tuple[MessageSeed, ...]
    calendar: tuple[CalendarSeed, ...]
    photos: tuple[PhotoSeed, ...]


@dataclass(frozen=True)
class DeviceIdentity:
    serial: str
    avd_name: str
    boot_completed: bool
    locale: str
    packages: tuple[str, ...]


@dataclass(frozen=True)
class SeedContext:
    serial: str
    avd_name: str
    release_id: str
    manifest_digest: str
    sdk: int
    locale: str
    system_fingerprint: str


@dataclass(frozen=True)
class StageResult:
    app_id: str
    status: Literal["passed", "failed", "skipped"]
    evidence: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class TraversalSeedObject:
    seed_id: str
    display_name: str
    shape_tags: tuple[str, ...]
    data: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class TraversalSeedDataset:
    dataset_id: str
    expected_count: int
    required_shapes: tuple[str, ...]
    objects: tuple[TraversalSeedObject, ...]
    reference_only: bool = False
    declared_shapes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TraversalSeedProfile:
    schema: str
    release_id: str
    profile: str
    snapshot_name: str
    builder_avd: str
    source_snapshot: str
    prng_seed: int
    adapter_ids: tuple[str, ...]
    shared_datasets: tuple[TraversalSeedDataset, ...]
    app_datasets: tuple[TraversalSeedDataset, ...]


@dataclass(frozen=True)
class ApkLockEntry:
    adapter_id: str
    display_name: str
    gcs_object: str
    sha256: str
    size_bytes: int
    package: str
    version_name: str
    version_code: int
    signer_sha256: str
    abis: tuple[str, ...]
    min_sdk: int
    target_sdk: int
    upstream_url: str
    upstream_revision: str
    spdx_license: str
    redistributable: bool
    trademark_note: str
    verified_at: str


@dataclass(frozen=True)
class AppsLock:
    schema: str
    release_id: str
    state: str
    entries: tuple[ApkLockEntry, ...]


@dataclass(frozen=True)
class AssetLockEntry:
    asset_id: str
    device_path: str
    kind: str
    sha256: str
    size_bytes: int
    source_type: str
    source: str
    generator_id: str
    generator_version: str
    generation_params: tuple[tuple[str, object], ...]
    spdx_license: str


@dataclass(frozen=True)
class AssetsLock:
    schema: str
    release_id: str
    state: str
    generator_provenance: tuple[tuple[str, str], ...]
    entries: tuple[AssetLockEntry, ...]


@dataclass(frozen=True)
class AppSeedStatus:
    adapter_id: str
    installed: bool
    setup: bool
    data: bool
    gui: bool
    evidence: tuple[str, ...] = ()
    partial_reason: str = ""


@dataclass(frozen=True)
class SharedSeedStatus:
    domain: str
    passed: bool
    evidence: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class CertificateIsolation:
    run_a_passed: bool
    run_b_passed: bool
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeedCertificate:
    release_id: str
    snapshot_name: str
    code_commit: str
    manifest_digest: str
    apps_lock_digest: str
    assets_lock_digest: str
    generator_provenance: str
    app_statuses: tuple[AppSeedStatus, ...]
    shared_statuses: tuple[SharedSeedStatus, ...]
    snapshot_saved: bool
    snapshot_list: tuple[str, ...]
    isolation: CertificateIsolation
    known_gaps: tuple[str, ...]
    valid_until: str
    profile: TraversalSeedProfile | None = None
    apps_lock: AppsLock | None = None
    assets_lock: AssetsLock | None = None
