"""Detect repeated settled traversal states without additional model calls."""
import hashlib
import json
from pathlib import Path
import importlib.util


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def same_observation(a,b):
    return Path(a).read_bytes()==Path(b).read_bytes() or helper('visual_backtrack').same_surface(a,b)


def progress_key(records, *, navigation=False):
    rows={}
    for rid,r in records.items():
        edges=[]
        for a in r.get('actions',{}).values():
            edges.append(json.dumps([a.get('control'),a.get('operation'),a.get('interactive_regions'),a.get('result',{}).get('exception')],sort_keys=True))
        rows[rid]={'controls':sorted(r.get('controls',{})),
            'tasks':{n:{k:t.get(k) for k in (('status','handling') if navigation else ('status','handling','result_evidence'))} for n,t in r.get('tasks',{}).items()},
            'findings':{n:{f:{k:v.get(k) for k in ('domain','conditions')}
                for f,v in t.get('findings',{}).items()} for n,t in r.get('tasks',{}).items()},
            'edges':sorted(set(edges)),
            'function_review':r.get('function_inventory',{}).get('evidence_digest'),
            # Keep visible value changes as progress; image paths/call IDs are not progress.
            'values':{} if navigation else {c:(v.get('observations') or [{}])[-1].get('state') for c,v in r.get('controls',{}).items()}}
    return hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def observe(run,round_key):
    run=Path(run);repair=helper('step_repair')
    if any((run/p).exists() for p in ('pending_step.json','execution_pending.json','visual_navigation_pending.json')):return None
    _,records,state=helper('discovery_step').load(run)
    work=state.get('working_region')
    if work not in records:return None
    path=run/'exploration_loop.json'
    ledger=repair.read(path) if path.exists() else {'history':[]}
    if any(r['round']==str(round_key) for r in ledger['history']):return None
    row={'round':str(round_key),'work':work,'task':state.get('active_task'),
         'position':sorted(state.get('interactive_regions',[])),'mode':state.get('next_action_mode'),
         'progress':progress_key(records),
         'navigation_progress':progress_key(records,navigation=True),
         'task_progress':progress_key(records,navigation=True),
         'navigating':not state.get('active_task') and (work not in state.get('interactive_regions',[]) or state.get('next_action_mode') in ('recover','recover_scope','review_result'))}
    frame=Path(round_key)/'current.png'
    if frame.is_file():row['frame']=str(frame.resolve())
    last=state.get('last_action_result',{})
    action=records.get(last.get('region'),{}).get('actions',{}).get(last.get('action'))
    if action:
        owner=records[last['region']]
        row['recent_action_ref']=[last['region'],last['action']]
        row['recent_action']={'区块':owner['name'],
            '目标':owner.get('controls',{}).get(action.get('control'),{}).get('name') or action.get('association',{}).get('target','未关联控件'),
            '动作':action.get('operation'),'结果':action.get('result',{})}
    ledger['history']=(ledger['history']+[row])[-9:];repair.atomic(path,ledger)
    return detect(ledger['history'])


def detect(rows):
    for width in (1,2,3):
        window=rows[-3*width:]
        if len(window)!=3*width:continue
        key='task_progress' if any(r.get('task') for r in window) else 'navigation_progress' if any(r.get('navigating') or r.get('mode') in ('recover','recover_scope','review_result') for r in window) else 'progress'
        if len({json.dumps([r['work'],r['task'],r.get(key,r['progress'])],sort_keys=True) for r in window})!=1:continue
        locations=[(r['position'],r['mode']) for r in window]
        if locations[:width]==locations[width:2*width]==locations[2*width:]:
            if all(r.get('frame') and Path(r['frame']).is_file() for r in window):
                same=same_observation
                if not all(same(window[i]['frame'],window[i-width]['frame']) for i in range(width,len(window))):continue
            return {'kind':'exploration_loop','cycle_length':width,'repetitions':3,'history':window}
    return None


def correct(runner,evidence):
    repair=helper('step_repair');_,records,state=helper('discovery_step').load(runner.run)
    import uuid
    job={'path':'repair_episodes/'+uuid.uuid4().hex+'/episode.json','stage':'action','attempt':None,
        'request':{'source':{'region':state['working_region'],'task_region':state['working_region'],
        'task_name':(state.get('active_task') or {}).get('name')}},'status':'initial','history':[],
        'switch_trigger':evidence}
    runner.save(job);repair.atomic(Path(runner.run)/runner.pointer_name,{'episode':job['path']})
    runner.switch_branch(job)
