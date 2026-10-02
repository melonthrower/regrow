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
    result={'观察来源':('本轮仅图片匹配定位；以下文字、状态和作用对象沿用历史，未重新识别' if row.get('visual_only') else '本轮输入所对应的登记观察') if matching else '历史观察，当前是否仍成立需核对',
            '文字':row.get('text',''),'本次外观':row.get('icon_description',''),
            '可见状态':row.get('state',''),'功能推测（未验证）':row.get('possible_operation',''),
            '功能疑问':row.get('uncertainty',''),'历史外观参考':old.get('icon_description','')}
    if templates.evidence_limit(row):result['视觉依据限定']=templates.evidence_limit(row)
    if templates.evidence_limit(old):result['历史外观参考限定']=templates.evidence_limit(old)
    return result


def handoff(records, state, run=None):
    """Carry observation gaps and three related executed attempts, without routing."""
    observation=state.get('observation') or {}
    last=state.get('last_action_result') or {}
    related=set(state.get('interactive_regions',[]))|{state.get('working_region'),last.get('region')}
    attempts={}
    for rid, region in records.items():
        for aid, action in region.get('actions',{}).items():
            if action.get('delivery')!='executed_receipt_zero':continue
            if rid not in related and not related.intersection(action.get('interactive_regions',[])):continue
            attempts[aid]=(region,action)
    recent=[]
    for aid in sorted(attempts)[-3:]:
        region,action=attempts[aid]
        association=action.get('association') or {}
        row={'来源记录区块':region['name'],'动作':action.get('operation'),
             '请求目标':association.get('target') or region.get('controls',{}).get(action.get('control'),{}).get('name','未关联控件'),
             '关联状态':association.get('status','已登记' if action.get('control') else '未关联控件'),
             '目的':action.get('purpose',''),'观察结果':action.get('result',{})}
        if run is not None:
            folder=Path(run)/'action_attempts'/aid
            if (folder/'dispatch.json').is_file() and (folder/'receipt.json').is_file():
                dispatch=json.loads((folder/'dispatch.json').read_text()).get('action',{})
                receipt=json.loads((folder/'receipt.json').read_text())
                if receipt.get('exit_code')==0 and dispatch.get('action')==action.get('operation'):
                    row['实际投递']= {k:dispatch[k] for k in ('action','target','x','y','end_x','end_y') if k in dispatch}
        recent.append(row)
    summary=state.get('handoff_summary','');gaps=observation.get('uncertainties',[])
    if not summary and not gaps and not recent:return {}
    return {'来源':'最近登记观察及相关执行历史，不保证当前仍成立；历史坐标不能直接复用',
            '交接说明':summary,'未确认事项':gaps,'最近已执行动作':recent}


def attach_handoff(request, records, state, run=None):
    if not request.get('action_ready'):return request
    context=handoff(records,state,run)
    if context:
        request['observation_handoff']=context
        request['user_prompt']=request['dynamic_prompt']=request['user_prompt']+'\n\n上步观察交接：\n'+json.dumps(context,ensure_ascii=False,indent=2)
    return request


def attach(request,records):
    if not request.get('action_ready'):return request
    spec=importlib.util.spec_from_file_location('target_choices',Path(__file__).with_name('visual_choices.py'))
    choices=importlib.util.module_from_spec(spec);spec.loader.exec_module(choices)
    request=choices.prepare(request)
    source=request.get('source',{});region=records.get(source.get('region'),{})
    targets=[]
    for candidate in request.get('backend_candidates',[]):
        owner=records.get(candidate.get('region_ref',source.get('region')),region)
        control=owner.get('controls',{}).get(candidate['id'])
        if control is None:continue
        card=describe(control,source.get('observation'))
        candidate['target_observation']=card
        item={'控件':candidate['name'],'目标观察':card}
        frames=request.get('image_refs',[])
        if candidate.get('image') and Path(candidate['image']).is_file() and len(frames)==1 and frames[0] and Path(frames[0]).is_file():
            boxes=[v['box'] for v in request.get('visual_choices',{}).get(candidate['id'],[])]
            item['整屏候选位置']=boxes
            item['位置说明']='与后台核对共用的视觉候选；已定位所属区块时仅保留区块内位置，仍需结合截图核对目标'
        targets.append(item)
    if not targets:return request
    request['target_observations']=targets
    text=request['user_prompt']+'\n\n本轮目标观察（沿用已登记对象，不按同名文字另换目标）：\n'+json.dumps(targets,ensure_ascii=False,indent=2)
    request['user_prompt']=request['dynamic_prompt']=text
    return request
