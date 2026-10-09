"""Review one new-vs-existing control conflict before identity publication.

Raw local pixel candidates only select a question. Luna decides identity using
original scenes; neither matching nor this module merges historical records.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import foreground_scope
import identity_templates
import image_match


class Conflict(ValueError):
    blocked_by = 'binding_conflict'

    def __init__(self, pair):
        self.control_identity_pair = pair
        super().__init__('新建控件与本区块唯一历史候选冲突，需要原场景两图核对：' + pair['current_name'] + ' / ' + pair['old_name'])


class CandidateConflict(ValueError):
    blocked_by = 'binding_conflict'

    def __init__(self, candidates):
        self.control_identity_candidates = candidates
        super().__init__('同一当前对象与本区块多个历史身份相似；先按场景选择一个候选，再核对这一对原图，不能按外观强行新建或合并')


def box(value):
    if not isinstance(value, dict):return None
    keys = ('left', 'top', 'right', 'bottom')
    if any(type(value.get(k)) is not int for k in keys):return None
    return [value[k] for k in keys]


def same_position(a, b):
    if not a or not b:return False
    overlap = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - overlap
    return union > 0 and overlap / union >= .8


def owner(records, request, proposal):
    if not proposal.get('previous_name') or proposal.get('identity') in ('new', 'uncertain'):return None
    labels = request.get('discovery_context', {}).get('region_names', request.get('region_names', {}))
    rid = labels.get(proposal['previous_name'])
    if rid in records:
        return rid if not records[rid].get('behavior_context') or proposal.get('context_matches') is True else None
    matches = [rid for rid, r in records.items() if r['name'] == proposal['previous_name']]
    if len(matches) != 1:return None
    rid = matches[0]
    return rid if not records[rid].get('behavior_context') or proposal.get('context_matches') is True else None


def candidate_groups(controls, hits):
    """Separate one current position/multiple histories from repeated positions."""
    associations = {i: [cid for cid, hit in hits.items()
                       if any(same_position(box(c.get('bbox')), h['box']) for h in hit.get('candidates', []))]
                    for i, c in controls}
    for i, c in controls:
        if c.get('previous_name') or c.get('identity') == 'uncertain':continue
        ids = associations[i]
        if not ids:continue
        if any(not hits[cid].get('accepted') or hits[cid].get('candidates_truncated') or
               len(hits[cid].get('candidates', [])) != 1 or
               sum(cid in row for row in associations.values()) != 1 for cid in ids):continue
        yield i, ids


def candidates(records, snapshot, frame, request, reply):
    from PIL import Image
    import numpy as np
    if not frame or not Path(frame).is_file():return
    scope = foreground_scope.validate(reply['foreground'], frame) if 'interactive_areas' in reply.get('foreground', {}) else None
    if not scope:return
    with Image.open(frame) as im:pixels = np.asarray(im.convert('RGB'))
    for ri, region in enumerate(reply.get('regions', [])):
        rid = owner(records, request, region);area = box(region.get('bbox'))
        if rid is None or not area or not foreground_scope.contains(area, scope):continue
        l, t, r, b = area
        if not (0 <= l < r <= pixels.shape[1] and 0 <= t < b <= pixels.shape[0]):continue
        controls = [(i, c) for i, c in enumerate(reply.get('controls', [])) if c.get('region_index') == ri]
        if not any(not c.get('previous_name') and c.get('identity') != 'uncertain' for _, c in controls):continue
        hits = {};observations = {}
        for cid, old in records[rid].get('controls', {}).items():
            observed = identity_templates.latest(old)
            if not observed:continue
            path = (snapshot/'regions'/rid/observed['image']).resolve()
            try:
                with Image.open(path) as im:template = np.asarray(im.convert('RGB'))
            except (OSError, FileNotFoundError):continue
            hit = image_match._search(template, pixels[t:b, l:r])
            for h in hit.get('candidates', []):h['box'] = [v + (l if k%2 == 0 else t) for k, v in enumerate(h['box'])]
            hits[cid] = hit;observations[cid] = observed
        for ci, ids in candidate_groups(controls, hits):
            group = []
            for cid in ids:
                c = reply['controls'][ci];old = records[rid]['controls'][cid];observed = observations[cid]
                source = observed.get('source_image');old_box = box(observed.get('bbox'))
                if not source or not old_box:continue
                source = (snapshot/'regions'/rid/source).resolve()
                if not source.is_file():continue
                # A control already explicitly reused elsewhere cannot be this new item.
                labels = request.get('discovery_context', {}).get('control_names', {})
                if any(other.get('previous_name') and (labels.get(other['previous_name']) == cid or other['previous_name'] == old['name']) for _, other in controls):continue
                label = next((name for name, ref in labels.items() if ref == cid), old['name'])
                if any(ref != cid and name == label for name, ref in labels.items()):continue
                pair = {'region': rid, 'control': cid, 'region_index': ri, 'control_index': ci,
                        'region_name': region['name'], 'region_previous_name': region['previous_name'],
                        'old_name': old['name'], 'previous_name': label,
                        'current_name': c.get('name', c.get('text', '')), 'current_box': box(c.get('bbox')),
                        'historical_box': old_box, 'historical_frame': str(source), 'current_frame': str(Path(frame).resolve()),
                        'historical_evidence': deepcopy(observed.get('evidence', {})),
                        'historical_description': observed.get('description', observed.get('icon_description', '')),
                        'snapshot': str(snapshot.resolve()), 'current_image': 2 if request.get('pipeline_step') == 'update' else 1}
                identity = {k: pair[k] for k in ('region', 'control', 'current_box', 'historical_box',
                            'historical_frame', 'current_frame', 'snapshot')}
                pair['key'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode() + source.read_bytes() + Path(frame).read_bytes()).hexdigest()
                import control_history_context
                pair['context'] = control_history_context.describe(records[rid], cid)
                pair['context']['适用条件与已登记知识'] = [
                    {'任务': name, '条件': task.get('conditions', []), '知识': task.get('knowledge', '')}
                    for name, task in records[rid].get('tasks', {}).items() if task.get('control') == cid]
                group.append(pair)
            # Missing original evidence must not turn several candidates into a unique one.
            if len(group) == len(ids):yield group


def check(records, snapshot, frame, request, reply):
    reviewed = {r['key']: r for r in request.get('control_identity_reviews', [])}
    for group in candidates(records, snapshot, frame, request, reply):
        if len(group) > 1:raise CandidateConflict(group)
        pair = group[0]
        if reviewed.get(pair['key'], {}).get('decision') == 'different':continue
        raise Conflict(pair)


def check_request(run, request, reply):
    """Publication callers invoke this after their idempotent-return boundary."""
    import discovery_step
    snapshot, records, _ = discovery_step.load(run)
    frames = request.get('screenshots', [])
    index = 1 if request.get('pipeline_step') == 'update' else 0
    frame = Path(run)/frames[index] if len(frames) > index and frames[index] else None
    check(records, snapshot, frame, request, reply)


def selection_request(root, job, request):
    """A small answer contract on the full normal correction context."""
    group = job['control_identity_candidates']
    q = request
    q['control_identity_candidates'] = deepcopy(group)
    q.update(role='control_identity_selection', stage='control_identity_selection')
    path = '纠错/控件身份候选选择.prompt'
    part = {'path': path, 'text': (Path(root)/'遍历prompt'/path).read_text()}
    q['fixed_parts'] = [part];q['system_prompt'] = part['text']
    q['response_schema'] = {'type': 'object', 'additionalProperties': False,
        'properties': {'candidate': {'type': ['string', 'null'], 'enum': [p['previous_name'] for p in group]+[None]},
                       'reason': {'type': 'string', 'minLength': 1}}, 'required': ['candidate', 'reason']}
    dynamic = json.loads(q['user_prompt'])
    dynamic['本区块同一当前对象的历史候选'] = {
        '区块': group[0]['region_name'], '当前对象': group[0]['current_name'],
        '当前图': group[0]['current_image'], '当前身份框': group[0]['current_box'],
        '候选': [{'candidate': p['previous_name'], '历史上下文': p['context']} for p in group]}
    q['user_prompt'] = q['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    return q


def selected_pair(request, reply):
    import jsonschema
    jsonschema.validate(reply, request['response_schema'])
    if not reply['reason'].strip():raise ValueError('候选选择须说明当前场景依据')
    if reply['candidate'] is None:return None
    selected = [p for p in request['control_identity_candidates'] if p['previous_name'] == reply['candidate']]
    if len(selected) != 1:raise ValueError('候选选择没有唯一对应本次本区块历史控件')
    return {**deepcopy(selected[0]), 'candidate_count': len(request['control_identity_candidates']),
            'selection_reason': reply['reason']}


def attach(root, job, request):
    """Keep full native task/history/context; disclose only one historical object."""
    if job.get('control_identity_candidates'):return selection_request(root, job, request)
    pair = job.get('control_identity_pair')
    if not pair:return request
    q = request
    original = q['original_request']
    if job['stage'] == 'discovery':
        original['discovery_context'].setdefault('control_names', {})[pair['previous_name']] = pair['control']
    frames = q['screenshots']
    if pair['historical_frame'] not in frames:frames.append(pair['historical_frame'])
    q['image_refs'] = list(frames)
    q['control_identity_pair'] = deepcopy(pair)
    q['response_schema']['properties']['control_identity'] = {'type': 'string', 'enum': ['same', 'different', 'uncertain']}
    q['response_schema']['required'].append('control_identity')
    path = '纠错/控件身份两图复核.prompt'
    part = {'path': path, 'text': (Path(root)/'遍历prompt'/path).read_text()}
    q['fixed_parts'].append(part);q['system_prompt'] += '\n\n' + part['text']
    dynamic = json.loads(q['user_prompt'])
    dynamic['本次只核对这一对控件'] = {
        '区块': pair['region_name'],
        '历史对象': {'图片': frames.index(pair['historical_frame'])+1, '名称': pair['old_name'],
                     'previous_name': pair['previous_name'], '身份框': pair['historical_box'], '原观察': pair['historical_evidence'],
                     '外观描述': pair['historical_description']},
        '当前对象': {'图片': pair['current_image'], '名称': pair['current_name'],
                     '身份框': pair['current_box'], '原提案索引': pair['control_index']},
        '说明': '以上两张为对象所在的原始完整场景。只比较这一对；其他原请求图仍用于实际动作结果，历史图不表示当前状态。'}
    if pair.get('selection_reason'):
        dynamic['候选选择依据'] = pair['selection_reason']
        dynamic['复核边界'] = '这只是按场景选出的候选，仍须两图核对；若发现不是同一对象，其他候选尚未排除，应保留uncertain，不轮换逐对试或直接新建。'
    dynamic['图片顺序'] = [{'图片': i+1, '用途': '本次当前场景' if i+1 == pair['current_image'] else
                        '历史对象原场景，仅核对身份' if f == pair['historical_frame'] else '原请求证据或补充观察'} for i, f in enumerate(frames)]
    q['user_prompt'] = q['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    return q


def reviewed_request(request, reply):
    """Bind the explicit decision to this exact proposed object and evidence."""
    pair = request.get('control_identity_pair')
    original = deepcopy(request['original_request'])
    if not pair:return original
    if not reply.get('reason', '').strip():raise ValueError('两图身份复核须说明场景依据')
    if reply.get('record_edit') is not None:raise ValueError('两图复核不能修改旧记录')
    decision = reply['control_identity'];resolution = reply['resolution']
    if resolution != 'revise':
        if decision != 'uncertain' or resolution not in ('blocked', 'defer'):
            raise ValueError('两图身份复核用revise登记same/different；仍不确定时保留blocked/defer，不改写旧记录或重做动作')
        return original
    proposal = reply.get('proposal') or {}
    owners = [i for i, r in enumerate(proposal.get('regions', [])) if r.get('previous_name') == pair['region_previous_name']]
    if len(owners) != 1:raise ValueError('两图复核不能改变已确认的区块身份')
    selected = [c for c in proposal.get('controls', []) if c.get('region_index') == owners[0] and box(c.get('bbox')) == pair['current_box']]
    if len(selected) != 1:raise ValueError('复核必须保留同一当前对象的区块归属和身份框，不能省略或换对象绕过核对')
    c = selected[0]
    if decision == 'same':
        if c.get('previous_name') != pair['previous_name'] or c.get('identity', 'same') != 'same':
            raise ValueError('same须在原proposal复用提供的previous_name')
    elif decision == 'different':
        if pair.get('candidate_count', 1) > 1:raise ValueError('所选对象不同但其他历史候选未排除；保留uncertain，不轮换候选或新建身份')
        if c.get('previous_name') or c.get('identity', 'new') != 'new':raise ValueError('different须明确登记独立新控件')
    elif c.get('identity') != 'uncertain':
        raise ValueError('仍不确定时发现步保留identity=uncertain；更新步用blocked/defer保留原待登记动作')
    original.setdefault('control_identity_reviews', []).append({'key': pair['key'], 'decision': decision, 'reason': reply['reason']})
    return original
