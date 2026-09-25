"""Isolated current-image observation followed by mandatory local decisions.

No GUI, production ledger, or verified identity. Fixed five-frame/ten-request cap.
"""
from collections import defaultdict
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import time

from tools.luna_inventory_probe import obj, TEXT, SCHEMA, PROMPT, merge_observation, save


def controls(view):
    return {f'{ref}:{i}': c for ref,r in view.get('regions', {}).items() for i,c in enumerate(r['controls'])}


def questions_for(previous, current):
    qs = {'foreground': dict(kind='foreground', refs=list(controls(current)), question='逐项核对当前接管输入的前景，只填给定控件编号，列出背景/不可见控件和无法确定的控件；没有则空数组，不填写系统栏等描述。')}
    siblings = defaultdict(list)
    for ref,r in current['regions'].items():
        if len(r['controls']) >= 2:
            qs[f'partition_{ref}'] = dict(kind='partition', refs=[ref], controls=[f'{ref}:{i}' for i in range(len(r['controls']))],
                question='该区是否包含共同显隐的独立编辑子任务，或固定导航/提交区与被替换的功能内容？keep保留，split列出独立子组及已有控件编号，uncertain待确认。不按按钮数量硬拆。')
            siblings[(r['parent_ref'], tuple(sorted(c['kind'] for c in r['controls'])))].append(ref)
        labels = {c['label'] for c in r['controls'] if c['label']}
        candidates = []
        for old_ref,old in previous.get('regions', {}).items():
            old_labels = {c['label'] for c in old['controls'] if c['label']}
            overlap = len(labels & old_labels)
            if overlap >= 2:
                candidates.append((overlap / max(len(labels), len(old_labels)), old_ref))
        if candidates:
            refs = [x[1] for x in sorted(candidates, reverse=True)[:2]]
            qs[f'identity_{ref}'] = dict(kind='identity', refs=[ref], candidates=refs,
                question='只判断是否同一功能组件；同位置或同父区不足以合并不同功能字段。选旧ref/new/uncertain并给视觉依据。此判定不复制历史控件。')
    for refs in siblings.values():
        if len(refs) >= 2:
            qs[f'repeated_{refs[0]}'] = dict(kind='repeated', refs=refs,
                question='这些同父区、控件类型结构重复的区域，是一个列表的数据成员(same_list)，还是独立功能区(keep_separate)，或uncertain？必须回答。same_list保留每个物理控件和成员来源。')
    return qs


def answer_schema(qs):
    result = {}
    for key,q in qs.items():
        if q['kind']=='foreground':
            refs={'type':'array','items':{'type':'string','enum':q['refs'] or ['__none__']}}
            if not q['refs']:refs['maxItems']=0
            result[key]=obj(dict(excluded=refs, uncertain=refs, evidence=TEXT))
        else:
            choices = {'partition':['keep','split','uncertain'], 'repeated':['same_list','keep_separate','uncertain'],
                       'identity':['new','uncertain']+q.get('candidates', [])}[q['kind']]
            fields=dict(choice={'type':'string','enum':choices}, evidence=TEXT)
            if q['kind']=='partition':
                group=obj(dict(label=TEXT,function=TEXT,controls={'type':'array','items':{'type':'string','enum':q['controls']}}))
                fields['groups']={'type':'array','items':group}
            result[key]=obj(fields)
    return obj(result)


