from __future__ import annotations

import re

from .contracts import SeedCertificate
from .locks import canonical_digest, validate_apps_lock_records, validate_assets_lock_records
from .manifest_v2 import ADAPTER_IDS


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z")
_SHARED_DOMAINS = frozenset({"contacts", "sms", "calendar", "call_logs", "clock", "files_media"})


def certificate_ready(certificate: SeedCertificate) -> bool:
    if not isinstance(certificate, SeedCertificate):
        return False
    if certificate.profile is None or certificate.apps_lock is None or certificate.assets_lock is None:
        return False
    if not validate_apps_lock_records(certificate.apps_lock) or not validate_assets_lock_records(certificate.assets_lock):
        return False
    if tuple(entry.adapter_id for entry in certificate.apps_lock.entries) != ADAPTER_IDS:
        return False
    if any(not entry.asset_id or not entry.device_path or not _SHA256.fullmatch(entry.sha256) or entry.size_bytes <= 0 for entry in certificate.assets_lock.entries):
        return False
    if certificate.profile.release_id != certificate.release_id or certificate.apps_lock.release_id != certificate.release_id or certificate.assets_lock.release_id != certificate.release_id:
        return False
    if (canonical_digest(certificate.profile), canonical_digest(certificate.apps_lock), canonical_digest(certificate.assets_lock)) != (certificate.manifest_digest, certificate.apps_lock_digest, certificate.assets_lock_digest):
        return False
    if certificate.release_id != "guitraverse_mobile_seed_v2" or certificate.snapshot_name != "guitraverse_mobile_seed_v2":
        return False
    if not certificate.code_commit or not certificate.generator_provenance or not _TIME.fullmatch(certificate.valid_until):
        return False
    if not all(_SHA256.fullmatch(value) for value in (certificate.manifest_digest, certificate.apps_lock_digest, certificate.assets_lock_digest)):
        return False
    app_ids = tuple(status.adapter_id for status in certificate.app_statuses)
    if app_ids != ADAPTER_IDS:
        return False
    if any(not all((status.installed, status.setup, status.data, status.gui)) or not _evidence(status.evidence) or status.partial_reason for status in certificate.app_statuses):
        return False
    domains = tuple(status.domain for status in certificate.shared_statuses)
    if len(domains) != len(set(domains)) or set(domains) != _SHARED_DOMAINS:
        return False
    if any(not status.passed or not _evidence(status.evidence) or status.reason for status in certificate.shared_statuses):
        return False
    if not certificate.snapshot_saved or certificate.snapshot_name not in certificate.snapshot_list:
        return False
    if not certificate.isolation.run_a_passed or not certificate.isolation.run_b_passed or not _evidence(certificate.isolation.evidence):
        return False
    return not certificate.known_gaps


def _evidence(values: tuple[str, ...]) -> bool:
    return bool(values) and all(isinstance(value, str) and value.strip() for value in values)
