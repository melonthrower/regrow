"""Review traversal scope without erasing attempts or inventing execution."""
from copy import deepcopy
import json
import uuid
from pathlib import Path
import importlib.util


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def record_only(task,reason,evidence):
    result=deepcopy(task)
    result.setdefault('scope_history',[]).append({k:deepcopy(task[k]) for k in ('handling','status','reason','blocker','deferral') if k in task})
    result.update(handling='record',status='record_only',equivalent_to='',reason=reason,
                  scope_exclusion={'policy':'external_entries_record_only',**evidence})
    result.pop('blocker',None);result.pop('deferral',None)
    return result


def review_request(root,records,state,rid):
    q=helper('task_proposer').plan_request(root,records,state,rid)
    dynamic=json.loads(q['user_prompt'])
    for item in dynamic['已有任务']:
        task=records[rid]['tasks'][item['name']]
        item.update(action=helper('action_commands').normalize(task)['action'],task_type=task['task_type'])
    active=state.get('active_task') or {}
    if active.get('region')==rid:
        dynamic['当前任务后续观察']={'任务':active.get('name'),'异常':state.get('exception'),
            '最近前景说明':state.get('handoff_summary'),'恢复交接':state.get('recovery_handoff'),
            '来源调用':state.get('source_call'),'说明':'这是原动作之后的运行观察，补充早先动作结果；不表示已恢复或完成任务。'}
    dynamic['旧任务范围复核']='复核已有未完成任务：有具体外跳线索、属于纯退出/返回服务动作，或当前平台/用户范围禁止的环境设置修改，改为record并说明依据；未知功能、参数、保存提交等仍需探索的任务保持。不为验证关闭而重新打开已离开的区块。沿用名称、控件、动作及task_type，不删除历史或宣称执行成功。仍需清点本区块新增入口。'
    part={'path':'任务/旧任务范围复核.prompt','text':(Path(root)/'遍历prompt/任务/旧任务范围复核.prompt').read_text()}
    q['fixed_parts'].append(part);q['system_prompt']+='\n\n'+part['text']
    q.update(task_scope_review=True,user_prompt=json.dumps(dynamic,ensure_ascii=False,indent=2))
    q['dynamic_prompt']=q['user_prompt']
    return q


def exclude_known_external(run,records=None,state=None):
    """Skip only entries with executed external results; never infer from names."""
    if (Path(run)/'execution_pending.json').exists():return False
    discovery=helper('discovery_step')
    if records is None:_,records,state=discovery.load(run)
    if state.get('next_action_mode')!='explore':return False
    changes=[]
    for rid,r in records.items():
        for name,t in r.get('tasks',{}).items():
            if t.get('status') not in ('pending','blocked') or t.get('handling')=='record' or not t.get('control'):continue
            hits=[aid for aid,a in r.get('actions',{}).items() if a.get('control')==t['control'] and
                  a.get('delivery')=='executed_receipt_zero' and a.get('result',{}).get('exception')=='external_app']
            if hits:changes.append((rid,name,hits))
    if not changes:return False
    def mutate(records,state,*args):
        for rid,name,hits in changes:
            records[rid]['tasks'][name]=record_only(records[rid]['tasks'][name],
                '已有实际应用外跳转记录；按当前探索范围仅记录此入口，不再点击。',{'attempts':hits})
            if state.get('active_task')=={'region':rid,'name':name}:state.pop('active_task',None)
    discovery.publish(run,'external-scope-'+uuid.uuid4().hex,mutate)
    return True


def skip_prohibited(run,request,proposal,call):
    """Defer a restricted task or prerequisite without erasing the exploration gap."""
    if not proposal.get('skip_task'):return False
    if proposal.get('action')!='none' or not proposal.get('reason','').strip():
        raise ValueError('跳过任务使用none，并说明违反哪项当前限制')
    if (Path(run)/'execution_pending.json').exists():
        raise ValueError('已有执行尚未结算，不能跳过结果登记')
    source=request.get('source',{});rid=source.get('task_region');name=source.get('task_name')
    discovery=helper('discovery_step');_,records,state=discovery.load(run)
    task=records.get(rid,{}).get('tasks',{}).get(name)
    if task is None:raise ValueError('当前请求没有可跳过的探索任务')
    if task.get('deferral',{}).get('source_call')==call:return True
    def mutate(records,state,*args):
        task=records[rid]['tasks'][name]
        task.setdefault('scope_history',[]).append({k:deepcopy(task[k]) for k in ('handling','status','reason','blocker','deferral') if k in task})
        task.update(handling='defer',status='blocked',
                    blocker={'condition':'review_required','source_call':call,'reason':proposal['reason']},
                    deferral={'reason':proposal['reason'],'source_call':call,'action_executed':False,
                              'retry_when':'前置条件或允许范围变化后需显式复核；当前不自动解除暂挂'})
        if state.get('active_task')=={'region':rid,'name':name}:state.pop('active_task',None)
    discovery.publish(run,'scope-skip-'+uuid.uuid4().hex,mutate)
    return True
