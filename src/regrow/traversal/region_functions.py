from regrow.records.calls import submission as _owner_submission
from regrow.records import tasks as _task_queries
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.paths import SOURCE_ROOT
from regrow.records.object_store import region_work
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records import object_store as object_store
'Region-owned reusable functions; instruction composition happens after traversal.'
from regrow.records.object_store import owned_controls
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from regrow.recognition import identity_templates as templates
from regrow.records.function_evidence import action_results
from regrow.records.function_evidence import action_row
from regrow.records.function_evidence import omitted_reason
from regrow.records.function_evidence import incoming_results
from regrow.records.function_evidence import coverage as action_evidence_coverage
from regrow.records import function_scope as knowledge

def wire_schema(root):

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for (k, v) in value.items() if k != 'uniqueItems'}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    return strip(schema(root))
from regrow.prompts.compose import entry as prompt_entry

def prompt_paths():
    return prompt_entry(SOURCE_ROOT, 'function_registration')['parts']

def request_support_review(run, rid, call):
    """Ask the task author to classify observed controls; never invent support tasks."""
    from regrow.traversal import discovery_step as _discovery_step
    tasks = _task_queries
    discovery = _discovery_step
    (_, records, _) = _record_load(run)
    region = records.get(rid, {})
    supported = {t.get('control') for t in owned_tasks(region).values()} | tasks.purpose_controls(region)
    missing = [cid for cid in owned_controls(region) if cid not in supported]
    key = hashlib.sha256(json.dumps([missing, sorted(owned_actions(region))], sort_keys=True).encode()).hexdigest()
    if not missing or region_work(region).get('support_review_key') == key:
        return False

    def mutate(records, state, *args):
        r = records[rid]
        region_work(r)['support_review_key'] = key
        region_work(r).setdefault('task_inventory', {})['review'] = {'kind': 'function_support', 'source_call': call, 'reason': '功能登记缺少已登记知识依据。请结合截图与已有记录核对这些控件的具体未知：' + '、'.join((owned_controls(r)[cid]['name'] for cid in missing)) + '。已有明确用途可引用，不为支持总结制造任务或操作。'}
    import uuid
    _record_publish(run, 'support-review-' + uuid.uuid4().hex, mutate)
    return True

def supported_tasks(region, records=None):
    return knowledge.supported(region, records)

def supporting_tasks(region, records=None):
    records = records or {region['id']: region}
    local = {name: {'region': task.ref.split('/', 1)[0] if hasattr(task, 'ref') else region['id'], 'name': task.ref.split('/', 1)[1] if hasattr(task, 'ref') else name, 'task': task} for (name, task) in supported_tasks(region, records).items()}
    return {**local, **knowledge.parameter_support(region, records)}

def catalog(region, records=None):
    from regrow.records.tasks import Task
    from regrow.records.tasks import parameter_ref
    result = {}
    known = {}
    for (key, support) in supporting_tasks(region, records).items():
        task = support['task']
        for (name, fact) in task_value(task, 'findings', {}).items():
            identity = parameter_ref(task, name) if isinstance(task, Task) else (support['region'], task.get('control'), name)
            if identity in known:
                result[known[identity]]['support_tasks'].append(key)
                continue
            ref = key + ' / ' + name
            known[identity] = ref
            result[ref] = {**deepcopy(fact), 'task': key, 'task_region': support['region'], 'task_name': support['name'], 'support_tasks': [key]}
    return result

def attribute_context(region, records=None):
    """Keep full binding keys and facts, grouped under the supporting task."""
    result = {}
    for (key, fact) in catalog(region, records).items():
        if fact['task_region'] != region['id']:
            continue
        item = {k: v for (k, v) in fact.items() if k not in ('source', 'sources')}
        item['事实来源'] = deepcopy(fact.get('sources') or ([fact['source']] if fact.get('source') else []))
        result.setdefault(fact['task'], {})[key] = item
    return result

def semantic_observation(control):
    return next((row for row in reversed(observation_history(control)) if not row.get('visual_only')), {})

