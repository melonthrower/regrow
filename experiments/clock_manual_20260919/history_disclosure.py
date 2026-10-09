"""History presentation and shared-rule references at the model-send boundary.

No evidence selection, task binding, schema changes or state mutation.
"""
from copy import deepcopy
import json


ROLES={'task_result_review','observation','task_proposal','action_selection','observation_update',
       'function_registration','step_correction','control_identity_selection','recovery','branch_correction'}


def render(value,depth=0):
    compact=lambda item:json.dumps(item,ensure_ascii=False,separators=(',',':'))
    if depth>=3 or not isinstance(value,(dict,list)) or not value:
        return compact(value)
    pad='  '*(depth+1);close='  '*depth
    if isinstance(value,dict):
        return '{\n'+',\n'.join(pad+compact(k)+': '+render(v,depth+1) for k,v in value.items())+'\n'+close+'}'
    return '[\n'+',\n'.join(pad+render(v,depth+1) for v in value)+'\n'+close+']'


def grouped_facts(text):
    lines=[];group=None
    for line in text.splitlines(keepends=True):
        head,sep,body=line.partition('：')
        pieces=head[2:].split(' / ') if head.startswith('- ') else []
        if sep and len(pieces)==3 and body.lstrip().startswith('{'):
            try:json.loads(body)
            except ValueError:
                lines.append(line);group=None;continue
            source=' / '.join(pieces[:2])
            if source!=group:lines.append('属性来源：'+source+'\n');group=source
            lines.append('- '+pieces[2]+sep+body)
        else:
            lines.append(line);group=None
    return ''.join(lines)


def project(request):
    role=request.get('role')
    if role not in ROLES:return request
    text=request.get('user_prompt','')
    try:value,end=json.JSONDecoder().raw_decode(text)
    except (ValueError,TypeError):
        if role!='action_selection':return request
        return {**request,'user_prompt':grouped_facts(text)}
    if not isinstance(value,dict):return request
    value=deepcopy(value);suffix=text[end:]
    if role in ('step_correction','control_identity_selection'):
        nested=value.get('原动态上下文')
        if isinstance(nested,str):
            try:
                original,stop=json.JSONDecoder().raw_decode(nested)
                if isinstance(original,dict):
                    value['原动态上下文']={'上下文':original,'附加说明':nested[stop:]}
                    task=original.get('本轮探索任务')
                    candidate=value.get('被拒绝回复') or {}
                    if task and isinstance(candidate,dict):
                        outcome=candidate.get('task_result')
                        value['任务名称对照']={'原任务':task,'回复任务':outcome.get('name') if isinstance(outcome,dict) else None}
            except ValueError:pass
        rules=value.pop('原任务要求',None)
        if rules is not None:
            from prompt_delivery import original_rules
            rules,shared=original_rules(request,rules)
            value['原步骤规则位置']='见后附“原步骤专属规则”；与当前 system 中的共同规则一并适用。' if shared else '见后附“原步骤完整规则”；它与纠错规则共同适用，内容未删减。'
            if shared:value['原步骤共用规则']=shared
            suffix+='\n\n## '+('原步骤专属规则' if shared else '原步骤完整规则')+'\n'+rules
        first=('具体校验错误','框架错误分类','执行状态','任务名称对照','本次修复历史','失败步骤')
        value={**{k:value[k] for k in first if k in value},**{k:v for k,v in value.items() if k not in first}}
    return {**request,'user_prompt':render(value)+suffix}
