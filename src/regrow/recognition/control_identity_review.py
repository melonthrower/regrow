from regrow.records.snapshots import load as _record_load
'Review proposed new identities and unsupported reuse before publication.\n\nRaw local pixel candidates only select a question. Luna decides identity using\noriginal scenes; neither matching nor this module merges historical records.\n'
from regrow.records.object_store import owned_controls
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from regrow.recognition import identity_templates as identity_templates
from regrow.recognition import matching as image_match

class Conflict(ValueError):
    blocked_by = 'binding_conflict'

    def __init__(self, pair):
        self.control_identity_pair = pair
        purpose = '本帧旧身份引用尚无外观对应，需根据原场景确认' if pair.get('kind') == 'reuse' else '新建控件与本区块唯一历史候选冲突，需要核对当前场景与历史记录'
        super().__init__(purpose + '：' + pair['current_name'] + ' / ' + pair['old_name'])

class CandidateConflict(ValueError):
    blocked_by = 'binding_conflict'

    def __init__(self, candidates):
        self.control_identity_candidates = candidates
        super().__init__('同一当前对象与本区块多个历史身份相似；先按场景选择一个候选，再核对该对象的历史记录，不能按外观强行新建或合并')

def box(value):
    if not isinstance(value, dict):
        return None
    keys = ('left', 'top', 'right', 'bottom')
    if any((type(value.get(k)) is not int for k in keys)):
        return None
    return [value[k] for k in keys]

def same_position(a, b):
    if not a or not b:
        return False
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return union > 0 and overlap / union >= 0.8

def owner(records, request, proposal):
    if not proposal.get('ref') or proposal.get('identity') in ('new', 'uncertain'):
        return None
    labels = request.get('discovery_context', {}).get('region_names', request.get('region_names', {}))
    rid = labels.get(proposal['ref'], proposal['ref'])
    if rid in records:
        return rid if not records[rid].get('behavior_context') or proposal.get('context_matches') is True else None
    matches = [rid for (rid, r) in records.items() if r['name'] == proposal['ref']]
    if len(matches) != 1:
        return None
    rid = matches[0]
    return rid if not records[rid].get('behavior_context') or proposal.get('context_matches') is True else None

def candidate_groups(controls, hits):
    """Separate one current position/multiple histories from repeated positions."""
    associations = {i: [cid for (cid, hit) in hits.items() if any((same_position(box(c.get('bbox')), h['box']) for h in hit.get('candidates', [])))] for (i, c) in controls}
    for (i, c) in controls:
        if c.get('ref') or c.get('identity') == 'uncertain':
            continue
        ids = associations[i]
        if not ids:
            continue
        if any((not hits[cid].get('accepted') or hits[cid].get('candidates_truncated') or len(hits[cid].get('candidates', [])) != 1 or (sum((cid in row for row in associations.values())) != 1) for cid in ids)):
            continue
        yield (i, ids)

