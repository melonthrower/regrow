"""Candidate-loadable graph progress; no scheduling or GUI effects."""
from pathlib import Path
import hashlib,json
from debug_loop import read,helper,ROOT

def graph_summary(run,source=ROOT):
    run=Path(run);pointer=read(run/'knowledge_current.json',{})
    if not pointer:return {'complete':False,'regions':0,'done':0,'pending':0,'blocked':0,'gaps':['no_graph']}
    base=run/pointer['snapshot'];records={p.parent.name:read(p) for p in (base/'regions').glob('*/region.json')}
    tasks=helper(source,'region_tasks');functions=helper(source,'region_functions')
    result={'regions':len(records),'done':0,'pending':0,'blocked':0,'gaps':[],'excluded':0}
    for rid,r in records.items():
        if r.get('out_of_scope_reason'):
            result['excluded']+=1
            continue
        c=tasks.coverage(r,records);result['pending']+=len(c['pending']);result['blocked']+=len(c['blocked'])
        functional=functions.review_current(r,records)
        if c['complete'] and functional and not r.get('registration_gaps'):result['done']+=1
        else:result['gaps'].append({'region':rid,'inventory':c['inventory_complete'],'functions':functional,'registration_gaps':r.get('registration_gaps',{})})
    unsettled=[p for p in ('execution_pending.json','pending_step.json','ownership_review.json') if (run/p).exists()]
    state=read(base/'runtime_state.json',{})
    if state.get('next_action_mode') in ('recover','recover_scope','review_result','discover'):unsettled.append(state['next_action_mode'])
    result['unsettled']=unsettled
    result['complete']=bool(records) and result['done']+result['excluded']==len(records) and not unsettled
    # Ignore observation IDs, descriptions and repeat screenshots as progress.
    semantic={rid:{'excluded':bool(r.get('out_of_scope_reason')),'controls':sorted(r.get('controls',{})),'tasks':{n:{k:t.get(k) for k in ('status','handling')} for n,t in r.get('tasks',{}).items()},'functions':sorted(r.get('functions',{})),'function_review_current':functions.review_current(r,records),'transitions':[{k:t.get(k) for k in ('source_control','action','target_region','destination','returns_to_previous')} for t in r.get('transitions',[])],'inventory':r.get('task_inventory',{}).get('inventory')} for rid,r in records.items()}
    result['progress_key']=hashlib.sha256(json.dumps(semantic,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return result
