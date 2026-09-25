"""Per-run content-addressed caches for the visual-traversal VLM roles.

Priority-4: per-action cost (~85s) is itself a coverage limiter — the budget
drains before the frontier does. Perception naming and
PageIdentityJudge.same_page were re-invoked with no caching, and Page Identity
alone was ~38% of all VLM calls (355/921 in one run), fired up to 6x
back-to-back against the wrong candidates during a single register.

Two cache strengths are deliberately separated:
  * semantic-only naming uses a tight pHash bucket;
  * geometry-bearing grounding and region results require exact screenshot MD5;
  * the pair role (same_page) keys on the ORDERED pair of pHashes.

Grounding stores the raw response, not mutable ``VisualElement`` instances, so
each hit reconstructs fresh objects. Reviewer-driven force refresh bypasses the
cache and promotes only the reviewed winner.

These are small per-app-run LRUs; the engine clears them between app runs so a
stale verdict from a different app can never leak.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class PersistentVLMResponseCache:
    """Optional exact-request cache for replaying raw VLM responses.

    The cache is deliberately stricter than the per-run pHash LRUs below.  A
    hit requires the exact prompt, exact image pixels, model identity, and
    response-affecting generation settings.  Prompt edits therefore invalidate
    old replies automatically.  Files contain hashes plus the raw response;
    screenshot bytes and prompt text are never copied into the cache.
    """

    SCHEMA = "gui_rewalk.vlm_response_cache.v1"

    def __init__(self, root: Optional[str] = None):
        self.root = os.path.abspath(root) if root else None

    @staticmethod
    def _image_hash(image: Any) -> str:
        digest = hashlib.sha256()
        if isinstance(image, (bytes, bytearray, memoryview)):
            digest.update(b"bytes\0")
            digest.update(bytes(image))
            return digest.hexdigest()
        shape = tuple(int(value) for value in getattr(image, "shape", ()) or ())
        dtype = str(getattr(image, "dtype", type(image).__name__))
        digest.update(json.dumps(
            {"shape": shape, "dtype": dtype},
            ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8"))
        digest.update(b"\0")
        tobytes = getattr(image, "tobytes", None)
        if callable(tobytes):
            digest.update(tobytes())
        else:
            digest.update(repr(image).encode("utf-8"))
        return digest.hexdigest()

    def request(self, role: str, agent, prompt: str, images) -> tuple[str, Dict[str, Any]]:
        prompt_hash = hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()
        metadata = {
            "schema": self.SCHEMA,
            "role": str(role),
            "agent_class": (
                f"{agent.__class__.__module__}.{agent.__class__.__qualname__}"
            ),
            "model": getattr(agent, "model", None),
            "model_version": getattr(agent, "model_version", None),
            "max_tokens": getattr(agent, "max_tokens", None),
            "top_p": getattr(agent, "top_p", None),
            "temperature": getattr(agent, "temperature", None),
            "enable_thinking": bool(getattr(agent, "enable_thinking", False)),
            "prompt_sha256": prompt_hash,
            "image_sha256": [self._image_hash(image) for image in (images or [])],
        }
        canonical = json.dumps(
            metadata, ensure_ascii=True, sort_keys=True,
            separators=(",", ":"), default=str,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest(), metadata

    def _path(self, key: str) -> Optional[str]:
        if not self.root:
            return None
        return os.path.join(self.root, key[:2], f"{key}.json")

    def get(self, key: str) -> Optional[str]:
        path = self._path(key)
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if (payload.get("schema") != self.SCHEMA
                    or payload.get("request_key") != key
                    or not isinstance(payload.get("response"), str)):
                return None
            return payload["response"]
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None

    def put(self, key: str, metadata: Dict[str, Any], response: str) -> None:
        path = self._path(key)
        if not path or not isinstance(response, str):
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = dict(metadata)
            payload.update({
                "request_key": key,
                "response": response,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
            temporary = f"{path}.{os.getpid()}.tmp"
            with open(temporary, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
        except OSError as exc:
            logger.warning("persistent VLM response cache write skipped: %s", exc)


class VLMCallLedger:
    """Per-run accounting for semantic VLM roles.

    ``calls`` counts logical ``predict_mm`` invocations; ``attempts`` uses the
    transport wrapper's returned retry counter when available.  Cache hits are
    recorded separately, so an optimisation can be evaluated without scraping
    generic HTTP logs.  The ledger is observational only: it returns the exact
    value produced by ``agent.predict_mm`` and never changes fallback semantics.
    """

    def __init__(self, output_path: Optional[str] = None,
                 response_cache_dir: Optional[str] = None):
        self.output_path = output_path
        self._roles: Dict[str, Dict[str, Any]] = {}
        self.response_cache = PersistentVLMResponseCache(response_cache_dir)

    def _role(self, role: str) -> Dict[str, Any]:
        return self._roles.setdefault(str(role), {
            "calls": 0,
            "attempts": 0,
            "cache_hits": 0,
            "persistent_cache_hits": 0,
            "errors": 0,
            "latency_seconds": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        })

    def predict(self, role: str, agent, prompt: str, images,
                max_attempts: Optional[int] = None,
                timeout_seconds: Optional[float] = None,
                use_response_cache: bool = True):
        rec = self._role(role)
        rec["calls"] += 1
        started = time.monotonic()
        cache_key = None
        cache_metadata = None
        if self.response_cache.root and use_response_cache:
            try:
                cache_key, cache_metadata = self.response_cache.request(
                    role, agent, prompt, images)
                cached_response = self.response_cache.get(cache_key)
                if cached_response is not None:
                    rec["cache_hits"] += 1
                    rec["persistent_cache_hits"] += 1
                    rec["latency_seconds"] += time.monotonic() - started
                    return cached_response, 0, 0, 0
            except Exception as exc:
                logger.warning("persistent VLM response cache lookup skipped: %s", exc)
        try:
            if max_attempts is not None and hasattr(agent, "predict_mm_with_policy"):
                result = agent.predict_mm_with_policy(
                    prompt, images, max_attempts=max_attempts,
                    timeout_seconds=timeout_seconds)
            else:
                result = agent.predict_mm(prompt, images)
        except Exception:
            rec["errors"] += 1
            raise
        finally:
            rec["latency_seconds"] += time.monotonic() - started
        try:
            response = result[0]
            prompt_tokens = result[1] if len(result) > 1 else 0
            completion_tokens = result[2] if len(result) > 2 else 0
            attempts = result[3] if len(result) > 3 else 1
            rec["prompt_tokens"] += int(prompt_tokens or 0)
            rec["completion_tokens"] += int(completion_tokens or 0)
            # GUIGenAgent returns max_retry+1 after exhausting its loop; cap the
            # accounting value to the configured transport budget.
            max_retry = int(
                max_attempts
                if max_attempts is not None
                else (getattr(agent, "max_retry", attempts or 1) or 1)
            )
            rec["attempts"] += min(max_retry, max(1, int(attempts or 1)))
            if str(response or "").strip().lower() == "error calling llm":
                rec["errors"] += 1
            elif cache_key and cache_metadata and isinstance(response, str):
                self.response_cache.put(cache_key, cache_metadata, response)
        except Exception:
            rec["attempts"] += 1
        return result

    def cache_hit(self, role: str) -> None:
        self._role(role)["cache_hits"] += 1

    def snapshot(self) -> Dict[str, Any]:
        roles = {name: dict(values) for name, values in sorted(self._roles.items())}
        return {
            "logical_calls": sum(v["calls"] for v in roles.values()),
            "transport_attempts": sum(v["attempts"] for v in roles.values()),
            "cache_hits": sum(v["cache_hits"] for v in roles.values()),
            "persistent_cache_hits": sum(
                v["persistent_cache_hits"] for v in roles.values()),
            "errors": sum(v["errors"] for v in roles.values()),
            "latency_seconds": round(
                sum(v["latency_seconds"] for v in roles.values()), 3),
            "prompt_tokens": sum(v["prompt_tokens"] for v in roles.values()),
            "completion_tokens": sum(v["completion_tokens"] for v in roles.values()),
            "roles": roles,
        }

    def save(self) -> None:
        if not self.output_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
        tmp = self.output_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.snapshot(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.output_path)


def predict_mm_role(agent, role: str, prompt: str, images, ledger=None,
                    max_attempts: Optional[int] = None,
                    timeout_seconds: Optional[float] = None,
                    use_response_cache: bool = True):
    """Call ``predict_mm`` with optional role-owned transport budget."""
    if ledger is not None:
        return ledger.predict(
            role, agent, prompt, images, max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            use_response_cache=use_response_cache)
    if max_attempts is not None and hasattr(agent, "predict_mm_with_policy"):
        return agent.predict_mm_with_policy(
            prompt, images, max_attempts=max_attempts,
            timeout_seconds=timeout_seconds)
    return agent.predict_mm(prompt, images)

# pHash Hamming distance within which two frames of the SAME page are treated as
# one cache bucket. Live data jitter on a single page — a battery %, the clock, a
# changing value, a blinking cursor — perturbs only a few of the 64 pHash bits, so
# an EXACT-pHash key forced a fresh VLM call on every such micro-change (the
# measured 10% hit rate). Bucketing within a few bits reuses the cached verdict
# across that jitter while staying FAR tighter than the genuinely-different-page
# distance (sibling pages measure >=16-20 apart), so two different screens cannot
# collide. Reuses the engine's VIEW_STABLE_DISTANCE (4):
# it is the same "this is the same view" tolerance the settle/scroll loops use, so
# the bucket is exactly "frames the engine already considers the same view".
PHASH_BUCKET_DISTANCE = 4


def frame_phash(shot: bytes) -> Optional[str]:
    """pHash hex of a PNG frame, or None on any decode error."""
    if not shot:
        return None
    try:
        import imagehash
        from PIL import Image
        return str(imagehash.phash(Image.open(io.BytesIO(shot)).convert("RGB")))
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("frame_phash failed: %s", e)
        return None


def _hamming_hex(a: str, b: str) -> Optional[int]:
    """Hamming distance between two equal-length pHash HEX strings, or None when
    they are not comparable (different length / non-hex). Pure int math — no
    imagehash import on the hot path."""
    if a is None or b is None or len(a) != len(b):
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


class LRU:
    """Tiny bounded LRU (key -> value).

    Keys may be plain pHash hex strings (single-frame roles) or tuples of them
    (the ordered same_page pair). When ``bucket`` > 0 a lookup additionally
    accepts the NEAREST stored key whose pHash Hamming distance is within
    ``bucket`` (per hex component for tuple keys) — so a same-page frame that
    differs only by live-data jitter (battery/clock/value) reuses the cached VLM
    result instead of missing on an exact-string mismatch. Non-string keys fall
    back to exact equality. The bucket is a few bits only, so genuinely different
    pages (distance >> bucket) never collide.
    """

    def __init__(self, capacity: int = 512, bucket: int = 0):
        self.capacity = capacity
        self.bucket = bucket
        self._d: "OrderedDict[Any, Any]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _within(a, b, bucket: int) -> bool:
        """True iff key ``a`` matches key ``b`` within ``bucket`` pHash bits.

        Handles a bare hex string and an ordered tuple of hex strings (same_page).
        Every hex component must individually be within ``bucket`` — a tuple key
        matches only when BOTH frames of the pair are the same-page-jitter of the
        stored pair, so the candidate↔current orientation cannot be confused."""
        if isinstance(a, tuple) and isinstance(b, tuple):
            if len(a) != len(b):
                return False
            for xa, xb in zip(a, b):
                d = _hamming_hex(xa, xb) if isinstance(xa, str) and isinstance(xb, str) else None
                if d is None or d > bucket:
                    return False
            return True
        if isinstance(a, str) and isinstance(b, str):
            d = _hamming_hex(a, b)
            return d is not None and d <= bucket
        return False

    def get(self, key, default=None):
        if key in self._d:
            self._d.move_to_end(key)
            self.hits += 1
            return self._d[key]
        if self.bucket > 0:
            # nearest stored key within the bucket (most-recent-first so the
            # freshest same-page verdict wins on a tie).
            for k in reversed(self._d):
                if self._within(key, k, self.bucket):
                    self._d.move_to_end(k)
                    self.hits += 1
                    return self._d[k]
        self.misses += 1
        return default

    def put(self, key, value) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self.capacity:
            self._d.popitem(last=False)

    def __contains__(self, key) -> bool:
        return key in self._d

    def clear(self) -> None:
        self._d.clear()
        self.hits = 0
        self.misses = 0


class VLMRoleCache:
    """Shared, per-run cache for the visual VLM roles, keyed by frame pHash.

    One instance is created per engine and shared with the agents.
    ``detect_and_name`` results are keyed by a single frame's pHash. Page
    identity uses the ordered pair of exact screenshot hashes so a perceptual
    near-match never reuses an earlier identity decision.
    """

    def __init__(self, capacity: int = 512,
                 bucket: int = PHASH_BUCKET_DISTANCE, ledger=None):
        # Identity choices are reusable only for the exact ordered screenshot
        # pair. A perceptual near-match must be judged again by the VLM.
        self.same_page = LRU(capacity, bucket=0)
        self.page_relationship = LRU(capacity, bucket=0)
        self.naming = LRU(capacity, bucket=bucket)
        # Geometry-bearing results require an EXACT frame.  A 1-bit pHash-near
        # frame may have a changed selected tab or shifted bbox, so no bucketing.
        self.grounding = LRU(capacity, bucket=0)
        self.regions = LRU(capacity, bucket=0)
        self.ledger = ledger

    def clear(self) -> None:
        self.same_page.clear()
        self.page_relationship.clear()
        self.naming.clear()
        self.grounding.clear()
        self.regions.clear()

    @staticmethod
    def _exact_key(shot: bytes) -> Optional[str]:
        return hashlib.md5(shot).hexdigest() if shot else None

    def _hit(self, role: str) -> None:
        if self.ledger is not None:
            self.ledger.cache_hit(role)

    # ── exact-frame grounding / regions ───────────────────────────────
    def lookup_grounding(self, shot: bytes):
        key = self._exact_key(shot)
        if key is None:
            return False, None
        marker = object()
        value = self.grounding.get(key, marker)
        if value is marker:
            return False, None
        self._hit("grounding")
        return True, value

    def put_grounding(self, shot: bytes, raw_response: str) -> None:
        key = self._exact_key(shot)
        if key is not None:
            self.grounding.put(key, raw_response)

    def lookup_regions(self, shot: bytes, element_signature=None):
        key = self._exact_key(shot)
        if key is None:
            return False, None
        if element_signature is not None:
            key = (key, element_signature)
        marker = object()
        value = self.regions.get(key, marker)
        if value is marker:
            return False, None
        self._hit("legacy_region_cache")
        return True, copy.deepcopy(value)

    def put_regions(self, shot: bytes, regions, element_signature=None) -> None:
        key = self._exact_key(shot)
        if key is not None:
            if element_signature is not None:
                key = (key, element_signature)
            self.regions.put(key, copy.deepcopy(regions))

    def lookup_naming(self, shot: bytes):
        ph = frame_phash(shot)
        if ph is None:
            return False, None
        marker = object()
        value = self.naming.get(ph, marker)
        if value is marker:
            return False, None
        self._hit("perception_naming")
        return True, value

    def put_naming(self, shot: bytes, value) -> None:
        ph = frame_phash(shot)
        if ph is not None:
            self.naming.put(ph, value)

    # ── same_page ───────────────────────────────────────────────────────
    def get_same_page(self, cand: bytes, cur: bytes,
                      compute: Callable[[], bool]) -> bool:
        a, b = self._exact_key(cand), self._exact_key(cur)
        if a is None or b is None:
            return compute()
        key = (a, b)
        cached = self.same_page.get(key, None)
        if cached is not None:
            self._hit("page_identity")
            return bool(cached)
        v = bool(compute())
        self.same_page.put(key, v)
        return v

    def get_same_page_result(self, cand: bytes, cur: bytes,
                             compute: Callable[[], Any]):
        """Cache only resolved page-identity comparisons.

        ``None`` means the judge was unavailable or returned an invalid
        contract.  It must not be cached as ``False`` because that would turn a
        transient model failure into durable evidence that two pages differ.
        """
        a, b = self._exact_key(cand), self._exact_key(cur)
        if a is None or b is None:
            return compute()
        key = (a, b)
        marker = object()
        cached = self.same_page.get(key, marker)
        if cached is not marker:
            self._hit("page_identity")
            return bool(cached)
        value = compute()
        if value is not None:
            self.same_page.put(key, bool(value))
        return value

    def get_page_relationship_result(
        self, cand: bytes, cur: bytes, compute: Callable[[], Any],
    ):
        """Cache one resolved three-way page relationship by exact frame pair."""
        a, b = self._exact_key(cand), self._exact_key(cur)
        if a is None or b is None:
            return compute()
        key = (a, b)
        marker = object()
        cached = self.page_relationship.get(key, marker)
        if cached is not marker:
            self._hit("page_identity")
            return cached
        value = compute()
        if value is not None:
            self.page_relationship.put(key, value)
        return value
