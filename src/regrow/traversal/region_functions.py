from regrow.records.calls import submission as _owner_submission
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.paths import SOURCE_ROOT
from regrow.records.object_store import region_work
from regrow.records import object_store as object_store
'Region-owned reusable functions; instruction composition happens after traversal.'
from regrow.records.object_store import owned_controls
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from regrow.records.function_evidence import action_results
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
    return [prompt_entry(SOURCE_ROOT, 'function_registration')['template']]


def catalog(region, records=None):
    from regrow.records.function_updates import catalog as facts
    return facts(region)


def summary_projection(region, records=None):
    from regrow.records.control_knowledge import card
    return {'区块已有知识': deepcopy(region.get('local_knowledge', {})),
            '控件知识': [{'ref': cid, '名称': c['name'], 'knowledge': card(c)} for cid, c in owned_controls(region).items() if c.get('knowledge')],
            '可引用参数事实': catalog(region, records),
            '支持知识引用目录': support_catalog(region, records),
            '实际操作结果': [knowledge.compact_action(row) for row in action_results(region, records)]}

def signature(region, records=None):
    data = {'name': region['name'], 'description': region.get('description'),
            'local_knowledge': region.get('local_knowledge', {}),
            'controls': {cid: {k: c.get(k) for k in ('name', 'knowledge', 'jump_to')}
                         for cid, c in owned_controls(region).items()}}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def request_signature(region, records=None):
    """Protect every offered fact, including support first selected in this reply."""
    data = {'rules': [(SOURCE_ROOT / 'regrow/prompts' / p).read_text() for p in prompt_paths()], 'name': region['name'], 'description': region['description'], 'evidence': summary_projection(region, records)}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def review_current(region, records=None):
    return region_work(region).get('function_inventory', {}).get('evidence_digest') == signature(region, records)

def ready(region, records=None):
    gap = region_work(region).get('registration_gaps', {}).get('function_registration', {})
    return bool(support_catalog(region, records) or region.get('functions') or region_work(region).get('function_inventory')) and gap.get('evidence_digest') != signature(region, records)

def next_ready(records, state):
    """Only the explicit/global-idle finalizer calls this selector."""
    for rid in sorted(records, key=lambda r: r != state.get('working_region')):
        region = records[rid]
        if region_work(region).get('out_of_scope_reason'):
            continue
        if ready(region, records) and not review_current(region, records):
            return rid
    return None


def schema(root):
    return json.loads((Path(root) / 'regrow/prompts/输出格式/区块功能登记.schema').read_text())

def support_catalog(region, records=None):
    from regrow.records.control_knowledge import evidence
    result = {cid: {'kind': 'control', 'region': region['id'], 'control': cid,
                    'name': c['name'], 'source': evidence(c)}
              for cid, c in owned_controls(region).items() if c.get('knowledge')}
    if region.get('local_knowledge'):
        result[region['id']] = {'kind': 'region', 'region': region['id'], 'control': None, 'name': region['name']}
    return result

def request_schema(root, region, records=None):
    from regrow.records.function_updates import schema as changes
    from regrow.records.object_knowledge import region_schema
    return {'type':'object','properties':{
        'function_updates':changes([region['id']]),
        'local_knowledge':region_schema(),
        'evidence':{'type':'string','minLength':1}},
        'required':['function_updates','local_knowledge','evidence'],'additionalProperties':False}


def locations(sources):
    result = []
    for source in sources:
        item = {'region': source['region'], 'control': source.get('control')}
        if item not in result:
            result.append(item)
    return result

def register(region, reply, call, records=None):
    records = records or {region['id']:region}
    if not reply['evidence'].strip():
        raise ValueError('功能整理需要说明实际支持依据')
    from regrow.records.region_knowledge import validate, apply
    from regrow.records.function_updates import apply as apply_functions
    validate(region, reply['local_knowledge'])
    apply(region, reply['local_knowledge'], records)
    apply_functions(records, reply['function_updates'], {'source_call':call}, [region['id']])
    region_work(region).get('registration_gaps', {}).pop('function_registration', None)
    region_work(region)['function_inventory'] = {'source_call':call,'evidence_digest':signature(region,records)}


def request(root, region, state, records=None):
    if not ready(region, records):
        raise ValueError('当前没有可总结的新对象知识或本次总结缺口尚未变化')
    pr = Path(root) / 'regrow/prompts'
    from regrow.prompts.compose import parts as rule_parts
    parts = rule_parts(root, 'function_registration')
    text = '\n\n'.join((part['text'] for part in parts))
    from regrow.records.function_updates import view
    user = {'已有功能轮廓':view(records or {region['id']:region},region['id']), '区块引用':region['id'], '区块': region['name'], '描述': {'历史登记描述': region['description'], '用途': '区块身份背景；其中的即时状态属于登记当时，不代表本次或最后动作后的状态。实际变化按所附动作结果及其观察来源读取。'}, **summary_projection(region, records)}
    dynamic = json.dumps(user, ensure_ascii=False, indent=2)
    request = {'pipeline_step': 'discovery', 'stage': 'function_registration', 'role': 'function_registration', 'action_ready': False, 'system_prompt': text, 'user_prompt': dynamic, 'dynamic_prompt': dynamic, 'screenshots': [], 'image_refs': [], 'fixed_parts': parts, 'response_schema': request_schema(root, region, records), 'source': {'region': region['id'], 'observation': (state.get('observation') or {}).get('id'), 'evidence_digest': request_signature(region, records)}}
    from regrow.traversal.work_context import attach
    attach(request, records or {region['id']: region}, state)
    from regrow.records.environment_context import for_request
    from regrow.prompts.prompt_material import assign
    assign(request, {'应用操作树': for_request(request, records or {region['id']: region}, state)})
    return request

def commit(root, run, call):
    from regrow.traversal import register_update as _register_update
    from regrow.traversal import discovery_step as _discovery_step
    (q, reply) = _owner_submission(run, call)
    rid = q['source']['region']
    from regrow.recognition.control_indexes import decode
    reply = decode(q, reply)

    def mutate(records, state, snapshot, temp):
        if q.get('stage') != 'function_registration':
            raise ValueError('not a function registration request')
        if request_signature(records[rid], records) != q['source']['evidence_digest']:
            raise ValueError('function evidence changed since request')
        register(records[rid], reply, call, records)
    return _record_publish(run, 'functions-' + call, mutate)
