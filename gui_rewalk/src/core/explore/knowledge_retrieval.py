"""Local graph/lexical evidence retrieval; no identity decisions or model calls."""
from __future__ import annotations

from collections import Counter
import json
import math
import re
from typing import Any

MAX_STATES = 8
MAX_GLOBAL_MATCHES = 2
MAX_KNOWLEDGE_BYTES = 24_000
MAX_DYNAMIC_BYTES = 96_000


class ContextBudgetExceeded(ValueError):
    """Do not send an oversized context or silently cut protected evidence."""


def json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def check_dynamic_budget(prompt: str) -> None:
    size = len(prompt.encode('utf-8'))
    if size > MAX_DYNAMIC_BYTES:
        raise ContextBudgetExceeded(f'dynamic context {size} UTF-8 bytes exceeds {MAX_DYNAMIC_BYTES}; no model call, protected current/pending evidence not truncated')


def terms(text: str) -> list[str]:
    result = re.findall(r'[a-z0-9_]+', text.casefold())
    for span in re.findall(r'[\u3400-\u9fff]+', text):
        result.extend(span)
        result.extend(span[i:i + 2] for i in range(len(span) - 1))
    return result


def lexical_states(ledger, query: str, *, landing: bool = False) -> dict[str, tuple[float, str]]:
    """BM25 over derived Region-occurrence cards, aggregated by best State hit."""
    query_terms = set(terms(query))
    if not query_terms:
        return {}
    incoming = {}
    if landing:
        for edge in ledger.transitions:
            text = str(edge.action.get('target') or '') + ' ' + edge.visible_result
            rows = incoming.setdefault(edge.target_state_id, [])
            if text not in rows:
                rows.append(text)
                del rows[:-4]
    documents = []
    for state in ledger.states.values():
        occurrences = ledger.state_occurrences(state.state_id)
        for occurrence in occurrences or [None]:
            heading = state.name
            body = state.summary + ' ' + ' '.join(incoming.get(state.state_id, []))
            if occurrence is not None:
                heading += ' ' + occurrence.name
                body += ' ' + occurrence.summary
                for op in ([] if landing else ledger.occurrence_operations(occurrence.occurrence_id)):
                    element = ledger.elements.get(op.element_id)
                    body += ' ' + (element.name if element else '') + ' ' + op.target + ' ' + op.parameter_summary
            tokens = Counter(terms((heading + ' ') * 3 + body))
            documents.append((state.state_id, occurrence.occurrence_id if occurrence else '', tokens, sum(tokens.values())))
    ranked = {}
    for sid, oid, score in score_documents(documents, query_terms):
        if score > ranked.get(sid, (0.0, ''))[0]:
            ranked[sid] = (score, oid)
    return ranked


def score_documents(documents, query_terms):
    df = Counter(term for _, _, tokens, _ in documents for term in query_terms if term in tokens)
    average = sum(length for _, _, _, length in documents) / max(1, len(documents)) or 1
    scores = []
    for key, ref, tokens, length in documents:
        score = 0.0
        for term in query_terms & tokens.keys():
            frequency = tokens[term]
            idf = math.log(1 + (len(documents) - df[term] + .5) / (df[term] + .5))
            score += idf * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * length / average))
        if score > 0:
            scores.append((key, ref, score))
    return sorted(scores, key=lambda row: row[2], reverse=True)


def query_text(query) -> str:
    return ' '.join(str(query.get(k) or '') for k in ('label', 'function', 'region')) if isinstance(query, dict) else str(query or '')