def apply_answers(current, qs, answers):
    if set(answers) != set(qs):
        raise ValueError('every question must be answered exactly once')
    known_controls=controls(current)
    result=deepcopy(current)
    foreground=answers['foreground']
    excluded,unknown=foreground['excluded'],foreground['uncertain']
    if not set(excluded+unknown) <= set(known_controls) or set(excluded)&set(unknown):
        raise ValueError('foreground references must be existing and unambiguous')
    if any(not a['evidence'].strip() for a in answers.values()):
        raise ValueError('every decision requires evidence')
    unresolved=list(current.get('uncertain', []))
    if unknown:unresolved.append('uncertain foreground: '+','.join(unknown))
    claimed=set()
    for key,q in qs.items():
        if q['kind']=='foreground':continue
        a=answers[key]
        allowed=answer_schema({key:q})['properties'][key]['properties']['choice']['enum']
        if a['choice'] not in allowed:raise ValueError('invalid choice')
        if a['choice']=='uncertain':unresolved.append(key)
        if a['choice']!='split' and a.get('groups'):raise ValueError('only split may supply child groups')
        if a['choice']=='split':
            source=q['refs'][0]
            if not a['groups']:raise ValueError('split requires child groups')
            for group in a['groups']:
                ids=group['controls']
                allowed_ids={f'{source}:{i}' for i in range(len(current['regions'][source]['controls']))}
                if not ids or len(ids)!=len(set(ids)) or not set(ids)<=allowed_ids or set(ids)&(claimed|set(excluded)):
                    raise ValueError('split controls must be existing, unique, in source, and foreground')
                claimed.update(ids)
                ref=f'r{result["next_id"]}';result['next_id']+=1
                result['regions'][ref]=dict(parent_ref=source,label=group['label'],function=group['function'],
                    controls=[deepcopy(known_controls[c]) for c in ids], control_sources=ids)
    for ref,r in current['regions'].items():
        ids=[f'{ref}:{i}' for i in range(len(r['controls'])) if f'{ref}:{i}' not in claimed|set(excluded)]
        result['regions'][ref]['controls']=[deepcopy(known_controls[c]) for c in ids]
        result['regions'][ref]['control_sources']=ids
    for key,q in qs.items():
        if q['kind']!='repeated' or answers[key]['choice']!='same_list':continue
        refs=q['refs'];members=[result['regions'].pop(ref) for ref in refs]
        ref=f'r{result["next_id"]}';result['next_id']+=1
        result['regions'][ref]=dict(parent_ref=members[0]['parent_ref'],label='',function='重复成员列表',
            controls=[c for r in members for c in r['controls']],
            control_sources=[c for r in members for c in r['control_sources']],
            members=[dict(source_ref=old,label=r['label'],function=r['function']) for old,r in zip(refs,members)])
        for r in result['regions'].values():
            if r['parent_ref'] in refs:r['parent_ref']=ref
    result.update(excluded_controls=excluded,uncertain=unresolved,complete=bool(current['complete'] and not unresolved),
        identity_verified=False,identity_proposals={k:a for k,a in answers.items() if qs[k]['kind']=='identity'})
    return result


RELATION_PROMPT='''你只回答框架列出的局部问题，不重写清单，不新增控件，不执行GUI。每个问题必须有明确choice和基于图的evidence；无法确定选uncertain。当前控件来自图1，历史候选来自图2（若有），二者不要混淆。
分区依据共同显隐、独立编辑任务、固定导航与替换内容的边界，不按边框/控件数量机械拆分。同一列表的重复数据成员合为一个列表区，保留物理控件。内联展开的完整编辑任务应形成来源区的子区。split时只列需要移动的已有控件编号，未列控件留原区。非split的groups必须为空。
排除当前接管输入的前景之后的窗口、系统栏及键盘；前景禁用控件仍保留。文本形式不证明不可交互。historical候选仅用于同一功能组件的身份判断，不能补进当前清单。
'''


