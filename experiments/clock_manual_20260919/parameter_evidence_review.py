"""Return missing parameter facts to their existing authoring stage, once per evidence set."""
import hashlib
import json
from pathlib import Path


def helper(name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def request_review(run,job):
    run=Path(run)
    if (job.get('stage')!='task_result_review' or job.get('attempt') or job.get('service_failure')
            or (run/'execution_pending.json').exists()
            or job.get('error')!='参数任务缺少已登记参数事实，需先补观察登记'):return False
    source=job['request'].get('source',{});rid=source.get('task_region') or source.get('region');name=source.get('task_name')
    discovery=helper('discovery_step');_,records,_=discovery.load(run)
    region=records.get(rid,{});task=region.get('tasks',{}).get(name,{})
    candidate=job.get('candidate') or {}
    if (task.get('status')!='pending' or not helper('task_prerequisites').needs_parameter_facts(task)
            or task.get('findings') or not task.get('attempts') or candidate.get('status')!='done'
            or candidate.get('name')!=name or not candidate.get('evidence','').strip()):return False
    attempts=[];frames=[]
    for aid in dict.fromkeys(task['attempts']):
        if Path(aid).name!=aid:return False
        owners=[r['actions'][aid] for r in records.values() if aid in r.get('actions',{})]
        folder=run/'action_attempts'/aid
        if len(owners)!=1 or owners[0].get('delivery')!='executed_receipt_zero':continue
        if not all((folder/f).is_file() for f in ('commit.json','receipt.json','before.png','after.png')):return False
        if json.loads((folder/'receipt.json').read_text()).get('exit_code')!=0:continue
        attempts.append({'attempt':aid,'action':owners[0]})
        frames.extend(str(Path('action_attempts')/aid/(when+'.png')) for when in ('before','after'))
    if not attempts:return False
    key=hashlib.sha256(json.dumps([task.get('control'),attempts],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    review=region.get('task_inventory',{}).get('review',{})
    if region.get('parameter_review_keys',{}).get(name)==key:
        # Resume a crash between the durable handoff and clearing the old pointer.
        return review.get('kind')=='parameter_facts' and review.get('episode')==job['path'] and review.get('key')==key
    if review:return False  # Preserve another outstanding inventory review.
    context=helper('history_context').task_goal(task,records,run)
    def mutate(records,state,*args):
        r=records[rid];r.setdefault('parameter_review_keys',{})[name]=key
        r.setdefault('task_inventory',{})['review']={'kind':'parameter_facts','task':name,'key':key,
            'episode':job['path'],'source_call':job.get('call'),'frames':frames,'context':context,
            'reason':'累计核对提出完成，但参数事实尚未登记。沿用任务「'+name+'」的归属、动作和类型，核对当前截图及附带的原动作前后图；仅将能够确认属于该任务对象的参数事实写入现有findings。身份未确认的动作只是线索，不能据此强行认领结果。证据不足时保留缺口，不重做GUI以补账，也不直接宣布完成。'}
    import uuid
    discovery.publish(run,'parameter-review-'+uuid.uuid4().hex,mutate)
    return True


def augment(request,region):
    review=region.get('task_inventory',{}).get('review',{})
    if review.get('kind')!='parameter_facts':return request
    dynamic=json.loads(request['user_prompt'])
    dynamic['待补参数事实的原任务证据']=review['context']
    labels=[]
    for frame in review['frames']:
        if frame not in request['screenshots']:
            request['screenshots'].append(frame)
            labels.append({'图片':len(request['screenshots']),'历史原图':frame})
    dynamic['历史原图对照']={'图片':labels,'说明':'首图是本轮观察；附图是对应历史动作的原前后图，不是新执行。动作已投递与对象已确认是两回事，按证据中的身份关联状态阅读。'}
    request['user_prompt']=request['dynamic_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    request['image_refs']=list(request['screenshots'])
    request['source']['parameter_fact_review']={k:review[k] for k in ('task','key')}
    return request
