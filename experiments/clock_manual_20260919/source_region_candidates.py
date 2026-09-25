"""Read-only source-action recall and historical identity text."""
from copy import deepcopy
import json



def recall(records,binding,operation,attempt):
    owner=records.get(binding.get('region_ref'),{})
    control=binding.get('control_ref')
    confirmed=control in owner.get('controls',{}) and binding.get('association',{}).get('status')!='unconfirmed'
    rows=[]
    if confirmed:
        for ref,action in sorted(owner.get('actions',{}).items()):
            if ref>=attempt or action.get('control')!=control or action.get('operation')!=operation:
                continue
            if action.get('delivery')!='executed_receipt_zero':continue
            targets=[r for r in action.get('interactive_regions',[]) if r in records and r!=binding['region_ref']]
            changed={r['region'] for r in action.get('region_changes',[]) if r.get('state')=='changed_interactive'}
            targets.sort(key=lambda r:r not in changed)
            rows.append({'attempt':ref,'description':action.get('result',{}).get('description',''),
                         'destinations':targets,'changed':[r for r in targets if r in changed],
                         'result_call':action.get('evidence',{}).get('result_call'),
                         'after_observation':action.get('evidence',{}).get('after_observation')})
    rows=rows[-3:]
    destinations=list(dict.fromkeys(r for a in reversed(rows) for r in a['destinations']))
    return {'confirmed':confirmed,'actions':rows,'destinations':destinations}


def reference(records,snapshot,recalled,visual_hits,frame):
    # Same-entry changed surfaces first. Cross-entry visual matches remain valid
    # candidates even when this control has never visited their Region.
    changed=list(dict.fromkeys(r for a in reversed(recalled['actions']) for r in a['changed']))
    ordered=list(dict.fromkeys([*changed,*recalled['destinations'],
                               *(h['region_ref'] for h in visual_hits if h.get('region_ref') in records)]))
    if not ordered:return None
    # Historical text is evidence in its own right, independent of image eligibility.
    rid=ordered[0];region=records[rid]
    actions=[a for a in reversed(recalled['actions']) if rid in a['destinations']]
    observations=list(reversed(region.get('observations',[])))
    obs=next((o for a in actions for o in observations
              if a['result_call'] and a['after_observation']
              and o.get('evidence',{}).get('source_call')==a['result_call']
              and o.get('evidence',{}).get('observation')==a['after_observation']),
             observations[0] if not actions and observations else {})
    return {'region_ref':rid,'description':obs.get('description',region.get('description','')),
            'source_call':obs.get('evidence',{}).get('source_call')}


def describe(recalled,labels):
    return {'来源关联':'已确认同一控件与动作' if recalled['confirmed'] else '来源控件未确认；不按同入口推断落点',
            '历史结果':[{'动作':a['attempt'],'观察结果':a['description'],
                        '当时可交互区块':[labels[r] for r in a['destinations'] if r in labels]}
                       for a in recalled['actions']],
            '边界':'历史落点只是优先候选；不同入口也可到达同一区块，候选缺失不等于新区块。'}


def attach(request,reference,labels):
    if reference is None:return request
    label=labels.get(reference['region_ref'])
    if label is None:return request
    result=deepcopy(request)
    dynamic=json.loads(result['user_prompt'])
    dynamic['区块历史文字对照']={'候选':label,
                            '当时描述':reference['description'],'历史观察':reference['source_call'],
                            '用途':'历史身份文字参考，不附历史裁图，不证明当前可见、动作或任务完成。'}
    result['user_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    return result
