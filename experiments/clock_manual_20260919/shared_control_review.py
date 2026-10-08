"""Shared behavior conflicts: evidence, correction request and atomic member edits.

Uses the existing step-correction Runner; never dispatches GUI or rewrites an
actual attempt. Shared task projection and withdrawal belong to shared_tasks.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def signature(group):
    value = {k: group.get(k) for k in ('members', 'results')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def conflicts(records):
    return [{'owner': rid, 'name': name, 'signature': signature(group)}
            for rid, region in records.items()
            for name, group in region.get('shared_controls', {}).items()
            if group.get('status') == 'needs_review']


def current_group(records, case):
    group = records.get(case['owner'], {}).get('shared_controls', {}).get(case['name'])
    if not group or signature(group) != case['signature']:
        raise ValueError('共享证据已变化，请按最新记录重新核对')
    return group


def build_request(root, run, snapshot, records, state, case):
    group = current_group(records, case)
    frames = []
    facts = []
    for row in group['results']:
        src = row['source']; rid = src['region']
        action = records[rid]['actions'][src['attempt']]
        fact = {'区块': records[rid]['name'], '控件': records[rid]['controls'][src['control']]['name'],
                '动作': row['operation'], '适用条件':row.get('conditions',[]), '实际结果': row['description'], '观察依据': row['evidence'],
                '动作前上下文（历史登记）': [records[r]['name'] for r in action.get('evidence',{}).get('before_regions',[]) if r in records],
                '目的区块': [records.get(r, {}).get('name', r) for r in row['destination_regions']]}
        for key in ('before_image', 'after_image'):
            image = action.get('evidence', {}).get(key)
            if not image: continue
            image = str((snapshot / 'regions' / rid / image).resolve())
            if not Path(image).is_file(): continue
            if image not in frames: frames.append(image)
        facts.append(fact)
    members = [{'区块': records[m['region']]['name'], '控件': records[m['region']]['controls'][m['control']]['name']}
               for m in group['members'] if m['region'] in records and m['control'] in records[m['region']]['controls']]
    dynamic = {'待核对共享关系': group['name'], '原共享理由': group['reason'], '关联成员': members,
               '实际动作证据': facts, '框架发现的问题': '共享成员的结果不同或证据不完整；不同落点是核对线索，不直接证明语义不同。',
               '本轮目的': '核对共享是否成立，修订关系后由框架重新调度；不是执行新动作。',
               '证据边界': '本轮仅提供历史语义登记，未附图；观察依据中的图号来自旧记录。不能声称本轮看图确认了位置或归属，怀疑登记错误时说明需要哪项原始证据。'}
    path = '纠错/共享行为核对.prompt'; text = (Path(root) / '遍历prompt' / path).read_text()
    return {'role': 'step_correction', 'stage': 'shared_control_review', 'system_prompt': text,
            'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [],
            'image_refs': [], 'evidence_images': frames, 'response_schema': {'type': 'null'},
            'fixed_parts': [{'path': path, 'text': text}], 'shared_control_conflict': case,
            'source': {'snapshot': str(snapshot.relative_to(Path(run).resolve()))}}


def apply(records, state, case, item, call):
    import shared_controls
    group = current_group(records, case)
    if item['field'] != 'shared_behavior' or item['before'] != group['name'] or not item['evidence'].strip():
        raise ValueError('共享修订需shared_behavior、原关系名称及证据')
    members = [m for m in group['members'] if records.get(m['region'], {}).get('name') == item['region']
               and records[m['region']]['controls'].get(m['control'], {}).get('name') == item['control']]
    if len(members) != 1: raise ValueError('共享修订成员不在本轮范围或名称不唯一')
    member = members[0]
    affected = {(m['region'], m['control']) for m in group['members']}
    audit = {'member': deepcopy(member), 'decision': item['after'], 'evidence': item['evidence'],
             'source_call': call, 'signature': case['signature']}
    if item['after'] == 'shared':
        # Missing members cannot be repaired merely by asserting common behavior.
        if any(m['region'] not in records or m['control'] not in records[m['region']]['controls'] for m in group['members']):
            raise ValueError('共享成员缺失，不能直接确认')
        expected={'region':case['owner'],'name':case['name']}
        if any(records[m['region']]['controls'][m['control']].get('shared_control_ref')!=expected for m in group['members']):
            raise ValueError('共享成员引用断开，不能直接确认')
        if not group['results'] or any(r['exception']!='none' for r in group['results']):
            raise ValueError('缺少正常结果依据，不能直接确认共享')
        group['reviewed_signature'] = case['signature']
    elif item['after'] == 'independent':
        group['members'].remove(member)
        records[member['region']]['controls'][member['control']].pop('shared_control_ref', None)
        if len(group['members']) < 2:
            for m in group['members']:
                control=records.get(m['region'],{}).get('controls',{}).get(m['control'])
                if control:control.pop('shared_control_ref', None)
            group['status'] = 'separated'
        group.pop('reviewed_signature', None)
    else: raise ValueError('共享修订after只能是independent或shared')
    group.setdefault('reviews', []).append(audit)
    shared_controls.refresh(records)
    if item['after'] == 'independent':
        from shared_tasks import reconcile_detached_tasks
        reconcile_detached_tasks(records, state, affected, member, call)


def next_request(root, run):
    import discovery_step as discovery
    import shared_controls
    if any((Path(run) / p).exists() for p in ('execution_pending.json', 'visual_navigation_pending.json')): return None
    snapshot, records, state = discovery.load(run)
    shared_controls.refresh(records)
    cases = conflicts(records)
    if not cases: return None
    case = cases[0]
    # Persist withdrawn sharing coverage before offering any further action.
    discovery.publish(run, 'shared-conflict-' + case['signature'][:16], lambda *args: None)
    snapshot, records, state = discovery.load(run)
    return build_request(root, run, snapshot, records, state, case)


def run_pending(runner):
    import step_repair
    if step_repair.pending(runner.run, runner.pointer_name): return
    q = next_request(runner.root, runner.run)
    if q is not None:
        runner.perform('shared_control_review', q)
        raise step_repair.Paused('ready_next_round', '共享关系已核对并保存；下一轮按新记录调度，未执行GUI')


def inventory_request(root, snapshot, records, state):
    """Reuse historical inventory so repairing a relation needs no GUI detour."""
    from historical_inventory import region_request
    for rid, region in records.items():
        if region.get('out_of_scope_reason'): continue
        if region.get('task_inventory', {}).get('review', {}).get('kind') == 'shared_behavior':
            q = region_request(root, snapshot, records, state, rid)
            if q is not None: return q
    return None


def correction_request(root, job):
    """Only this error's manual, evidence and applicable output format reach Luna."""
    original=deepcopy(job['request'])
    path='纠错/共享行为核对.prompt'
    text=(Path(root)/'遍历prompt'/path).read_text()
    dynamic=json.loads(original['user_prompt'])
    if job.get('repairs',0):
        dynamic['上次修订被拒原因']=job.get('error')
        dynamic['上次修订回复']=job.get('last_shared_reply')
    if job.get('parse_failure'):
        dynamic['上次模型回复解析错误']=deepcopy(job['parse_failure'])
    edit={'type':'object','properties':{key:{'type':'string'} for key in ('region','control','field','before','after','evidence')},
          'required':['region','control','field','before','after','evidence'],'additionalProperties':False}
    edit['properties']['field']={'type':'string','enum':['shared_behavior']}
    edit['properties']['after']={'type':'string','enum':['independent','shared']}
    fields={'blocked_by':{'type':'string','enum':['none','shared_control_conflict']},'reason':{'type':'string'},
            'resolution':{'type':'string','enum':['edit_record','blocked']},'proposal':{'type':'null'},
            'record_edit':{'anyOf':[edit,{'type':'null'}]}}
    user=json.dumps(dynamic,ensure_ascii=False,indent=2)
    return {**original,'role':'step_correction','stage':'step_correction','original_request':original,
            'system_prompt':text,'user_prompt':user,'dynamic_prompt':user,'screenshots':[],'image_refs':[],
            'fixed_parts':[{'path':path,'text':text}],
            'response_schema':{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}}
