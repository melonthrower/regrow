"""Same-frame incremental discovery and bounded historical identity recall."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path


def tokens(text):
    text=text.casefold()
    words=set(re.findall(r'[a-z0-9]+',text))
    for s in re.findall(r'[\u4e00-\u9fff]+',text):
        words.update(s[i:i+2] for i in range(max(1,len(s)-1)))
    return words-{'the','of','and','code','vs','区块','当前','内容'}


def retrieve(records, queries, limit=5):
    scores={}
    for q in queries:
        query=q.get('previous_name') or q.get('name','')
        exact=[rid for rid,r in records.items() if query and query.casefold()==r['name'].casefold()]
        evidence=' '.join(q.get(k,'') or '' for k in ('identity_evidence','uncertainty','description')).casefold()
        mentions=[(rid,m.start(),m.end()) for rid,r in records.items() if r['name']
                  for m in re.finditer(r'(?<![a-z0-9])'+re.escape(r['name'].casefold())+r'(?![a-z0-9])',evidence)]
        # A shorter name embedded in a longer named candidate is not another mention.
        named=[rid for rid,start,end in mentions if not any(a<=start and end<=b and (a,b)!=(start,end) for _,a,b in mentions)]
        if exact or named:
            for rid in exact+named:scores[rid]=10
            continue
        a=tokens(query+' '+q.get('description','')+' '+q.get('icon_appearance',''))
        for rid,r in records.items():
            b=tokens(r['name']+' '+r.get('description','')+' '+' '.join(c['name'] for c in r.get('controls',{}).values()))
            score=len(a&b)/max(1,len(a))
            if score>=.25:scores[rid]=max(scores.get(rid,0),score)
    return sorted(scores,key=lambda rid:(-scores[rid],rid))[:limit]


def partition(reply):
    accepted=deepcopy(reply);rs=reply['regions'];cs=reply['controls']
    withheld={i for i,r in enumerate(rs) if r['identity']=='uncertain'}
    for _ in rs:
        withheld.update(i for i,r in enumerate(rs) if r.get('parent_index') in withheld)
    keep=[i for i in range(len(rs)) if i not in withheld];indices={i:j for j,i in enumerate(keep)}
    accepted['regions']=[deepcopy(rs[i]) for i in keep]
    for r in accepted['regions']:
        if r.get('parent_index') is not None:r['parent_index']=indices[r['parent_index']]
    accepted['controls']=[];ck=[];gaps=[]
    for i in sorted(withheld):gaps.append({'kind':'region','index':i,'proposal':deepcopy(rs[i]),'name':rs[i]['name']})
    for i,c in enumerate(cs):
        if c['region_index'] in withheld or c['identity']=='uncertain':
            gaps.append({'kind':'control','index':i,'proposal':deepcopy(c),'name':c.get('name',c.get('text','')),'owner':rs[c['region_index']]['name']})
        else:
            c=deepcopy(c);c['region_index']=indices[c['region_index']];accepted['controls'].append(c);ck.append(i)
    for g in gaps:
        g['item']=('区块：' if g['kind']=='region' else '控件：'+g['owner']+' → ')+g['name']
    seen=set()
    for g in gaps:
        if g['item'] in seen:g['item']+=f"（原报告第{g['index']+1}项）"
        seen.add(g['item'])
    for r in accepted['regions']:
        if not r.get('out_of_scope_reason') and any(g.get('owner')==r['name'] for g in gaps):r['controls_complete']=False
    return accepted,gaps


def resolve_gaps(pending,updates,reply):
    labels=[x['item'] for x in updates]
    if len(set(labels))!=len(labels) or set(labels)!={g['item'] for g in pending}:
        raise ValueError('每个旧缺口必须明确处理一次；省略不能视为解决')
    safe_regions={i for i,r in enumerate(reply['regions']) if r['identity']!='uncertain'}
    for _ in reply['regions']:
        safe_regions={i for i in safe_regions if reply['regions'][i].get('parent_index') is None or reply['regions'][i]['parent_index'] in safe_regions}
    safe_controls={i for i,c in enumerate(reply['controls']) if c['identity']!='uncertain' and c['region_index'] in safe_regions}
    remaining=[]
    for old,u in zip(sorted(pending,key=lambda x:x['item']),sorted(updates,key=lambda x:x['item'])):
        if not u['evidence'].strip():raise ValueError('缺口处理需要证据')
        ri,ci=u['region_index'],u['control_index']
        if u['resolution']=='registered':
            if old['kind']=='region':ok=ci is None and ri in safe_regions
            else:ok=ri is None and ci in safe_controls
            if not ok:raise ValueError('缺口不能关联到未确认或错误种类的对象')
        elif u['resolution']=='excluded':
            if ri is not None or ci is not None:raise ValueError('排除的缺口不应引用登记索引')
        else:
            retained=deepcopy(old)
            if ri is not None or ci is not None:
                rows=reply['regions'] if old['kind']=='region' else reply['controls']
                index=ri if old['kind']=='region' else ci
                if (ci if old['kind']=='region' else ri) is not None or index is None or not 0<=index<len(rows):raise ValueError('未解决缺口的补充索引无效')
                retained.update(proposal=deepcopy(rows[index]),index=index)
            remaining.append(retained)
    return remaining


def extend_schema(schema):
    # A resumed historical request may predate the required inventory flag.
    region=schema['properties']['regions']['items']
    if 'controls_complete' in region['properties']:
        region['required']=list(dict.fromkeys(region['required']+['controls_complete']))
    schema['properties']['completion_updates']={'type':'array','items':{'type':'object','additionalProperties':False,
        'properties':{'item':{'type':'string'},'resolution':{'type':'string','enum':['registered','excluded','unresolved']},
            'region_index':{'type':['integer','null']},'control_index':{'type':['integer','null']},'evidence':{'type':'string'}},
        'required':['item','resolution','region_index','control_index','evidence']}}
    schema['required']=list(dict.fromkeys(schema['required']+['completion_updates']))


def fingerprint(frame):return hashlib.sha256(Path(frame).read_bytes()).hexdigest()


def scoped_batch(records,batch):
    batch=deepcopy(batch)
    kept=[]
    for gap in batch.get('pending',[]):
        owners=[rid for rid in batch.get('regions',[]) if records.get(rid,{}).get('name')==gap.get('owner')]
        if gap.get('kind')=='control' and len(owners)==1 and records[owners[0]].get('out_of_scope_reason'):
            batch.setdefault('excluded_gaps',[]).append({**gap,'owner_region':owners[0],'reason':records[owners[0]]['out_of_scope_reason']})
        else:kept.append(gap)
    batch['pending']=kept
    return batch


def supplement(root,records,state,frame):
    batch=state['discovery_completion']
    if str(Path(frame).resolve())!=batch['frame'] or fingerprint(frame)!=batch['sha256']:
        raise ValueError('补全截图已变化，不能复用旧登记回执')
    q=deepcopy(batch['request']);ctx=q['discovery_context'];names={}
    queries=[g['proposal'] for g in batch['pending']]
    ids=retrieve(records,queries)
    from region_candidate_names import candidates
    from history_matching import with_history
    describe=with_history if ctx['mode']!='local' else candidates
    rows,names=describe(records,[{'region_ref':rid,'name':records[rid]['name'],
        '提供原因':['按缺口文字检索；仍须核对当前截图'],
        '当前状态':'未定位；仅供身份核对'} for rid in ids])
    receipt=[]
    for rid in batch['regions']:
        r=records[rid];label=next((n for n,k in names.items() if k==rid),r['name'])
        base=label;n=1
        while label in names and names[label]!=rid:
            n+=1;label=f'{base}（已登记{n}）'
        names[label]=rid
        receipt.append({'区块':label,'已登记控件':[c['name'] for cid,c in r['controls'].items() if cid in batch['controls']]})
    ctx['region_names']=names
    ctx['completion']=True
    # Control identity stays scoped to the original local owner.
    focus=ctx.get('focus');prior_controls=list(ctx.get('control_names',{}).values());ctx['control_names']={}
    controls=records.get(focus,{}).get('controls',{}) if ctx['mode']=='local' else {}
    selected=retrieve({k:{'name':c['name'],'description':' '.join(v.get('icon_description','') for v in c.get('observations',[])[-1:])} for k,c in controls.items()},queries)
    selected=list(dict.fromkeys(selected+[k for k in prior_controls+batch['controls'] if k in controls]))
    for cid in selected:
        c=controls[cid]
        label=c['name'];n=1
        while label in ctx['control_names']:n+=1;label=f"{c['name']}（候选{n}）"
        ctx['control_names'][label]=cid
    dynamic={'本轮定位区块':records.get(focus,{}).get('name'),'已实际登记':receipt,
        '待补事项':[{'item':g['item'],'description':g['proposal'].get('description',g['proposal'].get('identity_evidence',''))} for g in batch['pending']],
        '相关历史候选':rows,'本区块控件身份候选':list(ctx['control_names']),
        '检索边界':('重定位包含全部历史身份；局部补全仅提供缺口相关身份。均不证明当前可见，不能凭名称自动认定身份。'),
        '用途':'沿用原截图补交未登记内容，并检查原观察范围是否还有遗漏；已登记内容只需在作为容器或消除重复缺口时以same引用，不是重新提交整屏。'}
    if ctx.get('partition_context'):
        from local_partition import prompt
        dynamic['同帧已确认区块划分']=prompt(ctx['partition_context'],completion=True)
    for part in q.get('fixed_parts',[]):
        part['text']=(Path(root)/'遍历prompt'/part['path']).read_text()
    if q.get('fixed_parts'):q['system_prompt']='\n\n'.join(p['text'] for p in q['fixed_parts'])
    manual=(Path(root)/'遍历prompt/发现手册/增量补全.prompt').read_text()
    q['system_prompt']+='\n\n'+manual
    q.setdefault('fixed_parts',[]).append({'path':'发现手册/增量补全.prompt','text':manual})
    q['user_prompt']=q['dynamic_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    q['screenshots']=[frame];extend_schema(q['response_schema'])
    import history_matching
    ranking=history_matching.scan({rid:records[rid] for rid in names.values()},None,frame)
    return history_matching.attach(q,records,ranking,names)


def prepare_registration(reply,request,known,batch,diagnostics):
    report=diagnostics.collect('discovery',request,reply,known)
    allowed={'region_identity','control_identity','unknown_region','unknown_candidate_control','existing_control_conflict'}
    if report['errors']:
        # Only identity-uncertain objects may be withheld; other invalid data still rejects.
        for e in report['errors']:
            path=e['path'].split('/')
            group=path[1] if len(path)>2 else '';idx=int(path[2]) if len(path)>2 and path[2].isdigit() else -1
            if e['code'] not in allowed or group not in ('regions','controls') or idx<0 or reply[group][idx].get('identity')!='uncertain':
                raise diagnostics.Rejected(report)
    accepted,gaps=partition(reply)
    if gaps and not accepted['regions'] and not batch:
        raise ValueError('本批没有可独立登记的身份；需核对相关候选')
    remaining=resolve_gaps(batch['pending'],reply.get('completion_updates',[]),reply) if batch else []
    addressed={(u['region_index'],u['control_index']) for u in reply.get('completion_updates',[]) if u['resolution']=='unresolved' and (u['region_index'] is not None or u['control_index'] is not None)}
    for g in gaps:
        if (g['index'] if g['kind']=='region' else None,g['index'] if g['kind']=='control' else None) in addressed:continue
        label=g['item'];n=1
        while any(x['item']==g['item'] for x in remaining):
            n+=1;g['item']=f'{label}（补充待核对{n}）'
        remaining.append(g)
    for key in ('completion_updates',):accepted.pop(key,None)
    q=deepcopy(request);q.pop('response_schema',None)
    diagnostics.check('discovery',q,accepted,known)
    rm=[];cm=[]
    withheld={g['index'] for g in gaps if g['kind']=='region'}
    withheld_controls={g['index'] for g in gaps if g['kind']=='control'}
    rm=[i for i in range(len(reply['regions'])) if i not in withheld]
    cm=[i for i in range(len(reply['controls'])) if i not in withheld_controls]
    if batch:
        registered_names={known[r]['name'] for r in batch['regions']}
        if any(r['identity']=='new' and r['name'] in registered_names for r in accepted['regions']):
            raise ValueError('已登记区块应使用same引用；不同对象需给出可区分名称')
        for c in accepted['controls']:
            region=accepted['regions'][c['region_index']]
            rid=request['discovery_context']['region_names'].get(region.get('previous_name'))
            cid=request['discovery_context']['control_names'].get(c.get('previous_name'))
            group=c.get('list_group')
            if group and any(k in batch['controls'] and k!=cid and old.get('list_group')==group for k,old in known.get(rid,{}).get('controls',{}).items()):
                raise ValueError('同一观察的同类列表已有代表控件；补交不能重复登记')
    return accepted,remaining,rm,cm


def recall_into_request(q,records,queries):
    """Repair observation recalls named missing objects, not the entire graph."""
    ctx=q['discovery_context'];dynamic=json.loads(q['user_prompt'])
    rows=dynamic.setdefault('程序匹配候选',[])
    for rid in retrieve(records,queries):
        if rid in ctx['region_names'].values():continue
        r=records[rid];label=r['name'];n=1
        if any(x['name']==label for k,x in records.items() if k!=rid):label+=' — '+r.get('description','')
        base=label
        while label in ctx['region_names']:n+=1;label=f'{base}（候选{n}）'
        ctx['region_names'][label]=rid
        rows.append({'名称':label,'历史描述':r.get('description',''),'区块图匹配':{'匹配说明':'按未确认对象召回的历史身份；不是当前视觉匹配','候选位置':[]},'定位锚点':[]})
    dynamic.pop('省略的候选数量',None)
    dynamic['历史检索范围']='保留本轮视觉候选，仅额外召回与未确认对象相关的少量历史；未召回不证明对象不存在。'
    q['user_prompt']=q['dynamic_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    return q
