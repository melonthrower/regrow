"""One task proposal contract, selected context and task registration kernel.

Independent proposals prepare knowledge/sharing before this kernel. Local
observations materialize their objects first. Neither repeats the other's writes.
"""
from collections import Counter
from copy import deepcopy

import jsonschema

from regrow.records.object_store import owned_controls, owned_tasks, replace_owned_tasks, region_work
from regrow.records import task_assessments, task_settlement as settlement, task_updates as updates
from regrow.records.tasks import read as task_value, equivalent_source
from regrow.records.control_records import aliases


FIELDS = ('new_tasks', 'task_update', 'evidence')


def schema():
    from regrow.records.task_goals import operation_schema
    string = {'type': 'string', 'minLength': 1}
    value = updates.object_schema({'evidence': string, 'task_update': {'type': 'array', 'items': updates.schema()},
        'new_tasks': {'type': 'array', 'items': operation_schema()}})
    value['required'].remove('task_update')
    return value


def update_names(region, *, scope_review=False):
    focus = None if scope_review else region_work(region).get('task_inventory', {}).get('review', {}).get('task')
    return [name for name, task in owned_tasks(region).items()
            if (focus is None or name == focus) and task.get('status') in ('pending', 'blocked')]


def matching_question(tasks, operation):
    """An exact existing question is redundant, regardless of its status."""
    return next((name for name, task in tasks.items()
                 if task.get('control') == (operation.get('control') or None)
                 and bool(settlement.completion_condition(task).strip())
                 and settlement.completion_condition(task).strip() == settlement.completion_condition(operation).strip()), None)


def proposal_rejections(region):
    """Read old exact-duplicate refusals without making them new repair work."""
    rows = region_work(region).get('registration_gaps', {}).get('task_proposal', {}).get('rejected', [])
    return [row for row in rows if not (
        row.get('field') in ('operations', 'new_tasks')
        and row.get('reason') == '已有相同对象及完成条件的问题，请继续或复用原问题'
        and matching_question(owned_tasks(region), row.get('proposed_update', {})) is not None)]


def context(records, state, rid, *, scope_review=False, observed_new=False):
    from regrow.records.task_inventory_context import project
    from regrow.records.control_knowledge import card
    from regrow.records.tasks import target, target_control
    region = records[rid]
    value = schema()
    if not observed_new:
        value['properties']['new_tasks']['items']['properties']['control']['enum'] = list(owned_controls(region)) + ['']
    refs = [updates.reference(rid, name) for name in update_names(region, scope_review=scope_review)]
    rejected = proposal_rejections(region)
    if rejected and not scope_review:
        allowed = {row.get('task') for row in rejected if row.get('field') != 'new_tasks'}
        refs = [ref for ref in refs if ref in allowed]
    if refs:
        value['properties']['task_update']['items']['properties']['task']['enum'] = refs
    else:
        value['properties'].pop('task_update')
    material = project(records, state, rid)
    catalog = material.pop('已有任务')
    material['本轮可判断旧任务'] = []
    provided = set()
    for row in catalog:
        if row['task'] not in refs:
            continue
        item = {k: v for k, v in row.items() if k not in ('control', 'region', 'name')}
        task = owned_tasks(region)[row['task'].split('/', 1)[1]]
        cid = target_control(task)
        if cid and cid not in provided and cid not in owned_controls(region):
            item['当前控件知识'] = card(target(task) or {})
            provided.add(cid)
        latest = item.get('最新判断', {})
        if latest:
            item['此前判断（须对照原完成条件复核）'] = item.pop('最新判断')
        deferred = item.get('deferral', {})
        if deferred and all(latest.get(k) == v for k, v in deferred.items()):
            item.pop('deferral')
        material['本轮可判断旧任务'].append(item)
    material['相关已完成问题'] = [row for row in catalog if row.get('status') == 'done']
    material['其他任务背景'] = [row for row in catalog
                              if row['task'] not in refs and row.get('status') != 'done']
    if rejected:
        material['未接受的任务条目'] = [
            {'对象': row.get('proposed_update', {}).get('control') or row.get('task') or '原任务',
             '原问题': row.get('proposed_update', {}).get('target') or row.get('proposed_update', {}).get('completion_condition', ''),
             '问题': row['reason']} for row in rejected]
    return value, material


