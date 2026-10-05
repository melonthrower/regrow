"""Shared read-only target observations for action selection and correction."""
import json
from pathlib import Path
import importlib.util
import identity_templates as templates


def describe(control, observation):
    rows=control.get('observations',[])
    matching=[v for v in rows if observation and v.get('evidence',{}).get('observation')==observation]
    row=(matching or rows or [{}])[-1]
    prior=rows[:rows.index(row)] if row in rows else []
    old=next((v for v in reversed(prior) if v.get('icon_description')), {})
    result={'观察来源':('本轮仅图片匹配定位；外观和作用对象沿用历史，未重新识别；当前状态看本轮截图' if row.get('visual_only') else '最近登记观察；是否对应本轮附图以共同地图的结构来源为准，仍需看图核对') if matching else '历史观察，当前是否仍成立需核对',
            '本次外观':row.get('icon_description',''),
            '功能推测（未验证）':row.get('possible_operation',''),
            '功能疑问':row.get('uncertainty',''),'历史外观参考':old.get('icon_description','')}
    result['当前状态依据']='本轮截图；旧观察文字、数值和选中状态不作为当前值'
    if templates.evidence_limit(row):result['视觉依据限定']=templates.evidence_limit(row)
    if templates.evidence_limit(old):result['历史外观参考限定']=templates.evidence_limit(old)
    return result


def handoff(records, state, run=None):
    """Carry observation gaps; action evidence is owned by page_history."""
    observation=state.get('observation') or {}
    summary=state.get('handoff_summary','');gaps=observation.get('uncertainties',[])
    if not summary and not gaps:return {}
    return {'来源':'最近登记观察，不保证本轮截图仍成立；动作经过见共同地图历史',
            '交接说明':summary,'未确认事项':gaps}


def attach_handoff(request, records, state, run=None):
    if not request.get('action_ready'):return request
    context=handoff(records,state,run)
    if context:
        request['observation_handoff']=context
        return render_handoff(request)
    return request


def compact_handoff(context, history):
    handoff=history.get('handoff')
    if (handoff and context.get('交接说明') == handoff['summary']
            and context.get('未确认事项') == handoff['uncertainties']):
        import page_history
        return {'来源':context['来源'], '交接与未确认事项':'见'+page_history.reference(history,handoff['attempt'])+'；仅为该次更新的交接，不表示缺口已解决。'}
    return context


def render_handoff(request):
    context=request.get('observation_handoff')
    if not context:return request
    history=request.get('page_context',{}).get('history',{})
    rendered=json.dumps(compact_handoff(context,history),ensure_ascii=False,indent=2)
    marker='\n\n上步观察交接：\n'
    previous=request.get('_handoff_text')
    texts={key:request.get(key,request.get('user_prompt','')) for key in ('user_prompt','dynamic_prompt')}
    for key,text in texts.items():
        request[key]=text.replace(marker+previous,marker+rendered,1) if previous and marker+previous in text else text+marker+rendered
    request['_handoff_text']=rendered
    return request


def attach(request,records):
    if not request.get('action_ready'):return request
    source=request.get('source',{});region=records.get(source.get('region'),{})
    for candidate in request.get('backend_candidates',[]):
        owner=records.get(candidate.get('region_ref',source.get('region')),region)
        control=owner.get('controls',{}).get(candidate['id'])
        if control is None:continue
        candidate['target_observation']=describe(control,source.get('observation'))
        candidate['region_name']=owner.get('name','')
    return refresh(request)


def refresh(request):
    """Rebuild positions after a frame replacement, including the rendered table."""
    import page_context
    page_context.refresh(request)
    if request.get('stage')=='step_correction':return request
    spec=importlib.util.spec_from_file_location('target_choices',Path(__file__).with_name('visual_choices.py'))
    choices=importlib.util.module_from_spec(spec);spec.loader.exec_module(choices)
    request=choices.prepare(request)
    return render(request)


def render(request):
    """Render cards from original backend observations, after map/frame refresh."""
    import page_context
    previous=request.get('target_observations',[])
    targets=[]
    source=request.get('source',{})
    target=source.get('task_control') or source.get('control')
    navigation={step.get('source_control') for step in request.get('navigation_path') or [] if isinstance(step,dict)}
    for candidate in request.get('backend_candidates',[]):
        if target and candidate['id']!=target and candidate['id'] not in navigation:continue
        card=candidate.get('target_observation')
        if card is None:continue
        card=page_context.compact_observation(card,request.get('page_context'),
            candidate.get('region_ref',source.get('region')),source.get('observation'),control=candidate['id'])
        item={'所属区块':candidate.get('region_name',''),'控件':candidate['name'],'目标观察':card}
        frames=request.get('image_refs',[])
        if candidate.get('image') and Path(candidate['image']).is_file() and len(frames)==1 and frames[0] and Path(frames[0]).is_file():
            boxes=[v['box'] for v in request.get('visual_choices',{}).get(candidate['id'],[])]
            item['整屏候选位置']=boxes
            item['位置说明']='与后台核对共用的当前图视觉候选；外观及相对位置匹配不独立证明字段单位或功能，仍需结合截图核对目标'
            matches=request.get('visual_choices',{}).get(candidate['id'],[])
            if any(v.get('layout_evidence') for v in matches):
                item['布局依据']='同源控件组的实际像素与相对位置在本图唯一重匹配；保留原单位/功能的未验证边界'
        targets.append(item)
    if not targets and not previous:return request
    request['target_observations']=targets
    marker='\n\n本轮目标观察（沿用已登记对象，不按同名文字另换目标）：\n'
    old=marker+json.dumps(previous,ensure_ascii=False,indent=2)
    new=marker+json.dumps(targets,ensure_ascii=False,indent=2) if targets else ''
    for key in ('user_prompt','dynamic_prompt'):
        text=request.get(key,request.get('user_prompt',''))
        request[key]=text.replace(old,new,1) if previous and old in text else text+new
    return request