def purpose_observation(control):
    from regrow.records.control_history_context import last_reported
    result = {}
    for field in ('knowledge', 'possible_operation', 'uncertainty'):
        if field == 'knowledge' and isinstance(control.get('knowledge'), str):
            if control['knowledge']:
                result['knowledge'] = control['knowledge']
            continue
        row = last_reported(control, field)
        if row.get(field):
            result[field] = row[field]
    return result

def evidence_projection(region, records=None):
    """Build once for the request and its invalidation digest; keep observation provenance."""
    controls = []
    for c in owned_controls(region).values():
        observation = semantic_observation(c)
        source = {**observation.get('evidence', {}), **observation}
        controls.append({'名称': c['name'], **purpose_observation(c), '观察出处': {k: source[k] for k in ('source_call', 'observation', 'source_field') if k in source}})
        if templates.evidence_limit(observation):
            controls[-1]['视觉依据限定'] = templates.evidence_limit(observation)
    return {'已观察控件': controls, '已登记操作': [{'任务': n, '依据': task_value(t, 'result_evidence', t.get('reason') or t.get('name', '')), '任务提出调用': task_value(t, 'source_call'), '稳定知识': task_value(t, 'knowledge', ''), '共享知识来源': task_value(t, 'knowledge_source'), '依据时态': '历史记录：其中当前、本轮、未验证均指对应观察时刻，须与后续动作和恢复观察合看', '结果动作记录': list(task_value(t, 'attempts', [])), '登记方式': '引用共享知识' if t.get('shared_result') else task_value(t, 'completion_basis', {}).get('basis', '来源见原记录')} for (n, t) in supported_tasks(region, records).items()], '已记录属性（待甄别）': attribute_context(region, records), '同区块已执行动作结果': action_results(region, records), '动作证据覆盖': action_evidence_coverage(region, records), '进入本区块的已观察结果': incoming_results(region, records)}

def summary_projection(region, records=None):
    from regrow.records import task_knowledge as _task_knowledge
    records = records or {region['id']: region}
    supports = supporting_tasks(region, records)
    return {'已有区块知识': deepcopy(region.get('local_knowledge', {})), '共享控件知识': {cid: _task_knowledge.control_knowledge(region, cid, records) for (cid, c) in owned_controls(region).items() if c.get('shared_control_ref')}, '已登记操作': [{'ref': getattr(t, 'ref', region['id'] + '/' + n), **knowledge.task_product(n, t)} for (n, t) in supported_tasks(region, records).items()], '控件用途标注': [{'ref': cid, '名称': c['name'], **purpose_observation(c)} for (cid, c) in owned_controls(region).items()], '同区块已执行动作结果': [knowledge.compact_action(row) for row in action_results(region, records)], '动作证据覆盖': action_evidence_coverage(region, records), '进入本区块的已观察结果': [knowledge.compact_action(row) for row in incoming_results(region, records)], '入口与目标一级摘要': [{**edge, 'destination': knowledge.card(records[edge['region']], records)} for edge in knowledge.entries(region, records)], '按本地参数任务披露的支持': [{'ref': support['region'] + '/' + support['name'], '区块': support['region'], **knowledge.task_product(support['name'], support['task']), '动作结果': [knowledge.compact_action(row) for row in action_results(records[support['region']], records) if row['动作记录'] in task_value(support['task'], 'attempts', []) or (row['控件'] and row['控件'] == owned_controls(records[support['region']]).get(support['task'].get('control'), {}).get('name'))]} for (key, support) in supports.items() if support['region'] != region['id']], '支持知识引用目录': {ref: {'区块': row['region'], '类型': '任务' if row['kind'] == 'task' else '控件用途', '名称': row.get('name') or owned_controls(region)[row['control']]['name']} for (ref, row) in support_catalog(region, records).items()}, '可引用参数事实': {key: knowledge.fact_card(fact) for (key, fact) in catalog(region, records).items()}}