def candidates(records, snapshot, frame, request, reply):
    from PIL import Image
    import numpy as np
    if not frame or not Path(frame).is_file():
        return
    with Image.open(frame) as im:
        pixels = np.asarray(im.convert('RGB'))
    for (ri, region) in enumerate(reply.get('regions', [])):
        rid = owner(records, request, region)
        area = [0, 0, pixels.shape[1], pixels.shape[0]]
        if rid is None or region.get('identity') == 'uncertain':
            continue
        (l, t, r, b) = area
        if not (0 <= l < r <= pixels.shape[1] and 0 <= t < b <= pixels.shape[0]):
            continue
        controls = [(i, c) for (i, c) in enumerate(reply.get('controls', [])) if c.get('region_index') == ri]
        if not any((not c.get('ref') and c.get('identity') != 'uncertain' for (_, c) in controls)):
            continue
        hits = {}
        observations = {}
        for (cid, old) in owned_controls(records[rid]).items():
            observed = identity_templates.latest(old)
            if not observed:
                continue
            path = (snapshot / observed['image']).resolve()
            try:
                with Image.open(path) as im:
                    template = np.asarray(im.convert('RGB'))
            except (OSError, FileNotFoundError):
                continue
            hit = image_match._search(template, pixels[t:b, l:r])
            for h in hit.get('candidates', []):
                h['box'] = [v + (l if k % 2 == 0 else t) for (k, v) in enumerate(h['box'])]
            hits[cid] = hit
            observations[cid] = observed
        for (ci, ids) in candidate_groups(controls, hits):
            group = []
            for cid in ids:
                c = reply['controls'][ci]
                old = owned_controls(records[rid])[cid]
                observed = observations[cid]
                source = observed.get('source_image')
                old_box = box(observed.get('bbox'))
                if not source or not old_box:
                    continue
                source = (snapshot / source).resolve()
                if not source.is_file():
                    continue
                labels = request.get('discovery_context', {}).get('control_names', {})
                if any((other.get('ref') and (labels.get(other['ref']) == cid or other['ref'] == cid) for (_, other) in controls)):
                    continue
                label = cid
                if any((ref != cid and name == label for (name, ref) in labels.items())):
                    continue
                pair = {'region': rid, 'control': cid, 'region_index': ri, 'control_index': ci, 'region_name': region['name'], 'region_ref': region['ref'], 'old_name': old['name'], 'ref': label, 'current_name': c.get('name', c.get('text', '')), 'current_box': box(c.get('bbox')), 'historical_box': old_box, 'historical_frame': str(source), 'current_frame': str(Path(frame).resolve()), 'historical_evidence': deepcopy(observed.get('evidence', {})), 'historical_description': observed.get('description', observed.get('icon_description', '')), 'snapshot': str(snapshot.resolve()), 'current_image': 1}
                identity = {k: pair[k] for k in ('region', 'control', 'current_box', 'historical_box', 'historical_frame', 'current_frame', 'snapshot')}
                pair['key'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode() + source.read_bytes() + Path(frame).read_bytes()).hexdigest()
                from regrow.records import control_history_context as control_history_context
                pair['context'] = control_history_context.comparison(records, rid, cid)
                group.append(pair)
            if len(group) == len(ids):
                yield group

def reused_candidates(records, snapshot, frame, request, reply):
    """A missing pixel match asks a semantic question; it never rejects reuse."""
    from PIL import Image
    import numpy as np
    if not frame or not Path(frame).is_file():
        return
    with Image.open(frame) as im:
        pixels = np.asarray(im.convert('RGB'))
    labels = request.get('discovery_context', {}).get('control_names', {})
    for (ci, row) in enumerate(reply.get('controls', [])):
        from regrow.records.object_knowledge import control_only
        if control_only(row):
            continue
        ref = row.get('ref')
        if not ref:
            continue
        cid = labels.get(ref, ref)
        matches = [(rid, old) for (rid, region) in records.items() for (key, old) in owned_controls(region).items() if key == cid]
        if not matches:
            continue
        ri = row.get('region_index')
        proposed = owner(records, request, reply['regions'][ri]) if isinstance(ri, int) and 0 <= ri < len(reply.get('regions', [])) else None
        rid, old = next(((r, c) for r, c in matches if r == proposed), matches[0])
        if ri is None:
            indices = [i for (i, region) in enumerate(reply.get('regions', [])) if owner(records, request, region) == rid]
            if len(indices) != 1:
                continue
            ri = indices[0]
        if not 0 <= ri < len(reply.get('regions', [])):
            continue
        region = reply['regions'][ri]
        observed = identity_templates.latest(old)
        if not observed or not observed.get('source_image') or (not box(observed.get('bbox'))):
            continue
        source = (snapshot / observed['source_image']).resolve()
        template = (snapshot / observed['image']).resolve()
        if not source.is_file() or not template.is_file():
            continue
        appearances = [{**row, 'image': str((snapshot / row['image']).resolve())}
                       for row in identity_templates.variants(old)]
        hit = image_match.match_appearances(appearances, lambda path: image_match.locate(path, frame))
        if hit.get('accepted'):
            continue
        pair = {'kind': 'reuse', 'region': rid, 'control': cid, 'region_index': ri, 'control_index': ci, 'region_name': records[rid]['name'], 'region_ref': region.get('ref'), 'old_name': old['name'], 'ref': cid, 'submitted_ref': ref, 'current_name': row.get('name', old['name']), 'current_box': box(row.get('bbox')), 'historical_box': box(observed['bbox']), 'historical_frame': str(source), 'current_frame': str(Path(frame).resolve()), 'historical_evidence': deepcopy(observed.get('evidence', {})), 'historical_description': observed.get('icon_description', ''), 'snapshot': str(snapshot.resolve()), 'current_image': 1}
        pair['current_candidates'] = [list(p['box']) for p in hit.get('candidates', []) if p.get('box')]
        pair['region_description'] = records[rid].get('description', '')
        identity = {k: pair[k] for k in ('kind', 'region', 'control', 'current_box', 'historical_frame', 'current_frame', 'snapshot')}
        pair['key'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode() + source.read_bytes() + Path(frame).read_bytes()).hexdigest()
        from regrow.records import control_history_context as control_history_context
        pair['context'] = control_history_context.comparison(records, rid, cid)
        yield pair

