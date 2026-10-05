"""Read-only history: select related evidence, project provenance, render it.
No visibility inference, task mutation or navigation scheduling belongs here.
"""
import control_history_context
import json
import importlib.util
from pathlib import Path
from history_selection import task_attempts

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
        lines=['历史结算（当时的判断，不是本轮指令）：'+(outcome or '任务已登记完成，未提供结果说明')]
        destinations=task.get('completion_basis',{}).get('destination_regions',[])
        if destinations:
            lines.append('动作后观察到的区块（不替代原任务结果）：'+ '、'.join('「'+records[r]['name']+'」' for r in destinations if r in records)+'。')
        return lines
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
             'controls':[control_history_context.describe(r,cid) for cid in r['controls']],
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
    result['历史阅读']='来源对象保留历史身份引用，不保证与动作入口相同。身份关联unconfirmed仅指后台控件绑定未确认，不否定动作投递或截图观察。仅展开任务引用的努力与反馈；未展开的其他历史仍留档，不能推断期间没有其他动作。对象身份、适用条件或因果链不清楚时明确缺口，不推断成功。'
    refs=task_attempts(task);observations={};unlinked=[];facts={}
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
    # References carry causality; numerical intervals do not.
    selected=set(refs)
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
            import page_history
            row.update(page_history._execution(action,ref,run))
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
    if facts:result['历史阅读']='已有参数发现是各属性最后登记的历史摘要，最新来源动作标明其时点；不是当前截图的同时状态，也不表示全部取值在该动作验证。参数观察以已有参数发现为基准，仅列不同字段；未列且不在原观察缺失字段中的字段沿用已有参数发现中的同名属性摘要，不继承上一事件；原观察缺失字段保持未知，不从最新摘要补齐。'+result['历史阅读']
    else:result['历史分段说明']=result['历史分段说明'].removesuffix('已有参数发现是各事件差异观察的属性基准。')
    if unlinked:result['未关联动作的历史观察']=unlinked

    return result


def action_context(records,state,task_region,name,task):
    lines=['当前目标：'+name,'探索说明（建立任务时的观察，不代表效果已实现）：'+task['reason']]
    lines.append('任务合同：'+json.dumps({'动作':task.get('action'),'类型':task.get('task_type'),
        '处理方式':task.get('handling'),'覆盖任务':task.get('equivalent_to')},ensure_ascii=False))
    lines.append('已有动作与观察统一见共同地图。框架根据绑定动作更新进度，done只表示已探索；业务效果以实际观察为准。')
    resolved=[item for item in task.get('blocker_history',[]) if item.get('resolved_by')]
    if resolved and not task.get('blocker'):
        lines.append('历史阻塞已在后续观察中解除；当前是否可操作仍以截图为准。')
    ref=state.get('last_action_result') or {}
    recent=records.get(ref.get('region'),{}).get('actions',{}).get(ref.get('action'))
    evidence={'task':{'region':task_region,'name':name},'recent_action':None,'resolved_blockers':resolved,
              'definition':{k:task.get(k) for k in ('control','reason','action','task_type','handling','equivalent_to')}}
    if recent:evidence['recent_action']=dict(ref)
    facts,evidence['known_findings']=findings(records,state,task_region,name,task)
    if facts:
        lines+=['已登记的相关属性（历史观察，不代表完整范围；用于判断还有什么新信息需要探索）：',*facts]
    lines.append('任务登记状态：'+task.get('status','未提供'))
    if task_region not in state.get('interactive_regions',[]) and task.get('attempts'):
        lines.append('任务仍归原区块记录，但不要求返回原区块。依据已有结果从当前截图继续核验；不要为再次操作原入口而自动返回。')
    from task_settlement import task_object_context
    lines.append('本任务当前绑定：'+json.dumps(task_object_context(records,{'task_region':task_region,'region_ref':task_region,'task_name':name}),ensure_ascii=False))
    lines.append('这是前置准备：根据原准备说明和实际反馈继续；条件满足由更新步的dependency_updates登记，点击入口本身不结束准备。' if task.get('prepares') else '执行当前绑定动作并记录直接反馈；普通探索不默认追加穷举或保存验证，显式目标要求保存生效时按真实证据核验。需要到达目标时可先导航，无法定位用none补发现。')
    return '\n'.join(lines),evidence