def signature(region, records=None):
    records = records or {region['id']: region}
    evidence = evidence_projection(region, records)
    evidence.pop('动作证据覆盖')
    local_tasks = owned_tasks(region)
    attempts = {aid for t in local_tasks.values() if not t.get('equivalent_to') for aid in task_value(t, 'attempts', [])}
    relevant = attempts
    evidence['同区块已执行动作结果'] = [row for row in evidence['同区块已执行动作结果'] if row['动作记录'] in relevant]
    for (item, (cid, control)) in zip(evidence['已观察控件'], owned_controls(region).items()):
        stable = [task_value(t, 'knowledge') for t in local_tasks.values() if t.get('control') == cid and task_value(t, 'knowledge') and (t.get('status') in ('done', 'record_only'))]
        if stable:
            item.pop('possible_operation', None)
            item.pop('uncertainty', None)
            item['已登记用途'] = stable
    for c in evidence['已观察控件']:
        c.pop('观察出处', None)
        c.pop('用途观察来源', None)
    selected = {(row['region'], row['task']) for f in region.get('functions', {}).values() for row in f.get('support_tasks', []) if row['region'] != region['id']}
    dependencies = []
    for (rid, name) in sorted(selected):
        source = records.get(rid, {})
        task = owned_tasks(source).get(name)
        control = owned_controls(source).get((task or {}).get('control'), {})
        observed = purpose_observation(control)
        dependencies.append({'region': rid, 'task_name': name, 'task': task, 'control': {'name': control.get('name'), **{k: v for (k, v) in observed.items() if k in ('knowledge', 'possible_operation', 'uncertainty')}}, 'results': [action_row(source, aid, action, records) for (aid, action) in owned_actions(source).items() if task and omitted_reason(action) is None and (aid in task_value(task, 'attempts', []))]})
    evidence.pop('进入本区块的已观察结果')
    data = {'extraction_rules': [(SOURCE_ROOT / 'regrow/prompts' / p).read_text() for p in prompt_paths()], 'name': region['name'], 'tasks': dict(owned_tasks(region)), 'inventory': {k: v for (k, v) in region_work(region).get('task_inventory', {}).items() if k in ('inventory', 'controls', 'review')}, 'evidence': evidence, 'entries': [edge for edge in knowledge.entries(region, records) if edge['attempt'] in relevant], 'selected_foreign_support': dependencies}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def request_signature(region, records=None):
    """Protect every offered fact, including support first selected in this reply."""
    data = {'rules': [(SOURCE_ROOT / 'regrow/prompts' / p).read_text() for p in prompt_paths()], 'name': region['name'], 'description': region['description'], 'evidence': summary_projection(region, records)}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def review_current(region, records=None):
    return region_work(region).get('function_inventory', {}).get('evidence_digest') == signature(region, records)

def ready(region, records=None):
    """Close all local work; changed adopted supports settle their own batch first."""
    records = records or {region['id']: region}
    if not _task_queries.coverage(region, records)['complete']:
        return False
    from regrow.records.task_settlement import completion_target
    from regrow.records.tasks import in_scope
    if any((task.get('status') in ('pending', 'blocked') and in_scope(owner, task, records) and (completion_target(owner, task)['region'] == region['id']) for owner in records.values() for task in owned_tasks(owner).values())):
        return False
    dependencies = set()
    for function in region.get('functions', {}).values():
        for support in function.get('support_tasks', []):
            owner = records.get(support['region'], {})
            task = owned_tasks(owner).get(support['task'])
            target = completion_target(owner, task)['region'] if task else support['region']
            if target != region['id']:
                dependencies.add(target)
    return all((rid in records and _task_queries.coverage(records[rid], records)['complete'] for rid in dependencies))

def next_ready(records, state):
    """Summarize closed Region work once per evidence revision, without navigation."""
    for region in sorted(records.values(), key=lambda r: r['id'] != state.get('working_region')):
        if ready(region, records) and (not region_work(region).get('registration_gaps', {}).get('function_registration')) and (not review_current(region, records)):
            return region['id']
    return None

def schema(root):
    return json.loads((Path(root) / 'regrow/prompts/输出格式/区块功能登记.schema').read_text())

def support_catalog(region, records=None):
    """Explicit task sources or observed control purposes, never invented tasks."""
    from regrow.records.task_updates import reference
    from regrow.records.task_knowledge import observed_purpose
    from regrow.records.task_settlement import completion_target
    records = records or {region['id']: region}
    result = {reference(row['region'], row['name']): {'kind': 'task', **{field: value for (field, value) in completion_target(records[row['region']], row['task']).items() if field in ('region', 'control')}, 'name': row['name'], 'task_key': key} for (key, row) in supporting_tasks(region, records).items()}
    for (cid, control) in owned_controls(region).items():
        purpose = observed_purpose(control)
        if purpose:
            result[cid] = {'kind': 'control', 'region': region['id'], 'control': cid, 'source': deepcopy(purpose['evidence']), 'basis': purpose['evidence'].get('basis', 'observation_only')}
    return result