def check(records, snapshot, frame, request, reply):
    # Discovery and normal action updates already ask Luna to associate objects.
    # Their registration paths still validate IDs, ownership and materialization;
    # absence of a pixel match is not a second mandatory identity decision.
    if (request.get('role') == 'observation' and request.get('discovery_context')
            or request.get('role') == 'observation_update'):
        return
    reviewed = {r['key']: r for r in request.get('control_identity_reviews', [])}
    for pair in reused_candidates(records, snapshot, frame, request, reply):
        if reviewed.get(pair['key'], {}).get('decision') == 'same':
            continue
        if reviewed.get(pair['key'], {}).get('decision') == 'different':
            raise ValueError('该旧控件引用已被否定；修正对象登记及关联知识，不重复提交同一复用引用')
        raise Conflict(pair)
    for group in candidates(records, snapshot, frame, request, reply):
        if len(group) > 1:
            raise CandidateConflict(group)
        pair = group[0]
        if reviewed.get(pair['key'], {}).get('decision') == 'different':
            continue
        raise Conflict(pair)

def check_request(run, request, reply):
    """Publication callers invoke this after their idempotent-return boundary."""
    (snapshot, records, _) = _record_load(run)
    from regrow.prompts.frame_context import primary
    chosen = primary(request)
    frame = Path(run) / chosen if chosen else None
    check(records, snapshot, frame, request, reply)

def review_material(job, original, pairs, *, candidate=None):
    """Select facts for identity questions, without ordinary repair permissions."""
    from regrow.prompts.prompt_material import body
    from regrow.prompts.prompt_material import execution
    from regrow.prompts.prompt_material import update_task
    materials = body(original)[0]
    update_task(materials)
    if '来源区块已有任务' in materials:
        ref = materials.get('当前任务引用')
        materials['来源区块已有任务'] = [row for row in materials['来源区块已有任务'] if ref and row.get('task') == ref]
    value = {'原工作': deepcopy(original.get('work_context', {})), '原任务与实际操作': {k: deepcopy(v) for (k, v) in materials.items() if k in ('本轮探索任务', '当前任务', '任务目标', '实际来源区块', '实际入口', '实际动作', '回执', '动作前对象观察', '准备动作说明', '当前任务引用', '来源区块已有任务', '任务与实际对象核对', '动作请求来源上下文', '来源身份说明', '控件关联待核对', '登记说明')}, '核对原因': job.get('error'), '此前修复': deepcopy(job.get('history', [])), '补充观察': deepcopy(job.get('supplements', []))}
    execution(value['原任务与实际操作'])
    for slot in ('任务目标', '当前任务'):
        card = value['原任务与实际操作'].get(slot)
        if isinstance(card, dict):
            card.pop('历史分段说明', None)
            extra = card.get('任务补充')
            if isinstance(extra, dict):
                extra.pop('历史分段说明', None)
                if not extra:
                    card.pop('任务补充')
    history = original.get('page_context', {}).get('history', {}).get('events', {})
    identities = {(pair['region'], pair['control']) for pair in pairs}
    value['直接相关历史'] = {aid: deepcopy(row) for (aid, row) in history.items() if (row.get('region'), row.get('control')) in identities or aid == job.get('attempt')}
    owners = {pair['region'] for pair in pairs}
    value['区块状态的已接受依据'] = {aid: deepcopy(row) for aid, row in history.items()
                               if row.get('region') in owners and row.get('已有身份核对')
                               and aid not in value['直接相关历史']}
    candidate = candidate if candidate is not None else job.get('candidate') or {}
    if candidate.get('controls'):
        value['单图步骤待登记的候选观察'] = deepcopy(candidate['controls'][pairs[0]['control_index']])
    return value

