"""Read-only history: select related evidence, project provenance, render it.
No visibility inference, task mutation or navigation scheduling belongs here.
"""
import json
import importlib.util
from pathlib import Path

def sibling(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def with_task_frames(root, run, request, task, region):
    """Attach confirmed task attempts, including a single observed operation."""
    from copy import deepcopy
    import hashlib
    if task.get('status') != 'pending' or not task.get('control'):
        return request
    run = Path(run)
    attempts = []
    for ref in dict.fromkeys(task.get('attempts', [])):
        folder = run / 'action_attempts' / ref
        if not (folder / 'commit.json').is_file():
            continue
        try:
            binding = json.loads((folder / 'binding.json').read_text())
            receipt = json.loads((folder / 'receipt.json').read_text())
        except (OSError, ValueError):
            continue
        if (binding.get('region_ref'), binding.get('control_ref')) != (region, task['control']):
            continue
        if receipt.get('exit_code') == 0 and all((folder / (p + '.png')).is_file() for p in ('before', 'after')):
            attempts.append(ref)
    if not attempts:
        return request
    selected = ([(attempts[-2], 'after')] if len(attempts) > 1 else [])
    selected += [(attempts[-1], 'before'), (attempts[-1], 'after')]
    seen = {hashlib.sha256((run / frame).read_bytes()).digest()
            for frame in request['screenshots'] if (run / frame).is_file()}
    result = deepcopy(request)
    labels = []
    for ref, stage in selected:
        frame = Path('action_attempts') / ref / (stage + '.png')
        digest = hashlib.sha256((run / frame).read_bytes()).digest()
        if digest in seen:
            continue
        seen.add(digest)
        result['screenshots'].append(str(frame))
        labels.append(f"图{len(result['screenshots'])}：历史动作 {ref} 的{'前' if stage == 'before' else '后'}图")
    if not labels:
        return request
    dynamic = json.loads(result['user_prompt'])
    dynamic['历史原图对照'] = labels
    result['user_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    path = '共享/历史原图对照.prompt'
    text = (Path(root) / '遍历prompt' / path).read_text()
    result['fixed_parts'].append({'path': path, 'text': text})
    result['system_prompt'] += '\n\n' + text
    return result

def attempts(task, records):
    attempts = list(dict.fromkeys(task.get('attempts', [])))
    outcome = task.get('result_evidence')
    if task.get('status') == 'done':
        destinations=task.get('completion_basis',{}).get('destination_regions',[])
        if destinations:
            return ['历史结果：该入口当时打开'+ '、'.join('「'+records[r]['name']+'」' for r in destinations if r in records)+'。']
        return ['历史结算（当时的判断，不是本轮指令）：'+(outcome or '任务已登记完成，未提供结果说明')]
    if not attempts:
        return ['当前图中尚未执行此任务的动作']
    lines = []
    for ref in attempts:
        matches = [(r, r['actions'][ref]) for r in records.values() if ref in r.get('actions', {})]
        if len(matches) != 1:
            lines.append('已关联一次尝试，但动作记录缺失或不唯一，不能确认执行情况')
            continue
        region, action = matches[0]
        target = region.get('controls', {}).get(action.get('control'), {}).get('name', region.get('name', ''))
        delivery = '已执行' if action.get('delivery') == 'executed_receipt_zero' else '执行情况未确认'
        result = action.get('result', {}).get('description') or '尚无已登记的观察结果'
        if action.get('text_delivered') is False:result='文字尚未发送；'+result
        lines.append(f"{delivery} {action.get('operation') or '动作类型未登记'}「{target}」；观察：{result}")
    if task.get('ownership_history'):
        lines.append('归属纠正：'+ '、'.join(h['invalidated_attempt'] for h in task['ownership_history'] if h.get('invalidated_attempt'))+' 为原尝试审计引用，实际作用于其他控件，不支持本控件完成。')
    if outcome:
        lines.append('任务判断：' + outcome)
    return lines


def findings(records,state,task_region,name,task):
    candidates=[(task_region,name,task)]
    if task.get('control'):
        candidates.extend((task_region,n,t) for n,t in records[task_region].get('tasks',{}).items()
                          if n!=name and t.get('control')==task['control'])
    lines=[];refs=[]
    for rid,n,t in candidates:
        for key,fact in t.get('findings',{}).items():
            import json
            detail={'说明':fact.get('description',''),'已见取值':fact.get('domain',{}),
                    '适用条件':fact.get('conditions',[])}
            lines.append(f"- {records[rid]['name']} / {n} / {key}："+json.dumps(detail,ensure_ascii=False))
            refs.append({'region':rid,'task':n,'finding':key})
    return lines,refs



def identity_candidates(records,state,binding,visual_hits,source_destinations=None):
    """Disclose local identity context; backend matching still sees all records."""
    anchors={binding.get('region_ref'),binding.get('working_region'),binding.get('task_region'),
             *state.get('interactive_regions',[]),*state.get('region_path',[])[-1:]}
    selected=set(anchors)
    if source_destinations is not None:
        selected.update(source_destinations)
    else:
        for rid in anchors:
            for action in records.get(rid,{}).get('actions',{}).values():
                if rid!=binding.get('region_ref') or action.get('control')!=binding.get('control_ref'):continue
                selected.update(action.get('interactive_regions',[]))
    hit_ids=set()
    for hit in visual_hits:
        rid=hit.get('region_ref')
        if rid is None:
            matches=[k for k,r in records.items() if r['name']==hit['name']]
            rid=matches[0] if len(matches)==1 else None
        if rid in records:hit_ids.add(rid)
    def reasons(rid,r):
        why=[]
        if rid==binding.get('region_ref'):why.append('动作前来源')
        if rid in (binding.get('working_region'),binding.get('task_region')):why.append('未完成工作所属区块')
        if rid in state.get('interactive_regions',[]):why.append('动作前观察中的区块')
        if rid in hit_ids:why.append('截图外观匹配候选（不等于前景）')
        return why or ['相关历史去向或返回路径']
    return [{'region_ref':rid,'name':r['name'],'description':r['description'],'提供原因':reasons(rid,r),'当前状态':'未由这份历史记录确认',
             'controls':[{'name':c['name']} for c in r['controls'].values()],
             **({'行为适用上下文':r['behavior_context']} if r.get('behavior_context') else {}),
             **({'不可共享区块':[records[x['region']]['name'] for x in r['distinct_regions'] if x.get('region') in records]} if r.get('distinct_regions') else {})}
            for rid,r in records.items() if rid in selected or rid in hit_ids]



def disclose(region,control,records):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('shared_controls',Path(__file__).with_name('shared_controls.py'))
    shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
    hits=sibling('entry_evidence').known_entries(region,control,'click')
    return [{'已观察结果':h['description'],'已知目的区块':records.get(h['destination_region'],{}).get('name',h['destination_region']),
             '用途':'此入口无需重新验证；如需进入目的区块，应作为已知导航。'} for h in hits[-2:]]+shared.disclose(records,region['id'],control)


def related(region,control,records):
    """Recall same-name entry evidence for interpretation, never transfer status."""
    name=region['controls'][control]['name'].strip().casefold()
    if not name:return []
    rows=[]
    for other in records.values():
        if other.get('id')==region['id']:continue
        for cid,c in other.get('controls',{}).items():
            if c['name'].strip().casefold()!=name:continue
            for hit in sibling('entry_evidence').known_entries(other,cid,'click'):
                row={'来源区块':other['name'],'来源区块描述':other.get('description',''),
                     '入口':c['name'],'已观察结果':hit['description'],
                     '已知目的区块':records.get(hit['destination_region'],{}).get('name',hit['destination_region']),
                     '适用性':'同名召回，不是同一控件的证明；结合当前截图和用途判断，不转移执行记录。'}
                if row not in rows:rows.append(row)
    return rows


def task_goal(task, records, run=None):
    """Project evidence once per event; never infer causality or task completion."""
    from copy import deepcopy
    result={'type':task.get('task_type'),'reason':task['reason']}
    result['历史阅读']='已有参数发现是各属性最后登记的历史摘要，最新来源动作标明其时点；不是当前截图的同时状态，也不表示全部取值在该动作验证。参数观察以已有参数发现为基准，仅列不同字段；未列且不在原观察缺失字段中的字段沿用已有参数发现中的同名属性摘要，不继承上一事件；原观察缺失字段保持未知，不从最新摘要补齐。来源对象保留历史身份引用，不保证与动作入口相同。身份关联unconfirmed仅指后台控件绑定未确认，不否定动作投递或截图观察，须结合执行位置核对对象。按记录核对操作及后续观察；包含所引动作之间已登记的其他动作。没有实际记录的间隙不能视为没有操作。对象身份、适用条件或因果链不清楚时明确缺口，不推断成功。'
    refs=set(task.get('attempts',[])) | set(task.get('completion_basis',{}).get('attempts',[]));observations={};unlinked=[];facts={}
    invalid={h['invalidated_attempt'] for h in task.get('ownership_history',[]) if h.get('invalidated_attempt')}
    fields=('description','domain','conditions','evidence')
    for name,fact in task.get('findings',{}).items():
        facts[name]={k:deepcopy(fact[k]) for k in fields if k in fact}
        facts[name]['最新来源动作']=fact.get('source',{}).get('attempt')
        # Sources without an observation still anchor the real action chain.
        for source in [fact.get('source',{}),*fact.get('sources',[])]:
            if source.get('attempt'):refs.add(source['attempt'])
        for observation in fact.get('observations',[]):
            source=observation.get('source',{})
            value={k:deepcopy(observation[k]) for k in fields if k in observation}
            # Evidence belongs to this observation, not to the latest fact.
            if source.get('evidence'):value['evidence']=source['evidence']
            row={'属性':name,**{k:v for k,v in value.items() if v!=facts[name].get(k)}}
            missing=[k for k in fields if k not in value]
            if missing:row['原观察缺失字段']=missing
            identity={k:source[k] for k in ('region','task_region','control') if k in source}
            if identity:row['来源对象']=identity
            ref=source.get('attempt')
            if ref:
                refs.add(ref);bucket=observations.setdefault(ref,[])
            else:
                row['来源']=deepcopy(source);bucket=unlinked
            if row not in bucket:bucket.append(row)
    def order(ref):
        return (0,int(ref[1:])) if ref.startswith('a') and ref[1:].isdigit() else (1,ref)
    index={}
    for region in records.values():
        for ref,action in region.get('actions',{}).items():index.setdefault(ref,[]).append((region,action))
    # Keep intervening actions even when they served another task. No last-N cut.
    selected=set(refs)
    numeric=[ref for ref in refs if order(ref)[0]==0]
    if numeric:
        lo,hi=min(map(order,numeric)),max(map(order,numeric))
        selected.update(ref for ref in index if lo<=order(ref)<=hi)
    events=[]
    for ref in sorted(selected,key=order):
        row={'记录':ref,'关联':'原尝试审计引用：实际作用于其他控件，不支持本控件完成' if ref in invalid else '任务证据' if ref in refs else '期间其他动作'}
        matches=index.get(ref,[])
        if len(matches)!=1:
            row['缺口']='实际动作记录缺失或不唯一，不能确认执行或因果'
        else:
            region,action=matches[0];outcome=action.get('result',{});association=action.get('association',{})
            control=region.get('controls',{}).get(action.get('control'),{})
            row.update(区块=region['name'],入口=control.get('name') or association.get('target') or '未绑定控件',
                       动作=action.get('operation','未知'),执行=action.get('delivery','未确认'),
                       观察=outcome.get('description','尚无观察'),证据=outcome.get('evidence',''))
            if association:row['身份关联']=association.get('status','未确认')
            if outcome.get('exception') not in (None,'none'):row['异常']=outcome['exception']
            if action.get('text_delivered') is False:row['文字投递']='未发送'
            for key in ('text','executed_steps'):
                if key in action:row[key]=deepcopy(action[key])
            receipt_path=Path(run)/'action_attempts'/ref/'receipt.json' if run and Path(ref).name==ref else None
            if receipt_path and receipt_path.exists():
                receipt=json.loads(receipt_path.read_text())
                row['实际执行']=[{k:v for k,v in step.items() if k!='reason'} for step in receipt.get('executed_steps',[])]
                row['回执']={k:receipt[k] for k in ('exit_code','semantic_result','text_delivered') if k in receipt}
            elif action.get('executed_steps'):
                row['实际执行']=deepcopy(action['executed_steps'])
            if not row.get('实际执行'):row['执行明细缺口']='未提供保存的执行步骤，不能仅从动作意图推断具体投递'

        if observations.get(ref):row['参数观察']=observations[ref]
        events.append(row)
    if task.get('result_evidence'):
        result['原任务已有判断']={'所属动作':task.get('attempts',[])[-1] if task.get('attempts') else None,
                              '当时判断':task['result_evidence'],'用途':'历史判断，可依据后续或此前有效证据纠正，不是完成状态的保证'}
    # Put a bounded contiguous reading window first, not a claim of relevance
    # or success. Older events remain available in full, in chronological order.
    result['最近连续动作']=events[-8:]
    result['历史分段说明']='先核对最近连续动作，再按需回查此前动作；两段各按时间正序，全部已提供历史仍保留。最近8条只是阅读窗口，不是完整因果链或成功证据的保证。已有参数发现是各事件差异观察的属性基准。'
    result['此前动作与观察']=events[:-8]
    result['已有参数发现']=facts
    if unlinked:result['未关联动作的历史观察']=unlinked

    return result


def compact_update_prompt(request):
    """Change wire layout only; keep the complete decoded context and suffix.

    One historical fact/event per line avoids deeply indented repeated JSON
    scaffolding without selecting evidence or inventing semantic summaries.
    Called after platform decoration, so adapters cannot undo the layout.
    """
    if request.get('pipeline_step') != 'update':
        return request
    text=request.get('user_prompt','')
    try:
        value,end=json.JSONDecoder().raw_decode(text)
    except (ValueError,TypeError):
        return request
    if not isinstance(value,dict):
        return request
    def render(value,depth=0):
        compact=lambda item:json.dumps(item,ensure_ascii=False,separators=(',',':'))
        if depth>=3 or not isinstance(value,(dict,list)) or not value:
            return compact(value)
        pad='  '*(depth+1);close='  '*depth
        if isinstance(value,dict):
            rows=[pad+compact(key)+': '+render(item,depth+1) for key,item in value.items()]
            return '{\n'+',\n'.join(rows)+'\n'+close+'}'
        return '[\n'+',\n'.join(pad+render(item,depth+1) for item in value)+'\n'+close+']'
    return {**request,'user_prompt':render(value)+text[end:]}


def action_context(records,state,task_region,name,task):
    lines=['当前目标：'+name,'原任务目标与结束条件（仍用于本轮核对，其中界面描述属于建立时观察）：'+task['reason']]
    owner=records[task_region]
    lines+=['本任务已尝试什么、观察到什么（含跨区块步骤）：', *attempts(task,records)]
    lines.append('还缺什么：结合下面的已有事实核对原结束条件；pending只是登记状态，不证明必须再点一次。')
    history=[a for a in owner.get('actions',{}).values() if a.get('control')==task.get('control') and a.get('delivery')=='executed_receipt_zero']
    if history:
        lines.append('同一入口已有动作记录（不因新任务名称而清空）：')
        lines.extend('- '+a.get('result',{}).get('description','未提供结果') for a in history[-3:])
    resolved=[item for item in task.get('blocker_history',[]) if item.get('resolved_by')]
    if resolved and not task.get('blocker'):
        lines.append('历史阻塞已在后续观察中解除；当前是否可操作仍以截图为准。')
    ref=state.get('last_action_result') or {}
    recent=records.get(ref.get('region'),{}).get('actions',{}).get(ref.get('action'))
    evidence={'task':{'region':task_region,'name':name},'recent_action':None,'resolved_blockers':resolved}
    if recent:
        source=records[ref['region']]
        target=source.get('controls',{}).get(recent.get('control'),{}).get('name',source['name'])
        delivery='已执行' if recent.get('delivery')=='executed_receipt_zero' else '投递未确认'
        result=recent.get('result',{}).get('description') or '尚无已登记的观察结果'
        lines+=['最近已登记的尝试：',f"- {delivery} {recent.get('operation','动作')}「{target}」；观察：{result}"]
        evidence['recent_action']=dict(ref)
    else:lines.append('最近已登记的尝试：未提供关联的最近动作记录。')
    if task.get('result_evidence'):lines.append('原任务已有判断：'+task['result_evidence'])
    facts,evidence['known_findings']=findings(records,state,task_region,name,task)
    if facts:
        lines+=['已登记的相关属性（历史观察，不代表完整范围；用于判断还有什么新信息需要探索）：',*facts]
    lines.append('尚未完成：'+name if task.get('status')=='pending' else '任务登记状态：'+task.get('status','未提供'))
    if task_region not in state.get('interactive_regions',[]) and task.get('attempts'):
        lines.append('任务仍归原区块记录，但不要求返回原区块。依据已有结果从当前截图继续核验；不要为再次操作原入口而自动返回。')
    lines.append('先用已有尝试核对原结束条件。历史可能已回答原问题，或实际尝试后效果仍未确认且暂无有依据的新验证动作时，可用none、skip_task=false、request_task_review=true交第三步核对完成、继续或暂挂，说明已知事实和缺口；不为pending重复操作。有允许且有依据的准备或验证方法时继续一步；仅缺定位时用none补发现。')
    return '\n'.join(lines),evidence
