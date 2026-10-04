"""Settle a task from observed results and retain sourced parameter facts."""
import json
from pathlib import Path


def task_object_context(records,binding):
    owner=records[binding.get('task_region',binding['region_ref'])]
    task=owner['tasks'][binding['task_name']]
    actual=records[binding['region_ref']]
    return {'原任务区块':owner['name'],'原任务控件':owner['controls'].get(task.get('control'),{}).get('name','区块本身'),
            '当前绑定的动作区块':actual['name'],'当前绑定的动作控件':actual['controls'].get(binding.get('control_ref'),{}).get('name','尚未关联控件或区块动作'),
            '登记身份一致':owner['id']==actual['id'] and task.get('control')==binding.get('control_ref'),
            '核对说明':'这里比较后台登记身份，不证明视觉身份、当前上下文或动作成功；有待确认关联时仅作线索。对象不同可以是导航或后续操作，完成仍须有原对象对应的操作与结果链。'}



def settle_task(owner,binding,reply,attempt,records=None):
    from region_tasks import helper
    name=binding.get('task_name')
    if not name:return
    task=owner['tasks'][name];assessment=reply.get('task_result')
    if not isinstance(assessment,dict):
        raise ValueError('缺少任务结果：task_result应为当前任务的结果对象；原任务名：'+name)
    if assessment.get('name')!=name:
        raise ValueError('任务名不匹配：'+json.dumps({'原任务名':name,'回复任务名':assessment.get('name'),
            '修正说明':'核对回复是否描述原任务；若是，沿用原任务完整名称，保留有依据的状态和观察。若不是，不可只改名冒充原任务结果。'},ensure_ascii=False))
    if not isinstance(assessment.get('evidence'),str) or not assessment['evidence'].strip():
        raise ValueError('缺少观察依据：任务名已匹配，请说明实际观察；原任务名：'+name)
    if (reply['action_result']['exception']=='external_app' and task.get('task_type')=='single_action'
            and not binding.get('preparatory_action') and binding.get('region_ref',owner['id'])==owner['id']
            and binding.get('control_ref')==task.get('control')):
        reason='已观察到入口跳转应用外；按当前探索范围仅记录，不继续外部流程。'+reply['action_result'].get('description','')
        task=helper('traversal_scope').record_only(task,reason,{'attempts':[attempt]})
        task['result_evidence']=assessment['evidence']
        if attempt not in task['attempts']:task['attempts'].append(attempt)
        owner['tasks'][name]=task
        return
    observed_popup_entry=(reply['action_result']['exception']=='blocking_popup'
        and task.get('task_type')=='single_action' and not binding.get('preparatory_action')
        and binding.get('region_ref')==owner['id'] and binding.get('control_ref')==task.get('control')
        and reply.get('exploration_update',{}).get('attempt_status')=='executed')
    if assessment['status']=='done' and reply['action_result']['exception']!='none' and not observed_popup_entry:
        raise ValueError('exception cannot verify task completion')
    findings=assessment.get('findings',[])
    same_object=(binding.get('region_ref',owner['id'])==owner['id']
                 and binding.get('control_ref')==task.get('control'))
    # Navigation is allowed, but it cannot silently substitute another control
    # for the object being investigated. Previously confirmed same-object history
    # may still satisfy a cumulative task after navigating away.
    supported=[]
    for aid in helper('action_owner_correction').effective_attempts(task):
        action=(records or {owner['id']:owner}).get(owner['id'],{}).get('actions',{}).get(aid,{})
        if (action.get('control')==task.get('control') and action.get('delivery')=='executed_receipt_zero'
                and action.get('result',{}).get('exception')=='none'
                and action.get('result',{}).get('description')
                and (not task.get('action') or action.get('operation')==task['action'])):
            supported.append(aid)
    if not same_object and assessment['status']=='done' and not supported:
        task['completion_review']={'attempt':attempt,'expected_region':owner['id'],
            'expected_control':task.get('control'),'actual_region':binding.get('region_ref'),
            'actual_control':binding.get('control_ref'),
            'reason':'本次结果属于另一操作对象，原任务缺少对应控件的完成证据；保留实际动作，可继续导航或探索其他任务。'}
        task.update(status='pending',result_evidence=task['completion_review']['reason'])
        if attempt not in task['attempts']:task['attempts'].append(attempt)
        return
    # Facts about the other object remain in the action record, not as parameters
    # of this task's control. The raw response is retained unchanged.
    if not same_object and not supported:findings=[]
    if helper('task_prerequisites').needs_parameter_facts(task) and assessment['status']=='done' and not (findings or task.get('findings')):
        raise ValueError('parameter task needs observed parameter facts')
    source={'region':binding.get('region_ref',owner['id']),'task_region':owner['id'],'task':name,
            'attempt':attempt,'control':binding.get('control_ref',task['control'])}
    store_findings(task,findings,source)
    status='blocked' if reply['action_result']['exception']=='unexpected_exit' else assessment['status']
    task.update(status=status,result_evidence=assessment['evidence'])
    if status=='done':task.pop('completion_review',None)
    if reply['action_result']['exception']=='unexpected_exit':
        task['blocker']={'condition':'review_required','exception':'unexpected_exit','attempt':attempt,
                         'reason':'该入口导致应用异常退出；恢复应用不代表入口故障已消除，不自动重试'}
        task['deferral']={'reason':task['blocker']['reason'],'retry_when':'explicit_crash_cause_resolved','attempt':attempt}
    if attempt not in task['attempts']:task['attempts'].append(attempt)



def store_findings(task,findings,source):
    """Visible facts and action-result facts share validation; provenance stays distinct."""
    import jsonschema
    schema=json.loads((Path(__file__).parent/'遍历prompt/输出格式/参数发现.schema').read_text())
    for fact in findings:
        jsonschema.validate(fact,schema)
        if not fact['name'].strip() or not fact['evidence'].strip():raise ValueError('parameter evidence missing')
        d=fact['domain']
        if d['type']=='enum' and not d['values']:raise ValueError('empty observed options')
        if d['type']=='integer' and d['min'] is not None and d['max'] is not None and d['min']>d['max']:raise ValueError('invalid observed range')
        evidence={**source,'evidence':fact['evidence']}
        previous=task.get('findings',{}).get(fact['name'])
        sources=list(previous.get('sources',[previous['source']])) if previous else []
        if previous and previous['domain']['type']!=d['type']:
            raise ValueError('参数类型冲突：任务「'+str(source.get('task',''))+'」事实「'+fact['name']+'」从'+previous['domain']['type']+'变为'+d['type']+'；不同参数应使用不同事实名称')
        if previous and previous['conditions']==fact['conditions'] and d['type']=='enum':
            d={**d,'values':list(dict.fromkeys(previous['domain']['values']+d['values']))}
        if evidence not in sources:sources.append(evidence)
        observations=list(previous.get('observations',[])) if previous else []
        if previous and not observations:
            observations.append({k:previous[k] for k in ('description','domain','conditions','source')})
        current={'description':fact['description'],'domain':fact['domain'],'conditions':fact['conditions'],'source':evidence}
        if current not in observations:observations.append(current)
        task.setdefault('findings',{})[fact['name']]={**fact,'domain':d,'source':evidence,'sources':sources,'observations':observations}