def recorded_history(pair):
    """Use the same frozen identity evidence in selection and comparison."""
    snapshot = pair.get('snapshot')
    if snapshot and (Path(snapshot) / 'runtime_state.json').is_file():
        from regrow.traversal import discovery_step as discovery_step
        from regrow.records import control_history_context as control_history_context
        (_, records, _) = _record_load(Path(snapshot), snapshot=Path(snapshot).resolve())
        return control_history_context.comparison(records, pair['region'], pair['control'])
    return deepcopy(pair['context'])

def selection_request(root, job, request):
    """Choose one identity from its original task, scene and candidate history."""
    group = deepcopy(job['control_identity_candidates'])
    for pair in group:
        pair['current_image'] = 1
        pair['context'] = recorded_history(pair)
    q = request
    q['identity_candidate'] = deepcopy(job.get('candidate'))
    if len({pair['current_frame'] for pair in group}) != 1:
        raise ValueError('同一当前对象的候选必须来自同一原场景')
    from regrow.prompts.frame_context import select
    select(q, group[0]['current_frame'],
           '原动作后图（身份候选选择）' if job['stage'] == 'update' else '原发现图（身份候选选择）')
    q['control_identity_candidates'] = deepcopy(group)
    q.update(role='control_identity_selection', stage='control_identity_selection')
    from regrow.prompts.prompt_material import identity_needs
    identity_needs(q, group, job.get('attempt'))
    path = '纠错/控件身份候选选择.prompt'
    part = {'path': path, 'text': (Path(root) / 'regrow/prompts' / path).read_text()}
    q['fixed_parts'] = [part]
    q['system_prompt'] = part['text']
    q['response_schema'] = {'type': 'object', 'additionalProperties': False, 'properties': {'candidate': {'type': ['string', 'null'], 'enum': [p['ref'] for p in group] + [None]}, 'reason': {'type': 'string', 'minLength': 1}}, 'required': ['candidate', 'reason']}
    dynamic = review_material(job, q['original_request'], group, candidate=q['identity_candidate'])
    dynamic['本次目的'] = '为同一当前对象选择一个有依据的历史候选；本步不修提案或记录。'
    dynamic['本区块同一当前对象的历史候选'] = {'区块': group[0]['region_name'], '当前对象': group[0]['current_name'], '当前图': group[0]['current_image'], '当前身份框': group[0]['current_box'], '候选': [{'candidate': p['ref'], '历史上下文': p['context']} for p in group]}
    q['user_prompt'] = q['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    return q

def selected_pair(request, reply):
    import jsonschema
    jsonschema.validate(reply, request['response_schema'])
    if not reply['reason'].strip():
        raise ValueError('候选选择须说明当前场景依据')
    if reply['candidate'] is None:
        return None
    selected = [p for p in request['control_identity_candidates'] if p['ref'] == reply['candidate']]
    if len(selected) != 1:
        raise ValueError('候选选择没有唯一对应本次本区块历史控件')
    return {**deepcopy(selected[0]), 'candidate_count': len(request['control_identity_candidates']), 'selection_reason': reply['reason']}

def attach(root, job, request):
    """Keep full native task/history/context; disclose only one historical object."""
    if job.get('control_identity_candidates'):
        return selection_request(root, job, request)
    pair = job.get('control_identity_pair')
    if not pair:
        return request
    pair = deepcopy(pair)
    pair['current_image'] = 1
    pair['context'] = recorded_history(pair)
    q = request
    original = q['original_request']
    if 'control_refs' in original and pair['control'] not in original['control_refs']:
        original['control_refs'].append(pair['control'])
        from regrow.recognition.control_references import prepare
        original.update(prepare(original))
    if job['stage'] == 'discovery':
        original['discovery_context'].setdefault('control_names', {})[pair['ref']] = pair['control']
    from regrow.prompts.frame_context import primary
    from regrow.prompts.frame_context import purpose
    from regrow.prompts.frame_context import label
    selected_purpose = '原动作后图（身份复核）' if job['stage'] == 'update' else '原发现图（身份复核）'
    q['screenshots'] = [pair['current_frame'], pair['historical_frame']]
    q['image_refs'] = list(q['screenshots'])
    label(q, pair['current_frame'], selected_purpose)
    label(q, pair['historical_frame'], '历史对象原场景（给定控件的历史外观）')
    q['control_identity_pair'] = deepcopy(pair)
    q['identity_candidate'] = deepcopy(job.get('candidate'))
    q.update(role='control_identity_comparison', stage='control_identity_comparison')
    from regrow.prompts.prompt_material import identity_needs
    identity_needs(q, [pair], job.get('attempt'))
    q['response_schema'] = {'type': 'object', 'properties': {'control_identity': {'type': 'string', 'enum': ['same', 'different', 'uncertain']}, 'reason': {'type': 'string', 'minLength': 1}}, 'required': ['control_identity', 'reason'], 'additionalProperties': False}
    path = '纠错/控件身份复核.prompt'
    part = {'path': path, 'text': (Path(root) / 'regrow/prompts' / path).read_text()}
    q['fixed_parts'] = [part]
    q['system_prompt'] = part['text']
    from regrow.prompts.prompt_material import same
    dynamic = review_material(job, original, [pair], candidate=q['identity_candidate'])
    dynamic['本次目的'] = '核对指定控件是否沿用历史身份；原步骤的其余判断保留。'
    dynamic['本次只核对这一对控件'] = {'区块': pair['region_name'], '历史对象': {'图片': 2, '名称': pair['old_name'], 'ref': pair['ref'], '身份框': pair['historical_box'], '原观察': pair['historical_evidence'], '外观描述': pair['historical_description'], '历史职责与知识': pair['context']}, '当前对象': {'图片': pair['current_image'], '名称': pair['current_name'], **({'身份框': pair['current_box']} if pair['current_box'] else {})}, '说明': '图1为本步对象所在原场景，图2为历史对象原场景；给定框只用于指认。本次只返回身份判断与理由。'}
    if pair.get('kind') == 'reuse':
        dynamic['本次目的'] = '确认本帧能否复用历史控件 ' + pair['ref'] + '。same表示该历史对象在当前前景中可确认；different表示本次引用了其他对象或历史对象不在当前前景；uncertain表示仍不能判断。different只撤回这条本帧引用，旧身份与历史保留。'
    if pair.get('kind') == 'reuse' and not pair.get('current_box'):
        dynamic['本次只核对这一对控件']['当前对象'] = {'图片': 1, '待复核的历史引用':pair['ref'], '所属区块':pair['region_name'], '该区块最近登记描述':pair.get('region_description',''), '本图外观位置候选':pair.get('current_candidates',[]), '说明':'本次没有已绑定的当前框；先在图1确认这个历史控件是否仍可辨认。候选位置只是找对象的线索，不是自动对应。不能自行改为旁边另一个控件进行比较。'}
    if pair.get('selection_reason'):
        if not any((row.get('identity_candidate') == pair['ref'] and same(row.get('reason'), pair['selection_reason']) for row in job.get('history', []))):
            dynamic['候选选择依据'] = pair['selection_reason']
        dynamic['复核边界'] = '这只是按场景选出的候选，仍须核对当前场景和历史依据；若发现不是同一对象，其他候选尚未排除，应保留uncertain，不轮换逐对试或直接新建。'
    q['user_prompt'] = q['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    return q

def compared_candidate(request, reply):
    """Bind a geometry-free comparison to the original single-frame candidate."""
    import jsonschema
    jsonschema.validate(reply, request['response_schema'])
    if not reply['reason'].strip():
        raise ValueError('身份比较需要实际依据')
    pair = request['control_identity_pair']
    from regrow.recognition.control_references import decode, encode
    proposal = decode(request['original_request'], request['identity_candidate'])
    if reply['control_identity'] == 'uncertain':
        return (None, None)
    if reply['control_identity'] == 'different' and pair.get('candidate_count', 1) > 1:
        raise ValueError('所选对象不同但其他历史候选未排除；保留uncertain')
    if not isinstance(proposal, dict):
        raise ValueError('身份比较缺少原单图候选')
    row = proposal['controls'][pair['control_index']]
    ri = row.get('region_index', pair['region_index'])
    if box(row.get('bbox')) != pair['current_box'] or proposal['regions'][ri].get('ref') != pair['region_ref']:
        raise ValueError('身份比较必须绑定原单图对象和所属区块')
    if pair.get('kind') == 'reuse':
        if row.get('ref') != pair.get('submitted_ref', pair['ref']):
            raise ValueError('本帧引用与复核的历史身份不一致')
        if reply['control_identity'] == 'different':
            # Keep the rejected draft for correction, including dependent task/target fields.
            # Do not silently publish its remaining knowledge against the old object.
            pass
    else:
        row['ref'] = pair['ref'] if reply['control_identity'] == 'same' else ''
        if 'identity' in row:
            row['identity'] = 'same' if reply['control_identity'] == 'same' else 'new'
    original = deepcopy(request['original_request'])
    original.setdefault('control_identity_reviews', []).append({'key': pair['key'], 'decision': reply['control_identity'], 'reason': reply['reason']})
    return (original, encode(original, proposal))

def reviewed_request(request, reply):
    return compared_candidate(request, reply)[0]


def recheck_request(root, job, previous_request, previous_reply, reason):
    """Rebuild the same real identity question after an explicit rule repair."""
    if previous_request.get('role') != 'control_identity_comparison':
        raise ValueError('需要真实身份比较请求')
    if previous_request['original_request'].get('source', {}).get('attempt') != job.get('attempt'):
        raise ValueError('身份复核必须属于同一实际动作')
    current = deepcopy(job)
    current.pop('registration_submission', None)
    current.pop('control_identity_candidates', None)
    current['control_identity_pair'] = deepcopy(previous_request['control_identity_pair'])
    current['candidate'] = deepcopy(previous_request['identity_candidate'])
    current['error'] = {'kind': 'identity_rules_recheck', 'reason': reason,
                        '先前身份判断（本次待复核）': deepcopy(previous_reply)}
    request = deepcopy(previous_request)
    request['original_request']['control_identity_reviews'] = deepcopy(job['request'].get('control_identity_reviews', []))
    request = attach(root, current, request)
    request['identity_rules_recheck'] = True
    return request


def queue_recheck(root, run, comparison_call, reason):
    """Queue one model recheck; keep original replies, attempt and repair count."""
    from regrow.traversal.step_repair import pending, atomic, read
    run = Path(run)
    job = pending(run)
    if not job or job.get('status') != 'blocked' or job.get('stage') != 'update' or not job.get('attempt'):
        raise ValueError('仅续接有真实未结算动作的身份阻塞')
    if job.get('identity_recheck_history'):
        raise ValueError('同一阻塞已安排过身份复核，不重复请求同一证据')
    request = read(run / 'calls' / comparison_call / 'request.json')
    reply = read(run / 'calls' / comparison_call / 'response.json')
    fresh = recheck_request(root, job, request, reply, reason)
    archive = Path(job['path']).with_name('before-identity-rule-recheck.json')
    if (run / archive).exists():
        raise ValueError('复核归档已存在')
    atomic(run / archive, job)
    job['identity_recheck_request'] = fresh
    job['identity_recheck_history'] = [{'comparison_call': comparison_call, 'reason': reason,
                                        'archive': str(archive), 'repairs_before': job['repairs']}]
    job.pop('registration_submission', None)
    job['status'] = 'repair'
    atomic(run / job['path'], job)
    return fresh