def run(manifest, output, request_limit=10):
    from gui_rewalk.src.core.explore import agent as transport
    from gui_rewalk.src.core.explore.api_config import load_explore_api_config,local_explore_api_config_path
    cases=json.loads(Path(manifest).read_text())
    if not 1<=len(cases)<=5 or not 1<=request_limit<=10:raise ValueError('one to five cases; request limit 1..10')
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    frames={c['name']:Path(c['screenshot']).read_bytes() for c in cases}
    save(out/'manifest.json',[dict(c,sha256=hashlib.sha256(frames[c['name']]).hexdigest()) for c in cases])
    for path in [Path(__file__),Path('tools/luna_inventory_probe.py')]:
        (out/path.name).write_bytes(path.read_bytes())
    cfg=load_explore_api_config(local_explore_api_config_path())
    agent=transport.OpenAIAPIExplorerAgent(base_url=cfg.base_url,api_key=cfg.api_key,model='gpt-5.6-luna',
        reasoning_effort='medium',output_root=str(out),timeout=cfg.timeout_seconds)
    http=[];active='';native=transport.requests.post
    class ProbeStop(BaseException):pass
    def post(*args,**kwargs):
        if len(http)>=request_limit or any(r['call']==active for r in http) or (out/'STOP').exists():
            raise ProbeStop('budget/STOP/no retry')
        if kwargs['json']['model']!='gpt-5.6-luna':raise ProbeStop('Luna only')
        kwargs['json']['max_output_tokens']=6500
        row=dict(call=active,started=time.time());http.append(row);save(out/'http.json',http)
        try:
            response=native(*args,**kwargs);body=response.json()
            row.update(status=response.status_code,usage=body.get('usage'),model=body.get('model'))
            return response
        finally:row['seconds']=time.time()-row['started'];save(out/'http.json',http)
    transport.requests.post=post
    previous={};previous_frame=None;previous_group=None;counter=1;results=[]
    save(out/'status.json',dict(status='running',http_limit=request_limit,new_gui_actions=0))
    try:
        for case in cases:
            name=case['name'];frame=frames[name];folder=out/name;folder.mkdir()
            if case['group']!=previous_group:previous={};previous_frame=None
            previous_group=case['group']
            (folder/'current.png').write_bytes(frame)
            active=name+'_observe';print('CALL',active,flush=True)
            prompt=PROMPT+'\n本轮是独立当前图观察，previous为空；所有source_ref为空，reuse为空。不引用任何历史。'
            save(folder/'observe_request.json',dict(prompt=prompt,input={},schema=SCHEMA))
            if case.get('observation_source'):
                source=Path(case['observation_source'])
                if (source.parent/'current.png').read_bytes()!=frame:raise ValueError('cached observation must match exact screenshot')
                raw=json.loads(source.read_text())
                save(folder/'observation_source.json',dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),new_http=False))
            else:
                raw=agent._call(role='luna_current_observation',system_prompt=prompt,user_prompt='仅根据当前截图观察。',screenshots=[frame],response_schema=SCHEMA)
            save(folder/'observe_response.json',raw)
            current=merge_observation(dict(next_id=counter),raw);save(folder/'observation.json',current)
            qs=questions_for(previous,current)
            payload=dict(questions=qs,current=current,control_refs=controls(current),historical=previous)
            text=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
            if len(text.encode())>24000:raise ProbeStop('context limit')
            active=name+'_relate';print('CALL',active,flush=True)
            schema=answer_schema(qs);save(folder/'relation_request.json',dict(prompt=RELATION_PROMPT,input=payload,schema=schema))
            images=[frame]+([previous_frame] if previous_frame is not None else [])
            if previous_frame is not None:(folder/'historical.png').write_bytes(previous_frame)
            answers=agent._call(role='luna_local_relations',system_prompt=RELATION_PROMPT,user_prompt=text,screenshots=images,response_schema=schema)
            save(folder/'relation_response.json',answers)
            try:
                result=apply_answers(current,qs,answers)
            except ValueError as exc:
                save(folder/'rejected.json',dict(error=str(exc),published=False))
                result=current;result['complete']=False;result['uncertain'].append('relation contract rejected')
            save(folder/'after.json',result)
            results.append(dict(name=name,regions=len(result['regions']),controls=sum(len(r['controls']) for r in result['regions'].values()),
                uncertain=result['uncertain'],complete=result['complete']))
            save(out/'results.json',results)
            previous=result;previous_frame=frame;counter=result['next_id']
        unchanged=all(hashlib.sha256(Path(c['screenshot']).read_bytes()).hexdigest()==c['sha256'] for c in json.loads((out/'manifest.json').read_text()))
        save(out/'status.json',dict(status='finished',http_requests=len(http),new_gui_actions=0,source_unchanged=unchanged,identity_verified=False))
    except BaseException as exc:
        save(out/'status.json',dict(status='stopped',http_requests=len(http),error_type=type(exc).__name__,new_gui_actions=0))
        raise
    finally:transport.requests.post=native


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--request-limit',type=int,default=10)
    args=parser.parse_args();run(args.manifest,args.output,args.request_limit)
