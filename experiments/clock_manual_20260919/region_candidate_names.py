import control_history_context
"""Per-request readable identity labels, shared by disclosure and binding."""
from collections import Counter
from copy import deepcopy
from region_functions import incoming_results


def candidates(records, rows):
    counts=Counter(r['name'] for r in records.values());out=[];mapping={}
    selected={}
    for row in rows:
        rid=row.get('region_ref')
        if rid in records:selected[rid]=row
        elif rid is None:
            # Old name-only rows can recall history, never assign their evidence
            # to several records with the same name.
            matches=[k for k,r in records.items() if r['name']==row['name']]
            for k in matches:
                selected.setdefault(k,row if len(matches)==1 else {'name':row['name'],'提供原因':['仅同名历史候选；无本轮匹配证据']})
    used=set(r['name'] for r in records.values())
    for rid in sorted(selected):
        r=records[rid];label=r['name']
        if counts[label]>1:
            label+=' — '+(r.get('description','').strip() or '描述未提供')
            base=label;index=1
            while label in used:
                index+=1;label=f'{base}（候选{index}）'
        used.add(label);mapping[label]=rid
        row=deepcopy(selected[rid]);row.pop('region_ref',None)
        row.update(name=label,description=r.get('description',''),
            controls=[control_history_context.describe(r,cid) for cid in r.get('controls',{})])
        entered=incoming_results(r,records)
        if entered:
            row['历史进入记录（不证明当前可见或行为等价）']=entered
        if r.get('behavior_context'):row['行为适用上下文']=r['behavior_context']
        if r.get('distinct_regions'):
            row['不可共享区块']=[records[x['region']]['name'] for x in r['distinct_regions'] if x.get('region') in records]
        if counts[r['name']]>1:row['历史名称']=r['name']
        out.append(row)
    return out,mapping


def resolve(records,name,mapping=None):
    if mapping:
        rid=mapping.get(name)
        if rid in records:return rid
    matches=[rid for rid,r in records.items() if r['name']==name]
    if len(matches)!=1:raise ValueError('unknown or ambiguous name: '+name)
    return matches[0]
