from .adb import AdbClient, preflight_device
from .contracts import (
    DeviceGuardError,
    DeviceIdentity,
    ManifestError,
    SeedContext,
    SeedManifest,
    StageResult,
)
from .cli import main
from .manifest_v1 import (
    DEFAULT_MANIFEST,
    build_seed_plan,
    canonical_manifest_digest,
    load_manifest,
)
from .shared_v1 import apply_seed, load_snapshot, save_snapshot, verify_seed
from .certificate import certificate_ready
from .contracts import (
    ApkLockEntry,
    AppSeedStatus,
    AppsLock,
    AssetLockEntry,
    AssetsLock,
    CertificateIsolation,
    SeedCertificate,
    SharedSeedStatus,
    TraversalSeedDataset,
    TraversalSeedObject,
    TraversalSeedProfile,
)
from .locks import canonical_digest, load_apps_lock, load_assets_lock
from .manifest_v2 import load_v2_manifest
from .androidworld_apps import ANDROIDWORLD_APPS, VLC_ALTERNATE_CANDIDATE, AndroidWorldApkSource
from .installer import (
    DownloadError,
    DownloadedApk,
    InstallError,
    InstallResult,
    InspectedApk,
    MetadataError,
    download_apks,
    inspect_apk,
    install_locked_apk,
    render_lock,
    verify_locked_apk,
)


load_v1_manifest = load_manifest
build_v1_plan = build_seed_plan
apply_v1_seed = apply_seed
verify_v1_seed = verify_seed


__all__ = [
    "DEFAULT_MANIFEST", "AdbClient", "DeviceGuardError", "DeviceIdentity",
    "ManifestError", "SeedContext", "SeedManifest", "StageResult",
    "apply_seed", "apply_v1_seed", "build_seed_plan", "build_v1_plan",
    "canonical_manifest_digest", "load_manifest", "load_snapshot",
    "load_v1_manifest", "main", "preflight_device", "save_snapshot",
    "verify_seed", "verify_v1_seed",
    "ApkLockEntry", "AppSeedStatus", "AppsLock", "AssetLockEntry", "AssetsLock",
    "CertificateIsolation", "SeedCertificate", "SharedSeedStatus", "TraversalSeedDataset",
    "TraversalSeedObject", "TraversalSeedProfile", "canonical_digest", "certificate_ready",
    "load_apps_lock", "load_assets_lock", "load_v2_manifest",
    "ANDROIDWORLD_APPS", "VLC_ALTERNATE_CANDIDATE", "AndroidWorldApkSource",
    "DownloadError", "DownloadedApk", "InstallError", "InstallResult", "InspectedApk",
    "MetadataError", "download_apks", "inspect_apk", "install_locked_apk", "render_lock",
    "verify_locked_apk",
]