def request_schema(root, region, records=None):
    value = wire_schema(root)
    fields = value['properties']['functions']['items']['properties']
    names = list(support_catalog(region, records))
    keys = list(catalog(region, records))
    fields['supports']['minItems'] = 1
    if names:
        fields['supports']['items']['enum'] = names
    else:
        value['properties']['functions']['maxItems'] = 0
    if keys:
        fields['constraints']['items']['enum'] = keys
    else:
        fields['constraints']['maxItems'] = 0
    definitions = value['properties']['parameter_definitions']
    if keys:
        definitions['items']['properties']['ref']['enum'] = keys
    else:
        definitions['maxItems'] = 0
    local = value['properties']['local_knowledge']['properties']
    ids = list(region.get('local_knowledge', {}))
    if ids:
        local['update']['items']['properties']['id']['enum'] = ids
        local['delete']['items']['enum'] = ids
    else:
        local['update']['maxItems'] = 0
        local['delete']['maxItems'] = 0
    return value

def locations(sources):
    result = []
    for source in sources:
        item = {'region': source['region'], 'control': source.get('control')}
        if item not in result:
            result.append(item)
    return result

def register(region, reply, call, records=None):
    import jsonschema
    jsonschema.validate(reply, schema(SOURCE_ROOT))
    if not ready(region, records):
        raise ValueError('Region exploration or adopted support batch is not complete')
    if not reply['evidence'].strip():
        raise ValueError('function inventory needs evidence')
    facts = catalog(region, records)
    definitions = {}
    for definition in reply['parameter_definitions']:
        ref = definition['ref']
        if ref not in facts or ref in definitions or (not definition['description'].strip()):
            raise ValueError('stable parameter definition needs unique known fact and description')
        definitions[ref] = definition

    def stable_fact(ref):
        if ref not in definitions:
            raise ValueError('selected parameter needs stable definition: ' + ref)
        fact = facts[ref]
        return {**{k: deepcopy(v) for k, v in fact.items() if k != 'conditions'}, 'description': definitions[ref]['description']}
    from regrow.records.region_knowledge import validate as validate_knowledge
    validate_knowledge(region, reply['local_knowledge'])
    supports = support_catalog(region, records)
    facts = catalog(region, records)
    tasks = supporting_tasks(region, records)
    result = {}
    errors = []
    for proposed in reply['functions']:
        name = proposed['name'].strip()
        selected = proposed['supports']
        refs = [supports[n]['task_key'] for n in selected if n in supports and supports[n]['kind'] == 'task']
        direct = [supports[n] for n in selected if n in supports and supports[n]['kind'] == 'control']
        if not name or name in result or (not proposed['description'].strip()) or (not proposed['object'].strip()) or (not proposed['completion'].strip()) or (not selected) or any((n not in supports for n in selected)):
            raise ValueError('function needs known knowledge references')
        if not any((supports[n]['region'] == region['id'] for n in selected)):
            raise ValueError('功能主区块需要本地支持知识：' + name + '的依据全部来自相关区块。应引用真正支持本区块用途的任务或控件知识。')
        constraints = {}
        sources = []
        for key in proposed['constraints']:
            if key not in facts:
                matches = [full for (full, fact) in facts.items() if set(fact.get('support_tasks', [fact['task']])) & set(refs) and fact['name'] == key]
                if len(matches) == 1:
                    key = matches[0]
            fact = facts.get(key)
            if not fact or not set(fact.get('support_tasks', [fact['task']])) & set(refs):
                if fact:
                    reason = f"属性的来源任务“{fact['task']}”未列入本功能supports；只有该任务确实支持功能时才引用"
                    candidates = [key]
                else:
                    matches = [full for (full, value) in facts.items() if value['name'] == key and set(value.get('support_tasks', [value['task']])) & set(refs)]
                    reason = '短属性名不唯一，请使用完整属性名' if len(matches) > 1 else '该名称未匹配本功能支持任务的属性；不能用任务名或控件名代替属性名'
                    candidates = matches or [full for (full, value) in facts.items() if set(value.get('support_tasks', [value['task']])) & set(refs)]
                errors.append({'功能': name, '约束引用': key, '原因': reason, '可核对的完整属性名': candidates})
                continue
            fact = stable_fact(key)
            evidence = deepcopy(fact.get('sources', [fact['source']]))
            constraints[key] = {'name': fact['name'], 'description': fact['description'], **({'domain': deepcopy(fact['domain'])} if 'domain' in fact else {}), 'locations': locations(evidence), 'sources': evidence}
            sources.extend(evidence)
        entries = [{'region': supports[n]['region'], 'control': supports[n]['control']} for n in selected]
        result[name] = {'description': proposed['description'], 'object': proposed['object'], 'completion': proposed['completion'], 'region': region['id'], 'task_refs': [tasks[n]['name'] for n in refs if tasks[n]['region'] == region['id']], 'support_tasks': [{'region': tasks[n]['region'], 'task': tasks[n]['name']} for n in refs], 'locations': locations(entries + sources), 'constraints': constraints, 'unconfirmed': list(proposed['unconfirmed']), 'source_call': call}
        if direct:
            result[name]['support_controls'] = [{k: deepcopy(v) for (k, v) in row.items() if k != 'kind'} for row in direct]
    if errors:
        raise ValueError('constraint lacks supporting task evidence；constraints引用属性名，supports引用已提供的知识编号。只选择确有可设置证据的属性，不要为了通过校验全部填入。\n' + json.dumps(errors, ensure_ascii=False, indent=2))
    gap = region_work(region).get('registration_gaps', {}).pop('function_registration', None)
    if gap:
        region_work(region).setdefault('registration_gap_history', []).append({**deepcopy(gap), 'stage': 'function_registration', 'resolved_by': call})
    from regrow.records.region_knowledge import apply as apply_knowledge
    if not isinstance(records, object_store.Records):
        raise ValueError('知识段落编号需要正常对象存储入口')
    apply_knowledge(region, reply['local_knowledge'], records)
    region.setdefault('constraints', {}).update({ref: knowledge.fact_card(stable_fact(ref)) for ref in definitions if facts[ref]['task_region'] == region['id']})
    region['functions'] = result
    region_work(region)['function_inventory'] = {'source_call': call, 'evidence_digest': signature(region, records)}

