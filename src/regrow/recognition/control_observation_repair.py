from regrow.records.snapshots import load as _record_load
from regrow.records.object_store import region_work
'Explicit source-scoped observation reassignment, never whole-control merging.'
from regrow.records.object_store import owned_actions
from regrow.records.object_store import observation_history
from regrow.records.object_store import replace_observation_history
from regrow.records.object_store import owned_controls
from copy import deepcopy

def schema():
    source = {'type': 'object', 'properties': {k: {'type': 'string', 'minLength': 1} for k in ('source_call', 'source_field')}, 'required': ['source_call', 'source_field'], 'additionalProperties': False}
    fields = {k: {'type': 'string', 'minLength': 1} for k in ('region', 'from_control', 'to_control', 'retained_name', 'evidence')}
    fields['observations'] = {'type': 'array', 'items': source, 'minItems': 1}
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}

def key(observation):
    evidence = observation.get('evidence', {})
    return (evidence.get('source_call'), evidence.get('source_field'))

def apply(records, state, edit, call):
    regions = [records[edit['region']]] if edit['region'] in records else []
    if len(regions) != 1:
        raise ValueError('观察纠正区块不唯一')
    region = regions[0]

    def find(name):
        ids = [name] if name in owned_controls(region) else []
        if len(ids) != 1:
            raise ValueError('观察纠正控件不唯一')
        return ids[0]
    (old, new) = (find(edit['from_control']), find(edit['to_control']))
    selectors = [(x['source_call'], x['source_field']) for x in edit['observations']]
    if old == new or not edit['evidence'].strip() or (not selectors) or (len(set(selectors)) != len(selectors)):
        raise ValueError('观察纠正需要不同对象、唯一来源及依据')
    retained = edit['retained_name'].strip()
    if not retained or any((cid != old and c['name'] == retained for (cid, c) in owned_controls(region).items())):
        raise ValueError('保留对象需要明确且不重复的职责名称')
    source = owned_controls(region)[old]
    target = owned_controls(region)[new]
    chosen = []
    for selector in selectors:
        hits = [o for o in observation_history(source) if key(o) == selector]
        if len(hits) != 1 or any((key(o) == selector for o in observation_history(target))):
            raise ValueError('观察来源缺失、重复或已在目标对象')
        chosen.append(hits[0])
    if len(chosen) == len(observation_history(source)):
        raise ValueError('不能迁移来源控件的最后观察；需另行核对整个身份')
    observations = {o.get('evidence', {}).get('observation') for o in chosen}
    for owner in records.values():
        for action in owned_actions(owner).values():
            if owner.get('id') == region.get('id') and action.get('control') == old and (action.get('evidence', {}).get('before_observation') in observations):
                raise ValueError('被迁移观察支撑已执行动作；先独立核对动作归属，不随观察自动迁移')
    ref = source['name']
    source['name'] = retained
    replace_observation_history(source, [o for o in observation_history(source) if key(o) not in selectors])
    observation_history(target, create=True).extend(deepcopy(chosen))
    observation_history(target).sort(key=lambda o: (str(o.get('evidence', {}).get('source_call', '')), str(o.get('evidence', {}).get('source_field', ''))))
    audit = {'source_call': call, 'from_control': old, 'to_control': new, 'observations': deepcopy(edit['observations']), 'evidence': edit['evidence'], 'ref': ref, 'retained_name': retained}
    region_work(region).setdefault('control_observation_revisions', []).append(audit)
    current = state.get('observation', {})
    if current.get('id') in observations and old in current.get('control_refs', []):
        remaining = any((o.get('evidence', {}).get('observation') == current['id'] for o in observation_history(source)))
        current['control_refs'] = list(dict.fromkeys([c for c in current['control_refs'] if c != old or remaining] + [new]))
    region_work(region).setdefault('task_inventory', {})['review'] = {'source_call': call, 'reason': '历史观察对象已纠正；核对任务与功能依据，不继承另一对象的完成状态。'}
    region_work(region).get('function_inventory', {}).pop('evidence_digest', None)
    state.pop('visual_navigation', None)