def retrieve_controls(ledger, query, limit: int = 4) -> list[dict]:
    """Rank concrete operation cards, deduplicating only confirmed canonical IDs."""
    spec = query if isinstance(query, dict) else {}
    text_query = query_text(query)
    query_terms = set(terms(text_query))
    if not query_terms and not (spec.get('state_ref') or spec.get('region_ref') or spec.get('label')):
        return []
    names_by_identity, region_names = {}, {}
    for region in ledger.regions.values():
        region_names[region.region_id] = {region.name}
    for occurrence in ledger.occurrences.values():
        region_names.setdefault(occurrence.region_id, set()).add(occurrence.name)
    for event in ledger.events:
        if event['kind'] == 'region_name_observed':
            payload = event['payload']
            region_names.setdefault(payload['region_ref'], set()).update(
                (payload.get('previous_name', ''), payload.get('reported_name', '')))
    for op in ledger.operations.values():
        element = ledger.elements.get(op.element_id)
        if element is None:
            continue
        names = names_by_identity.setdefault(op.canonical_operation_id, [])
        for name in [element.name, *(o.get('reported_name', '') for o in element.observations)]:
            if name and name not in names:
                names.append(name)
    documents, sources = [], {}
    for op in ledger.operations.values():
        if spec.get('action') and op.action != spec['action']:
            continue
        if spec.get('region_ref') and op.region_id != spec['region_ref']:
            continue
        occurrence = next((ledger.occurrences[r] for r in op.source_occurrence_ids if r in ledger.occurrences
                           and (not spec.get('state_ref') or ledger.occurrences[r].state_id == spec['state_ref'])), None)
        if occurrence is None:
            continue
        element = ledger.elements.get(op.element_id)
        name = element.name if element is not None else occurrence.name
        parent = ledger.occurrences.get(occurrence.parent_occurrence_id)
        aliases = names_by_identity.get(op.canonical_operation_id, [name])
        text = ((name + ' ') * 3 + ' '.join(aliases) + ' ' + op.target + ' ' + ' '.join(sorted(region_names[op.region_id])) + ' '
                + (parent.name if parent else '') + ' ' + op.parameter_summary + ' ' + op.result)
        tokens = Counter(terms(text))
        documents.append((op.operation_id, occurrence.occurrence_id, tokens, sum(tokens.values())))
        sources[op.operation_id] = (occurrence, name)
    normalized_query = ' '.join(text_query.casefold().split())

    def matching_name(oid):
        op = ledger.operations[oid]
        for name in names_by_identity.get(op.canonical_operation_id, [sources[oid][1]]):
            label = ' '.join(name.casefold().split())
            if spec.get('label'):
                requested = set(terms(spec['label']))
                matched = requested <= set(terms(label)) if requested else label == spec['label'].casefold().strip()
            else:
                matched = bool(label and re.search(r'(?<![a-z0-9_])' + re.escape(label) + r'(?![a-z0-9_])', normalized_query))
            if matched:
                return name
        return ''

    def region_match(oid):
        requested = set(terms(spec.get('region', '')))
        occurrence = sources[oid][0]
        parent = ledger.occurrences.get(occurrence.parent_occurrence_id)
        available = set(terms(' '.join(sorted(region_names[occurrence.region_id])) + ' ' + (parent.name if parent else '')))
        return len(requested & available) / len(requested) if requested else 0

    scored = score_documents(documents, query_terms) if query_terms else [
        (a, b, 0) for a, b, _, _ in documents if not spec.get('label') or matching_name(a)]
    ranked = sorted(scored, key=lambda row: (bool(matching_name(row[0])), region_match(row[0]), row[2]), reverse=True)
    cards, seen = [], set()
    for oid, _, score in ranked:
        op = ledger.operations[oid]
        if op.canonical_operation_id in seen:
            continue
        occurrence, name = sources[oid]
        state = ledger.states[occurrence.state_id]
        targets = list(dict.fromkeys(e.target_state_id for e in reversed(ledger.transitions)
                                     if e.action.get('operation_ref') == oid))[:2]
        card = {'element_ref': op.element_id, 'local_operation_ref': oid,
                'operation_ref': op.canonical_operation_id, 'region_ref': op.region_id,
                'variant_ref': op.variant_id, 'occurrence_ref': occurrence.occurrence_id,
                'state_ref': state.state_id, 'page_ref': state.page_id,
                'name': name, 'matched_name': matching_name(oid) or name,
                'region_name': occurrence.name, 'action': op.action, 'scope': op.scope,
                'function': op.target, 'parameter_status': op.parameter_status,
                'parameter_summary': op.parameter_summary, 'observed_result': op.result,
                'known_target_state_refs': targets, 'screenshot_ref': state.screenshot_ref,
                'historical': True}
        from .partition_review import qualification_gaps
        gap = qualification_gaps(ledger).get(oid)
        if gap:
            card.update(qualification='unconfirmed', executable=False, qualification_evidence=gap['evidence'])
        if json_bytes(cards + [card]) > 8000:
            continue
        cards.append(card); seen.add(op.canonical_operation_id)
        if len(cards) >= limit:
            break
    return cards