def request(root, region, state, records=None):
    if not ready(region, records):
        raise ValueError('Region exploration or adopted support batch is not complete')
    pr = Path(root) / 'regrow/prompts'
    from regrow.prompts.compose import parts as rule_parts
    parts = rule_parts(root, 'function_registration')
    text = '\n\n'.join((part['text'] for part in parts))
    user = {'区块': region['name'], '描述': region['description'], **summary_projection(region, records)}
    dynamic = json.dumps(user, ensure_ascii=False, indent=2)
    request = {'pipeline_step': 'discovery', 'stage': 'function_registration', 'role': 'function_registration', 'action_ready': False, 'system_prompt': text, 'user_prompt': dynamic, 'dynamic_prompt': dynamic, 'screenshots': [], 'image_refs': [], 'fixed_parts': parts, 'response_schema': request_schema(root, region, records), 'source': {'region': region['id'], 'observation': (state.get('observation') or {}).get('id'), 'evidence_digest': request_signature(region, records)}}
    from regrow.traversal.work_context import attach
    attach(request, records or {region['id']: region}, state)
    return request

def commit(root, run, call):
    from regrow.traversal import register_update as _register_update
    from regrow.traversal import discovery_step as _discovery_step
    tasks = _task_queries
    reg = _register_update
    discovery = _discovery_step
    (q, reply) = _owner_submission(run, call)
    rid = q['source']['region']

    def mutate(records, state, snapshot, temp):
        if q.get('stage') != 'function_registration':
            raise ValueError('not a function registration request')
        if request_signature(records[rid], records) != q['source']['evidence_digest']:
            raise ValueError('function evidence changed since request')
        register(records[rid], reply, call, records)
    return _record_publish(run, 'functions-' + call, mutate)