def validate_scope(run, job, edit, records, scope):
    from pathlib import Path
    import json
    candidates = job['request'].get('control_observation_candidates', [])
    matched = [c for c in candidates if c['region'] in scope and c['region'] == edit['region'] and c['from_control'] == edit['from_control'] and c['to_control'] == edit['to_control']]
    if len(matched) != 1:
        raise ValueError('观察纠正对象没有随本轮披露')
    c = matched[0]
    if c['region'] not in scope or any((cid not in owned_controls(scope[c['region']]) for cid in (c['from_control'], c['to_control']))):
        raise ValueError('观察纠正超出本轮控件范围')
    pointer = json.loads((Path(run) / 'knowledge_current.json').read_text())
    if pointer['snapshot'] != job['request'].get('control_observation_snapshot'):
        raise ValueError('观察纠正快照已变化')
    allowed = {(s['source_call'], s['source_field']) for s in c['observations']}
    if not all(((s['source_call'], s['source_field']) in allowed for s in edit['observations'])):
        raise ValueError('观察来源没有随本轮披露')
    return deepcopy(edit)

def begin(root, run, rid, from_control, to_control, selectors, frame):
    """Supervised diagnosis enters normal task correction with complete run context."""
    from regrow.traversal import task_proposer as _task_proposer
    from regrow.traversal import step_repair as _step_repair
    from pathlib import Path
    import json
    import uuid
    run = Path(run).resolve()
    (snapshot, records, state) = _record_load(run)
    if any(((run / n).exists() for n in ('pending_step.json', 'execution_pending.json'))):
        raise ValueError('先完成当前步骤或待结算动作，再核对历史观察')
    import hashlib
    observed = (state.get('observation') or {}).get('image')
    if rid not in state.get('interactive_regions', []) or not observed:
        raise ValueError('当前区块未确认可交互，不能进入本轮观察纠正')
    current = (run / observed).resolve()
    provided = Path(frame).resolve()
    if not current.is_file() or not provided.is_file() or hashlib.sha256(current.read_bytes()).digest() != hashlib.sha256(provided.read_bytes()).digest():
        raise ValueError('观察纠正必须使用当前记录的原始观察图')
    region = records[rid]
    source = owned_controls(region)[from_control]
    target = owned_controls(region)[to_control]
    chosen = []
    for selector in selectors:
        hits = [o for o in observation_history(source) if key(o) == (selector['source_call'], selector['source_field'])]
        if len(hits) != 1:
            raise ValueError('诊断观察不唯一')
        chosen += hits
    q = _task_proposer.plan_request(root, records, state, rid)
    q['screenshots'] = [str(Path(frame).resolve())]
    examples = [observation_history(source)[0], *chosen, observation_history(target)[-1]]
    labels = [{'image': 1, 'purpose': '当前保存观察；本轮没有执行动作'}]
    for o in examples:
        image = (snapshot / o['source_image']).resolve()
        if not image.is_file():
            raise ValueError('历史观察缺少原始截图')
        labels.append({'source': o['evidence'], '原图': str(image)})
    q['image_refs'] = list(q['screenshots'])
    q['control_observation_snapshot'] = str(snapshot.relative_to(run))
    q['control_observation_candidates'] = [{'region': rid, 'from_control': from_control, 'to_control': to_control, 'observations': deepcopy(selectors)}]

    def review_record(record):
        return {**deepcopy(dict(record)), 'observations': deepcopy(observation_history(record))}
    details = {'来源控件': review_record(source), '目标候选控件': review_record(target), '观察证据来源': labels, '说明': '来源和目标只是待核对候选。本图只显示当前观察，历史原图未附；结合已登记职责、历史观察与原任务判断。证据不足保留缺口，不能声称重新看过旧图。若证据支持确有混写，按source_call/source_field迁移指定观察，同时必须填写retained_name：它是来源控件在移除误挂观察后，依据剩余观察和原任务职责应使用的准确名称；不能继续沿用描述被移走对象的错误名称。from_control/to_control引用本轮披露的控件ID，retained_name是本次修正后的名称。不得整条合并、迁移旧任务或改写动作。若同一物理对象只是模式变化，不应拆分。回复沿正常纠错，修订后完整清点当前区块。'}
    q['user_prompt'] += '\n历史观察归属核对：' + json.dumps(details, ensure_ascii=False, indent=2)
    q['dynamic_prompt'] = q['user_prompt']
    job = {'path': 'repair_episodes/observation-review-' + uuid.uuid4().hex + '/episode.json', 'stage': 'task_proposal', 'request': q, 'attempt': None, 'status': 'repair', 'repairs': 0, 'observations': 0, 'history': [], 'seen': [], 'supplements': [], 'candidate': None, 'blocked_by': 'binding_conflict', 'error': '历史控件的部分观察可能对应不同职责对象；按本图、历史记录及来源核对，依据不足时保留未确认，未确认前不得继承任务完成。'}
    _step_repair.atomic(run / job['path'], job)
    _step_repair.atomic(run / 'pending_step.json', {'episode': job['path']})
    return job