def apply(region, reply, call, *, records, state=None, request=None, reviewed_controls=None,
          scope_review=False, bindings=None):
    """Register only task fields, using this request's accepted object bindings."""
    spec = (request or {}).get('response_schema') or schema()
    spec = {'type': 'object', 'properties': {key: deepcopy(value) for key, value in spec.get('properties', {}).items() if key in FIELDS},
            'required': [key for key in spec.get('required', []) if key in FIELDS], 'additionalProperties': False}
    payload = {key: value for key, value in reply.items() if key in FIELDS}
    local = bool((request or {}).get('discovery_context', {}).get('mode') == 'local')
    task_assessments.envelope(payload, spec, partial=local)
    if not payload['evidence'].strip():
        raise ValueError('任务提出需要本次范围及判断依据')
    old = owned_tasks(region)
    tasks = dict(old)
    considered = set(owned_controls(region) if reviewed_controls is None else reviewed_controls)
    considered = {next((cid for cid, control in owned_controls(region).items()
                       if previous == cid or any(a['id'] == previous for a in aliases(control))), previous)
                  for previous in considered}
    if not considered.issubset(owned_controls(region)):
        raise ValueError('本次清点的控件身份已变化，需重新读取问题范围')
    assessment = {'accepted': [], 'rejected': []}
    seen = set()
    rows = payload.get('task_update', [])
    counts = Counter(row.get('task') for row in rows)
    for index, row in enumerate(rows):
        names = [name for name in old if updates.reference(region['id'], name) == row.get('task')]
        name = names[0] if len(names) == 1 else None
        current = tasks.get(name)
        if current is None and not local:
            raise ValueError('已有任务增量未能关联本区块明确task，需先核对引用')
        try:
            jsonschema.validate(row, spec['properties']['task_update']['items'])
            if current is None:
                raise ValueError('该任务引用不在本次给定范围内')
            if counts[row['task']] != 1:
                raise ValueError('同一任务不能重复提交判断')
            previous = task_value(current, 'latest_update', {})
            if previous.get('source', {}).get('source_call') == call:
                assessment['accepted'].append({'task': row['task'], 'state': previous.get('state'), 'already_accepted': True})
                seen.add(name)
                continue
            if name not in update_names(region, scope_review=bool(scope_review)):
                raise ValueError('只能更新本轮允许的未结束本地任务；其他原任务保持')
            task = deepcopy(current)
            from regrow.traversal import parameter_evidence_review
            review = region_work(region).get('task_inventory', {}).get('review', {})
            observed = updates.observed_control(region, task, state or {}) or bool(
                review.get('task') == name and review.get('kind') == 'parameter_facts'
                and review.get('snapshot') and parameter_evidence_review.evidence_context(region))
            basis = {'basis': 'observation_only', 'source_call': call,
                     'observation': ((state or {}).get('observation') or {}).get('id')}
            updates.store_increment(region, task, name, row, records, state or {}, basis, observed=observed)
            tasks[name] = task
            seen.add(name)
            assessment['accepted'].append({'task': row['task'], 'state': row['state']})
        except (ValueError, jsonschema.ValidationError) as error:
            assessment['rejected'].append(task_assessments.rejected(current, row, call, error, index))
    for index, submitted in enumerate(payload['new_tasks']):
        try:
            jsonschema.validate(submitted, spec['properties']['new_tasks']['items'])
            cid = (bindings or {}).get(submitted['control'], submitted['control'])
            if submitted['control'] and cid is None:
                raise ValueError('该控件名称重名或对应对象未被本次登记接受，请引用明确对象')
            cid = cid or None
            if cid is not None and cid not in owned_controls(region):
                raise ValueError('新问题的控件未在本次成功登记或存在明确身份歧义')
            definition = submitted
            task = {**deepcopy(definition), 'control': cid, 'status': 'pending', 'source_call': call, 'attempts': []}
            if 'function_refs' in task:
                from regrow.records.function_updates import task_refs
                task['function_refs'] = task_refs(records, region['id'], task['function_refs'])
            same = matching_question(tasks, task)
            if same is not None:
                flag = 'already_accepted' if task_value(tasks[same], 'source_call') == call else 'redundant'
                assessment['accepted'].append({'operation': index, 'task': updates.reference(region['id'], same), flag: True})
                continue
            name = settlement.task_definition(task)['label'].strip()
            base = name
            suffix = 1
            while name in tasks:
                suffix += 1
                name = (cid or region['id']) + ' / ' + base + (' / ' + str(suffix) if suffix > 2 else '')
            task['name'] = settlement.task_definition(task)['label']
            if settlement.region_task(task) and state:
                task['navigation_observation'] = (state.get('observation') or {}).get('id')
            tasks[name] = task
            seen.add(name)
            assessment['accepted'].append({'operation': index, 'task': updates.reference(region['id'], name)})
        except (ValueError, jsonschema.ValidationError) as error:
            if not local:
                raise
            detail = task_assessments.rejected(None, submitted, call, error, index)
            detail['field'] = 'new_tasks'
            assessment['rejected'].append(detail)
    if scope_review:
        for name in sorted(set(update_names(region, scope_review=True)) - seen):
            ref = updates.reference(region['id'], name)
            if not any(row.get('task') == ref for row in assessment['rejected']):
                assessment['rejected'].append(task_assessments.rejected(tasks[name], {'task': ref}, call,
                    ValueError('本轮要求复核的任务尚未给出判断'), None))
    for name, task in tasks.items():
        if task.get('equivalent_to'):
            canonical = equivalent_source(tasks, task)
            if not canonical or settlement.registration_kind(canonical) != settlement.registration_kind(task) or name == task['equivalent_to']:
                raise ValueError('等价任务须引用同类问题的直接代表')
    if assessment['rejected'] and not assessment['accepted'] and not payload['new_tasks'] and not local:
        raise ValueError('；'.join(str(row.get('task')) + '：' + row['reason'] for row in assessment['rejected']))
    replace_owned_tasks(region, tasks)
    prior = region_work(region).get('task_inventory', {})
    considered.update(cid for cid in prior.get('controls', []) if cid in owned_controls(region))
    region_work(region)['task_inventory'] = {'evidence': payload['evidence'],
        'controls': sorted(considered), 'source_call': call,
        'observation': ((state or {}).get('observation') or {}).get('id')}
    gaps = region_work(region).setdefault('registration_gaps', {})
    if assessment['rejected']:
        gaps['task_proposal'] = {'source_call': call, 'reason': '本次任务提出有未接受的条目',
                                 'rejected': deepcopy(assessment['rejected']), 'recheck_after': call}
    else:
        gaps.pop('task_proposal', None)
    return assessment


def apply_observation(records, state, request, reply, call, raw_controls):
    """Bind same-call names through accepted source rows, never a graph search."""
    from regrow.records.observations import frame_observation
    rid = request['discovery_context']['focus']
    region = records[rid]
    accepted = {}
    for cid, control in owned_controls(region).items():
        observation = frame_observation(control, kind='controls', call=call, region=rid)
        if observation:
            accepted[int(observation['evidence']['source_field'].split('/')[-1])] = cid
    counts = Counter(row.get('name') for row in raw_controls if row.get('name'))
    stored_names = Counter(control['name'] for control in owned_controls(region).values())
    bindings = {}
    for index, row in enumerate(raw_controls):
        name = row.get('name')
        if name:
            bindings[name] = (accepted.get(index) if counts[name] == 1 and stored_names[name] == 1 else None)
    considered = set(request.get('source', {}).get('controls', [])) | set(accepted.values())
    return apply(region, reply, call, records=records, state=state, request=request,
                 reviewed_controls=considered, bindings=bindings)
