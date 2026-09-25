"""Canonical semantic page and functional-variant identity."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import unicodedata
from typing import Any, Dict, Mapping, Optional

from .matching import _GENERIC_BUTTONS
from ..stateful import normalize_state_key

# ── Volatile-text filter (2026-07-14 用户) ────────────────────────────────────
# 页面身份签名的第二道闸: 剔除【每次访问都在变】的 display 文字 —— 时间/日期/百分比/
# 纯数字/IP/倒计时。这类值进签名会让同一页随时间产生不同签名。
# 但【稳定状态文字】("Bluetooth Turned Off"/"No Thunderbolt support")必须留——稀疏页
# 全靠它区分(见 signature_names 上方注释)。故只砍"会变的", 不砍"不变的": 用确定性正则
# (文档 §5.2 的最小子集), 不需要 VLM 新字段, 不需要跨帧账本。GUIWALK_VOLATILE_FILTER=0 回退。
_VOLATILE_TIME = re.compile(
    r"\b\d{1,2}[:：]\d{2}(?:[:：]\d{2})?\s*(?:[ap]\.?m\.?|上午|下午|早上|晚上|凌晨)?\b",
    re.IGNORECASE)
_VOLATILE_DATE = re.compile(
    r"\b(?:\d{4}[-/年]\s*)?\d{1,2}[-/月]\s*\d{1,2}\s*日?\b")
_VOLATILE_NUM = re.compile(r"[-+]?\d[\d,.]*\s*(?:%|％|kb|mb|gb|tb|kib|mib|gib)?", re.I)
_VOLATILE_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_VOLATILE_CAL = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day|s|nes|rs|ur)?\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    r"|[ap]\.?m\.?|周[一二三四五六日天]|星期[一二三四五六日天]"
    r"|上午|下午|早上|晚上|凌晨", re.IGNORECASE)


def _is_volatile_text(name: str) -> bool:
    """True if ``name`` is a value that changes every visit (not page identity).

    Strips known volatile spans (time/date/number/percent/IP/weekday); if what
    remains has < 2 alphabetic (incl. CJK) characters, the token was essentially
    just a dynamic value and must NOT enter the identity signature. A label like
    ``5 alarms`` keeps enough letters to survive, so real page content is safe.
    """
    if os.environ.get("GUIWALK_VOLATILE_FILTER", "1") == "0":
        return False
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    if not text:
        return False
    for pat in (_VOLATILE_IP, _VOLATILE_TIME, _VOLATILE_DATE,
                _VOLATILE_CAL, _VOLATILE_NUM):
        text = pat.sub(" ", text)
    residue = [c for c in text if c.isalpha() or unicodedata.category(c).startswith("Lo")]
    return len(residue) < 2


def canonical_page_name(page_name: str) -> str:
    """Return a stable semantic key for one page responsibility.

    Page identity deliberately ignores variant facts such as an empty/non-empty
    list or a feature gate's current value.  It keeps meaningful digits, so
    distinct responsibilities such as ``IPv4`` and ``IPv6`` do not collapse.
    Callers whose visible title contains instance data should pass a stable
    semantic key to :func:`compute_page_id` (for example ``alarm_detail``).
    """
    text = unicodedata.normalize("NFKC", str(page_name or "")).casefold()
    text = re.sub(r"[_\W]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def compute_page_id(
    page_name: str,
    *,
    semantic_key: str = "",
    namespace: str = "",
) -> str:
    """Compute a stable page id from semantic responsibility, never state facts.

    ``semantic_key`` is the explicit parameterisation hook for homogeneous detail
    instances whose visible titles contain object data.  Graphs are app-scoped,
    but ``namespace`` can be supplied by callers that need globally-qualified ids.
    """
    key = canonical_page_name(semantic_key or page_name) or "unknown"
    scope = canonical_page_name(namespace)
    raw = f"{scope}|{key}" if scope else key
    return "p" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:15]


def semantic_page_key(page_name: str, elements=None) -> str:
    """Combine the page label with stable primary-navigation context.

    State values, list instances and inner tabs stay variant evidence.  A
    selected primary/sidebar destination, however, disambiguates applications
    whose VLM repeatedly emits the generic title ``Settings`` for every panel.
    """
    base = canonical_page_name(page_name) or "unknown"
    primary = set()
    for element in elements or ():
        if isinstance(element, str):
            continue
        category = canonical_page_name(_element_field(element, "category", ""))
        region = canonical_page_name(_element_field(element, "region", ""))
        group = canonical_page_name(_element_field(element, "group", ""))
        selected = bool(_element_field(element, "selected", False))
        name = canonical_page_name(_element_field(element, "name", ""))
        if (
            selected and not group and category == "navigation" and name
            and region in {
                "nav sidebar", "sidebar", "primary navigation", "navigation",
                "bottom navigation", "bottom nav",
            }
        ):
            primary.add(name)
    if not primary:
        return base
    return base + " / " + " / ".join(sorted(primary))


def _element_field(element: Any, name: str, default: Any = None) -> Any:
    if isinstance(element, Mapping):
        return element.get(name, default)
    return getattr(element, name, default)


def _canonical_fact_value(value: Any) -> Any:
    """Convert caller facts into deterministic, JSON-safe identity material."""
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_fact_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_canonical_fact_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, str):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return " ".join(str(value).casefold().split())


def observed_variant_facts(
    elements,
    extra_facts: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract functional facts that distinguish variants of one semantic page.

    Dynamic display values are intentionally excluded.  Repeated data rows fold
    to group-presence, while available functions, selected navigation modes,
    structured state values and access gates remain.  Consequently two alarm
    detail instances with the same controls share a variant, while materially
    different available functions or state values remain distinct variants.

    ``elements`` may contain VisualElement-like objects, mappings, or the string
    tokens produced by :func:`signature_names`.
    """
    functions = set()
    groups = set()
    selected = set()
    states: Dict[str, str] = {}
    availability: Dict[str, str] = {}

    for element in elements or ():
        if isinstance(element, str):
            token = " ".join(element.strip().casefold().split())
            if not token:
                continue
            if token.startswith("selected:"):
                selected.add(token[len("selected:"):].strip())
            elif token.startswith("state:") and "=" in token:
                key, value = token[len("state:"):].split("=", 1)
                if key.strip() and value.strip():
                    states[key.strip()] = value.strip()
            elif token.startswith("grp:"):
                group = token[len("grp:"):].strip()
                if group:
                    groups.add(group)
            elif (token not in _GENERIC_BUTTONS and len(token) >= 2
                    and not _is_volatile_text(token)):
                functions.add(token)
            continue

        name = " ".join(str(_element_field(element, "name", "") or "")
                        .strip().casefold().split())
        category = " ".join(str(_element_field(element, "category", "") or "")
                            .strip().casefold().split())
        group = " ".join(str(_element_field(element, "group", "") or "")
                         .strip().casefold().split())
        if group:
            groups.add(group)
        elif (name and category != "display" and name not in _GENERIC_BUTTONS
                and not _is_volatile_text(name)):
            functions.add(name)

        if (name and bool(_element_field(element, "selected", False))
                and category == "navigation"):
            selected.add(name)

        state_key = " ".join(str(_element_field(element, "state_key", "") or "")
                             .strip().casefold().split())
        state_value = " ".join(str(_element_field(element, "state_value", "") or "")
                               .strip().casefold().split())
        effect_scope = " ".join(str(
            _element_field(element, "effect_scope", "") or "")
            .replace("_", " ").strip().casefold().split())
        if (bool(_element_field(element, "stateful", False))
                and effect_scope == "function set"
                and state_key
                and state_value in {"off", "on", "mixed", "unknown"}):
            states[state_key] = state_value

        blocked_reason = " ".join(str(
            _element_field(element, "blocked_reason", "") or "")
            .strip().casefold().split())
        enabled = _element_field(element, "enabled", None)
        requires_permission = bool(
            _element_field(element, "requires_permission", False))
        if name and (enabled is False or requires_permission or blocked_reason):
            availability[name] = (
                blocked_reason
                or ("permission_required" if requires_permission else "disabled")
            )

    facts: Dict[str, Any] = {
        "functions": sorted(functions),
        "groups": sorted(groups),
        "selected": sorted(selected),
        "states": dict(sorted(states.items())),
        "availability": dict(sorted(availability.items())),
    }
    if extra_facts:
        facts["observed"] = _canonical_fact_value(extra_facts)
    return facts