def state_card(ledger, sid: str) -> dict:
    state = ledger.states[sid]
    return {'state_ref': sid, 'page_ref': state.page_id, 'page_name': ledger.pages[state.page_id].name,
            'state_name': state.name, 'state_summary': state.summary, 'survey_complete': state.survey_complete,
            'known_regions': [{'region_ref': o.region_id, 'name': o.name,
                               'parent_region_ref': ledger.occurrences[o.parent_occurrence_id].region_id if o.parent_occurrence_id else ''}
                              for o in ledger.state_occurrences(sid)],
            'screenshot_ref': state.screenshot_ref}


def retrieve_knowledge(ledger, task, pending, task_view, *, query='', needs_route: bool, rediscovering: bool) -> dict:
    explicit_query = bool(query)
    spec = query if isinstance(query, dict) else {}
    query = query_text(query)
    if not query and pending is not None and pending.action.get('kind') != 'back':
        owner = ledger.elements.get(str(pending.action.get('owner_ref') or ''))
        query = owner.name if owner is not None else str(pending.action.get('target') or '')
    if not query and pending is None and task is not None:
        op = ledger.operations.get(task.operation_id)
        query = op.target if op is not None else ''
    query = query[:200]
    ranked = lexical_states(ledger, query, landing=pending is not None and not explicit_query)
    control_query = spec or query
    if pending is not None and query and not explicit_query:
        # The before-action Region/type cannot constrain the unknown after-frame.
        # Only an explicit query supplies structural scope/action filters.
        control_query += ' ' + str(pending.action.get('target') or '')
    controls = retrieve_controls(ledger, control_query)
    origin = pending.source_state_id if pending is not None else ledger.current_state_id
    required = []

    def require(sid):
        if sid in ledger.states and sid not in required:
            required.append(sid)

    require(origin)
    if spec.get('state_ref'):
        require(spec['state_ref'])
    if task is not None:
        require(task.state_id)
    incoming = next((e for e in reversed(ledger.transitions) if e.target_state_id == origin), None)
    if incoming is not None:
        require(incoming.source_state_id)
    # Actual recent movement supplies return context that label retrieval cannot.
    recent_states = {origin}
    for attempt in reversed(ledger.attempts.values()):
        if attempt.outcome != 'success':
            continue
        for sid in (attempt.target_state_id, attempt.source_state_id):
            if sid not in recent_states and len(recent_states) < 3:
                recent_states.add(sid); require(sid)
        if len(recent_states) >= 3:
            break
    if pending is not None and pending.action.get('kind') == 'back' and origin in ledger.states:
        page = ledger.states[origin].page_id
        entry = next((a for a in reversed(ledger.attempts.values())
                      if a.outcome == 'success' and a.target_state_id in ledger.states
                      and a.source_state_id in ledger.states
                      and ledger.states[a.target_state_id].page_id == page
                      and ledger.states[a.source_state_id].page_id != page), None)
        if entry is not None:
            require(entry.source_state_id)
            parent = next((e for e in reversed(ledger.transitions)
                           if e.target_state_id == entry.source_state_id), None)
            if parent is not None:
                require(parent.source_state_id)
    if rediscovering:
        last = next(reversed(ledger.attempts.values()), None)
        if last is not None:
            require(last.target_state_id or last.source_state_id)
        recent = next((e['payload'].get('state_id') for e in reversed(ledger.events)
                       if e['payload'].get('state_id') in ledger.states), '')
        require(recent)
        # Resume clears the live location, not the historical retrieval anchor.
        # This does not bind the current State or create an observed transition.
        if not origin:
            origin = recent or (last.target_state_id or last.source_state_id if last is not None else '')
    steps = (task_view.get('region_route') or {}).get('steps', [])
    if steps:
        require(steps[0].get('expected_target_state_ref'))
    component_states = {origin}
    for occurrence in ledger.state_occurrences(origin):
        component_states.update(o.state_id for o in ledger.occurrences.values()
                                if o.region_id == occurrence.region_id)
    neighbours, recency = set(component_states), {}
    for i, edge in enumerate(ledger.transitions):
        if edge.source_state_id in component_states or edge.target_state_id in component_states:
            neighbours.update((edge.source_state_id, edge.target_state_id))
            recency[edge.source_state_id] = recency[edge.target_state_id] = i
    # Known outcomes for the actual pending local Operation are strong candidates,
    # not asserted current landings or shared-Variant result reuse.
    observed_targets = []
    if pending is not None and pending.action.get('operation_ref'):
        for edge in reversed(ledger.transitions):
            if edge.action.get('operation_ref') == pending.action['operation_ref'] and edge.target_state_id not in observed_targets:
                observed_targets.append(edge.target_state_id)
    state_order = {sid: i for i, sid in enumerate(ledger.states)}
    local = list(dict.fromkeys([sid for sid in observed_targets if sid not in required] + sorted(neighbours - set(required),
                  key=lambda sid: (ranked.get(sid, (0, ''))[0], recency.get(sid, -1), state_order.get(sid, -1)), reverse=True)))
    control_states = list(dict.fromkeys(sid for card in controls
                         for sid in [*card['known_target_state_refs'], card['state_ref']]))
    global_hits = [sid for sid in dict.fromkeys(control_states + sorted(ranked, key=lambda sid: ranked[sid][0], reverse=True))
                   if sid not in neighbours and sid not in required][:MAX_GLOBAL_MATCHES]
    ordered = required + (global_hits + local if explicit_query else local[:max(0, MAX_STATES - len(required) - len(global_hits))] + global_hits)
    cards, selected = [], []
    for sid in dict.fromkeys(ordered):
        if sid not in ledger.states or len(cards) >= MAX_STATES:
            continue
        card = state_card(ledger, sid)
        if json_bytes(cards + [card]) > MAX_KNOWLEDGE_BYTES - 3000 - json_bytes(controls):
            if sid in required:
                raise ContextBudgetExceeded('required historical State evidence exceeds retrieval byte budget; no silent truncation')
            continue
        cards.append(card)
        selected.append(sid)
    route_refs = {s.get('evidence_transition_ref') for s in steps}
    edges = [e for e in ledger.transitions if e.transition_id in route_refs]
    if needs_route:
        for e in reversed(ledger.transitions):
            if len(edges) >= max(8, len(route_refs)):
                break
            if e not in edges and e.source_state_id in selected and e.target_state_id in selected:
                edges.append(e)
    elif pending is not None:
        edges = [incoming] if incoming is not None else []
    else:
        edges = []
    result = {'states': cards, 'controls': controls,
              'connections': [{'from': e.source_state_id, 'to': e.target_state_id,
                               'action': e.action.get('target') or e.action.get('kind')} for e in edges],
              'retrieval': {'scope': 'source_neighbors_and_lexical', 'query': spec or query,
                            'global_matches': [s for s in global_hits if s in selected],
                            'selected_state_refs': selected, 'total_states': len(ledger.states),
                            'max_states': MAX_STATES, 'max_bytes': MAX_KNOWLEDGE_BYTES},
              'instruction': 'controls是历史控件/操作候选，附Region、State和证据；states辅助定位。'
                             '仅提供来源及邻居、任务必需来源和少量本地文字检索候选，不发送全局索引。'
                             '候选均是历史证据，不证明当前可见、同一身份或可直接执行。没有匹配不证明是新页面；'
                             '可用context_query描述当前可见的功能/控件补查，再依据截图判断。完整路由仍由任务卡提供。'}
    if json_bytes(result) > MAX_KNOWLEDGE_BYTES:
        raise ContextBudgetExceeded('retrieved knowledge exceeds byte budget; preserve evidence instead of truncating it')
    return result
