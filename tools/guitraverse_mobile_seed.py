"""Manifest-driven synthetic seed and whole-AVD snapshot utility.

This is out-of-band environment setup.  It never creates exploration Attempts,
graph edges, Capabilities, or instruction trajectory records.
"""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.guitraverse_seed import (
    DEFAULT_MANIFEST,
    AdbClient,
    DeviceGuardError,
    DeviceIdentity,
    ManifestError,
    SeedManifest,
    apply_seed,
    build_seed_plan,
    canonical_manifest_digest,
    load_manifest,
    load_snapshot,
    main,
    preflight_device,
    save_snapshot,
    verify_seed,
)
from tools.guitraverse_seed.shared_v1 import (
    _apply_contacts,
    _apply_system,
    _local_assets,
)


__all__ = [
    "DEFAULT_MANIFEST", "AdbClient", "DeviceGuardError", "DeviceIdentity",
    "ManifestError", "SeedManifest", "apply_seed", "build_seed_plan",
    "canonical_manifest_digest", "load_manifest", "load_snapshot", "main",
    "preflight_device", "save_snapshot", "verify_seed",
]


if __name__ == "__main__":
    raise SystemExit(main())