def variant_signature(facts: Mapping[str, Any]) -> str:
    """Return the canonical, human-inspectable signature for variant facts."""
    return json.dumps(
        _canonical_fact_value(dict(facts or {})),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_variant_signature(facts: Mapping[str, Any]) -> str:
    """Compatibility spelling for :func:`variant_signature`."""
    return variant_signature(facts)


def compute_variant_id(page_id: str, facts: Mapping[str, Any]) -> str:
    """Compute a stable variant id scoped to one semantic page."""
    raw = f"{str(page_id or '')}|{variant_signature(facts)}"
    return "v" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:15]


def _merge_observed_variant_facts(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> Dict[str, Any]:
    """Accumulate a richer observation of the same execution state.

    Initial registration may only see the top viewport; scroll aggregation then
    supplies the complete function set.  Missing facts in that preliminary frame
    are not evidence that a function disappeared.  True functional changes must
    receive a different execution state id, so enrichment is monotonic here.
    """
    merged = copy.deepcopy(dict(previous or {}))
    for key in ("functions", "groups", "selected"):
        values = set(merged.get(key) or [])
        values.update(current.get(key) or [])
        merged[key] = sorted(values)
    for key in ("states", "availability", "observed"):
        prior = merged.get(key)
        incoming = current.get(key)
        if isinstance(prior, Mapping) or isinstance(incoming, Mapping):
            values = dict(prior or {})
            values.update(copy.deepcopy(dict(incoming or {})))
            if values or key in current or key in merged:
                merged[key] = values
        elif incoming is not None:
            merged[key] = copy.deepcopy(incoming)
    for key, value in current.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
    return merged


def signature_names(elements) -> list:
    """页面身份签名的名单 —— 把「内容重复单元(group)」折叠掉 (§1+§7).

    身份是页面**骨架**, 不是**内容**. 一组 group 成员(应用列表项 / 帖子 / 商品 /
    下拉展开的候选值)是"内容 / 控件展开的临时项": 列表滚动、数据刷新、换一批数据
    都会让逐项名变 —— 逐项进签名 => 同一页分裂成多个 state(长列表 D18 分裂、Default
    Apps 下拉展开拆 4 节点都是它). 折叠规则:
      * 非 group 元素(骨架: 导航项/标题/字段/当前值)   -> 保留原名;
      * group 成员 -> 每个 group 只折成一个 ``grp:<group>`` token(算"有这么一组",
        不看里面此刻是哪几项).
    于是"有哪些功能区 / 有几种列表"决定身份,"列表里此刻是哪几条数据"不再决定身份.
    ``elements`` 为 VisualElement(有 ``.name`` / ``.group``). 仅供**身份**用;
    覆盖账本另存全名(见 VisualStateRegistry.set_buttons)."""
    out = []
    seen_groups = set()
    for e in (elements or []):
        if isinstance(e, str):               # back-compat: a bare skeleton name
            n = e.strip()
            if n:
                out.append(n)
            continue
        # A selected NAVIGATION item changes which functional surface is active
        # even when the surrounding list/region skeleton is identical (Settings
        # Applications: Accerciser vs Calendar; tabbed editors; sidebars).  Keep
        # this mode token even when the row belongs to a folded list group.  Data
        # selections such as a wallpaper thumbnail are intentionally excluded:
        # their value changes, but the page's available function set does not.
        n = (getattr(e, "name", "") or "").strip()
        if (n and getattr(e, "selected", False)
                and (getattr(e, "category", "") or "").strip().lower()
                == "navigation"):
            out.append("selected:" + n)
        # Functional-surface state is part of node identity.  Two values of a
        # feature gate can share the same page/regions/control labels while
        # exposing different reachable functions.  Value-only widget
        # changes deliberately do not enter identity and therefore cannot create a
        # Cartesian product of ordinary preferences.
        if (getattr(e, "stateful", False)
                and (getattr(e, "effect_scope", "") or "").strip().lower()
                == "function_set"):
            state_key = normalize_state_key(getattr(e, "state_key", ""))
            state_value = (getattr(e, "state_value", "") or "").strip().lower()
            if state_key and state_value in {"off", "on", "mixed", "unknown"}:
                out.append(f"state:{state_key}={state_value}")
        enabled = getattr(e, "enabled", None)
        requires_permission = bool(getattr(e, "requires_permission", False))
        blocked_reason = " ".join(str(
            getattr(e, "blocked_reason", "") or "")
            .strip().lower().split())
        if n and (enabled is not None or requires_permission or blocked_reason):
            if enabled is False or requires_permission or blocked_reason:
                status = "blocked:" + (
                    blocked_reason
                    or ("permission required" if requires_permission else "disabled"))
            else:
                status = "available"
            out.append(f"availability:{n.strip().lower()}={status}")
        g = (getattr(e, "group", "") or "").strip().lower()
        if g:
            if g not in seen_groups:
                seen_groups.add(g)
                out.append("grp:" + g)
        else:
            n = (getattr(e, "name", "") or "").strip()
            # [2026-07-14 用户] 会变的 display 值(时间/日期/数字)不进身份签名, 否则同一页
            # 会随时间分裂。稳定状态文字仍留(稀疏页区分靠它). 选中导航项、
            # 状态/可用性 token 上面已单独收过, 这里只管普通名字的 else 分支。
            if n and not _is_volatile_text(n):
                out.append(n)
    return out
