"""Explicit, visually reviewed extraction from coarse Regions in a ledger copy."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .contracts import ReportCorrections, ReportCorrectionExhausted
from .ledger import ExplorationLedger
from .models import Region, RegionOccurrence, RegionVariant
from .region_review import _review_operation_identity_candidates



REVIEW_SCHEMA = {
    'type': 'object', 'properties': {
        'approved': {'type': 'boolean'}, 'reason': {'type': 'string'},
        'shared_operations': {'type': 'array', 'items': {
            'type': 'object', 'properties': {
                'current_operation_ref': {'type': 'string'},
                'known_operation_ref': {'type': 'string'},
            }, 'required': ['current_operation_ref', 'known_operation_ref'], 'additionalProperties': False,
        }},
    }, 'required': ['approved', 'reason', 'shared_operations'], 'additionalProperties': False,
}

REVIEW_PROMPT = """你是既有Region视觉审核角色，本次审核显式旧分区修正，而非新GUI动作。
图1是当前完整截图；每个source的image是该来源State实际保存的完整截图，不能把旧控件当当前可点击。
核对每个source中selected的具体控件是否共同形成一个独立功能组件，原source是否过粗且其余内容应保留。
多个source必须提取同一功能组件的不同State实例；不同主体、不同功能对象不能因名称/图标/位置相似而合并。
修正只改变图中的包含归属，不表示界面实际变化、控件出现/消失或产生新因果边。
全部来源有充分证据才approved=true；来源缺控件、仅同类而不同组件、随意截取部分成员或证据不足则false。
父区保留为容器，不把父子合并。操作配对只提候选：current_operation_ref来自第二个及后续source，
known_operation_ref来自第一个source的已选控件；动作、对象、直接效果一致才提议，不按名称自动配对。
每个current最多一对，未配对的功能保留独立。共享仅identity，不复制成功结果；既有Operation审核角色将另行复核候选。
approved=false时shared_operations=[]，reason具体说明依据。"""


def validate_proposal(ledger: ExplorationLedger, proposal: Mapping[str, Any], current_state_id: str):
    if not isinstance(proposal, Mapping) or any(not isinstance(proposal.get(k), str) or not proposal[k].strip() for k in ('name', 'summary', 'reason')):
        raise ValueError('region_refinement requires name, summary and evidence reason')
    if any(a.outcome == 'pending' for a in ledger.attempts.values()):
        raise ValueError('region_refinement requires all pending actions settled first')
    sources = proposal.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('region_refinement.sources must be nonempty')
    selected, states, records = set(), set(), []
    for source in sources:
        if not isinstance(source, Mapping):
            raise ValueError('region_refinement source must be an object')
        occurrence = ledger.occurrences.get(source.get('occurrence_ref'))
        refs = source.get('element_refs')
        if occurrence is None or not isinstance(refs, list) or not refs:
            raise ValueError('region_refinement requires known occurrence and nonempty element_refs')
        if occurrence.state_id in states:
            raise ValueError('region_refinement selects one source occurrence per State')
        states.add(occurrence.state_id)
        for ref in refs:
            element = ledger.elements.get(ref) if isinstance(ref, str) else None
            if (ref in selected or element is None or element.variant_id != occurrence.variant_id
                    or element.source_occurrence_ids != [occurrence.occurrence_id]):
                raise ValueError(f'region_refinement invalid or duplicate Element {ref}; use source-local concrete refs')
            selected.add(ref)
        remaining = set(ledger.region_variants[occurrence.variant_id].element_ids) - set(refs)
        if not remaining and not any(o.scope == 'region' for o in ledger.variant_operations(occurrence.variant_id)) and not any(o.parent_occurrence_id == occurrence.occurrence_id for o in ledger.occurrences.values()):
            raise ValueError('region_refinement extracts a subcomponent; whole-Region reuse uses existing identity review')
        records.append(occurrence)
    if current_state_id not in states:
        raise ValueError('region_refinement must include the confirmed current State')
    moved = {o.operation_id for o in ledger.operations.values() if o.element_id in selected}
    for oid in moved:
        op = ledger.operations[oid]
        identity = ledger.canonical_operations[op.canonical_operation_id]
        if not set(identity.operation_ids) <= moved:
            raise ValueError(f'region_refinement must include all existing shared bindings for {identity.canonical_operation_id}')
        if op.source_occurrence_ids != ledger.elements[op.element_id].source_occurrence_ids:
            raise ValueError(f'region_refinement operation {oid} has unresolved source ownership')
    return records, moved


def refinement_context(ledger: ExplorationLedger, task: Any) -> dict:
    """Current owners and, only for a stranded focus, its historical source."""
    state_ids = {ledger.current_state_id}
    if task is not None and task.operation_id:
        from .status import current_operation_binding
        from .tasks import task_source_states
        if current_operation_binding(ledger, task.operation_id) is None:
            state_ids.update(task_source_states(ledger, task))
    return {'sources': [
        {'occurrence_ref': occ.occurrence_id, 'state_ref': occ.state_id,
         'region_ref': occ.region_id, 'name': occ.name,
         'historical': occ.state_id != ledger.current_state_id,
         'elements': ([{'element_ref': e.element_id, 'name': e.name}
                       for e in ledger.elements.values() if e.variant_id == occ.variant_id]
                      if occ.state_id != ledger.current_state_id else []),
         'current_elements_in_existing_inventory': occ.state_id == ledger.current_state_id}
        for sid in sorted(state_ids) for occ in ledger.state_occurrences(sid)
    ], 'instruction': '只有新证据说明旧分区过粗才提交region_refinement：明确来源occurrence和要摘出的具体element refs。历史目录不证明当前可交互。该工具不执行GUI、不新增覆盖；不得用重复分区修正绕过预算。'}


def refine_regions(ledger: ExplorationLedger, proposal: Mapping[str, Any], *, agent: Any,
                   current_state_id: str, screenshot: bytes, screenshot_ref: str,
                   read_screenshot: Callable[[str], bytes], corrections: ReportCorrections) -> ExplorationLedger:
    records, moved = validate_proposal(ledger, proposal, current_state_id)
    frames = [screenshot]
    rows = []
    for source, occ in zip(proposal['sources'], records):
        frame_ref = ledger.states[occ.state_id].screenshot_ref
        frame = screenshot if occ.state_id == current_state_id else read_screenshot(frame_ref)
        if not frame:
            raise ValueError(f'region_refinement missing source screenshot: {frame_ref}')
        if frame not in frames:
            frames.append(frame)
        label = f'图{frames.index(frame) + 1}'
        elements = [e for e in ledger.elements.values() if e.variant_id == occ.variant_id]
        operations = [o for o in ledger.variant_operations(occ.variant_id) if o.element_id in source['element_refs']]
        rows.append({'occurrence_ref': occ.occurrence_id, 'region_ref': occ.region_id,
                     'page': ledger.pages[ledger.states[occ.state_id].page_id].name,
                     'state': ledger.states[occ.state_id].name, 'state_ref': occ.state_id,
                     'image': label, 'screenshot_ref': screenshot_ref if occ.state_id == current_state_id else frame_ref,
                     'elements': [{'element_ref': e.element_id, 'name': e.name, 'selected': e.element_id in source['element_refs']} for e in elements],
                     'operations': [{'operation_ref': o.operation_id, 'element': ledger.elements[o.element_id].name,
                                     'source_state': ledger.states[occ.state_id].name,
                                     'source_page': ledger.pages[ledger.states[occ.state_id].page_id].name,
                                     'target': o.target, 'action': o.action, 'scope': o.scope, 'direction': o.direction,
                                     'images': [label], 'visible_in_candidate_state': True} for o in operations]})
    payload = {'proposal': dict(proposal), 'sources': rows}
    reviewer = getattr(agent, 'review_region_refinement', None)
    if not callable(reviewer):
        raise ValueError('region_refinement reviewer unavailable; graph unchanged')
    result = None
    while corrections.count < corrections.limit:
        try:
            result = reviewer(payload=payload, screenshots=frames)
            if not isinstance(result, Mapping) or not isinstance(result.get('approved'), bool) or not str(result.get('reason') or '').strip() or not isinstance(result.get('shared_operations'), list):
                raise ValueError('region_refinement review requires approved, reason, shared_operations')
            known = {o['operation_ref'] for o in rows[0]['operations']}
            current = moved - known
            seen, targets, identity_targets = set(), set(), {}
            for pair in result['shared_operations']:
                cid, kid = pair['current_operation_ref'], pair['known_operation_ref']
                if cid not in current or kid not in known or cid in seen:
                    raise ValueError('region_refinement review contains unknown/duplicate operation pair')
                a, b = ledger.operations[cid], ledger.operations[kid]
                prior_target = identity_targets.setdefault(a.canonical_operation_id, b.canonical_operation_id)
                if prior_target != b.canonical_operation_id:
                    raise ValueError('region_refinement pair contradicts an already shared operation identity')
                target = (a.variant_id, b.canonical_operation_id)
                if target in targets:
                    raise ValueError('region_refinement duplicate pair collapses distinct owners in one source Variant')
                targets.add(target)
                if (a.scope, a.action, a.direction) != (b.scope, b.action, b.direction):
                    raise ValueError('region_refinement paired actions/scopes/directions differ')
                if any(ledger.canonical_operations[o.canonical_operation_id].representative_operation_ids for o in (a, b)):
                    raise ValueError('region_refinement pair must preserve explicit representative experiments; leave unpaired')
                seen.add(cid)
            if not result['approved'] and result['shared_operations']:
                raise ValueError('region_refinement refused review cannot share operations')
            break
        except (KeyError, TypeError, ValueError) as exc:
            if not corrections.reject(exc, 'region_reviewer'):
                raise ReportCorrectionExhausted(str(exc)) from exc
            payload['correction'] = str(exc)
    if result is None:
        raise ReportCorrectionExhausted('region_refinement correction budget exhausted')
    if not result['approved']:
        raise ValueError('region_refinement not approved: ' + result['reason'])

    staged = ledger.clone()
    pairs = _review_operation_identity_candidates(
        staged, agent, result={'decisions': [{'decision': 'reuse', 'shared_operations': [dict(p, reuse_level='identity') for p in result['shared_operations']]}]},
        payload={'current_regions': rows[1:], 'known_region_candidates': rows[:1]},
        screenshots=frames, state_id=current_state_id, corrections=corrections) or {}
    region = Region(staged.mint('region'), proposal['name'], proposal['summary'], memory=proposal['summary'])
    staged.regions[region.region_id] = region
    mapping = []
    for source, old in zip(proposal['sources'], records):
        variant = RegionVariant(staged.mint('region_variant'), region.region_id)
        staged.region_variants[variant.variant_id] = variant
        occurrence = RegionOccurrence(staged.mint('occurrence'), region.region_id, old.state_id,
                                      region.name, region.summary, variant.variant_id, old.occurrence_id)
        staged.occurrences[occurrence.occurrence_id] = occurrence
        staged.states[old.state_id].region_occurrence_ids.append(occurrence.occurrence_id)
        for eid in source['element_refs']:
            e = staged.elements[eid]
            e.region_id, e.variant_id = region.region_id, variant.variant_id
            e.source_occurrence_ids = [occurrence.occurrence_id]
            for oid in e.operation_ids:
                o = staged.operations[oid]
                o.region_id, o.variant_id = region.region_id, variant.variant_id
                o.source_occurrence_ids = [occurrence.occurrence_id]
                staged.canonical_operations[o.canonical_operation_id].region_id = region.region_id
        mapping.append({'source_occurrence_ref': old.occurrence_id, 'target_occurrence_ref': occurrence.occurrence_id,
                        'element_refs': list(source['element_refs'])})
    staged._rebuild_derived_indexes()
    for current, known in pairs:
        a, b = staged.operations[current], staged.operations[known]
        old_co, new_co = a.canonical_operation_id, b.canonical_operation_id
        if old_co == new_co:
            continue
        for op in staged.operations.values():
            if op.canonical_operation_id == old_co:
                op.canonical_operation_id = new_co
        staged.canonical_operations.pop(old_co)
    staged._rebuild_derived_indexes()
    staged.coalesce_operation_tasks()
    staged.validate_region_parentage()
    staged.event('region_refinement_applied', proposal=dict(proposal), region_ref=region.region_id,
                 mapping=mapping, operation_pairs=[list(p) for p in pairs], reason=result['reason'],
                 evidence=[{'state_ref': r['state_ref'], 'screenshot_ref': r['screenshot_ref']} for r in rows],
                 gui_action=False, historical_effects_unchanged=True)
    return staged
