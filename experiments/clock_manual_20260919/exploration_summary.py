"""Session-bounded, read-only display of actual model attempts and their owners."""
import json
from pathlib import Path


def read(path,default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {} if default is None else default


def category(q):
    stage=q.get('stage','')
    if stage=='recovery_action' or q.get('role')=='recovery':return 'recovery'
    if stage=='discovery':return 'discovery'
    if stage=='action_selection':return 'action'
    if stage=='observation_update':return 'update'
    return 'other'


def knowledge(run):
    snapshot=read(run/'knowledge_current.json').get('snapshot')
    if not snapshot:return {},{}
    root=run/snapshot
    records={p.parent.name:read(p) for p in (root/'regions').glob('*/region.json')}
    return records,read(root/'runtime_state.json')


def record(run,folder,q,output=None):
    """Capture names at dispatch; never add accounting text to model prompts."""
    run=Path(run)
    try:
        records,state=knowledge(run);source=q.get('source') or {};kind=category(q)
        binding={}
        if kind in ('update','recovery'):
            attempt=read(run/'execution_pending.json').get('attempt') or (state.get('last_action_result') or {}).get('action')
            if attempt:binding=read(run/'action_attempts'/attempt/'binding.json')
        task=source.get('task_name') or binding.get('task_name')
        task_region=source.get('task_region') or binding.get('task_region')
        rid=binding.get('region_ref') or source.get('task_region') or source.get('region')
        if not rid:rid=(q.get('discovery_context') or {}).get('focus')
        if not rid and kind!='discovery':rid=state.get('working_region')
        region=records.get(rid,{})
        cid=(binding.get('control_ref') if binding else
             source.get('task_control') or region.get('tasks',{}).get(task,{}).get('control'))
        name=region.get('controls',{}).get(cid,{}).get('name')
        row={'region_id':rid,'region':region.get('name','当前画面'),'control_id':cid,
             'control':name or ('区块发现' if kind=='discovery' else '异常恢复' if kind=='recovery' else '区块级处理'),
             'task':task,'task_region':task_region or rid,'category':kind,'stage':q.get('stage'),
             'session':str(Path(output).resolve().parent) if output else None}
        (Path(folder)/'exploration_context.json').write_text(json.dumps(row,ensure_ascii=False,indent=2))
    except (OSError,ValueError,TypeError,KeyError):
        # Missing display metadata cannot invalidate an action or a model request.
        pass


def counts():return dict.fromkeys(('discovery','action','update','recovery','other'),0)


def summarize(run,session,running):
    run=Path(run);session=Path(session) if session else None
    meta=read(session/'session.json') if session else {}
    if 'start_call' not in meta:
        return {'available':False,'total':0,'counts':counts(),'items':[],
                'note':'本轮尚未开始，或旧轮次缺少调用边界；不混入历史调用。'}
    end=int(read(run/'run_manifest.json').get('last_call',0)) if running else int(meta.get('end_call',meta['start_call']))
    records,_=knowledge(run);groups={};total=counts();last=None
    for folder in sorted((run/'calls').glob('*')):
        if not folder.name.isdigit():continue
        row=read(folder/'exploration_context.json')
        if row.get('session'):
            if Path(row['session']).resolve()!=session.resolve():continue
        elif not meta['start_call']<int(folder.name)<=end:continue
        q=read(folder/'request.json');kind=category(q)
        if not row:row={'region':'未关联区块','control':'未关联控件','task':None,'region_id':None}
        key=(row.get('region_id'),row.get('region'),row.get('control_id'),row['control'],row.get('task_region'),row.get('task'))
        if key not in groups:groups[key]={**row,'counts':counts(),'total':0,'active':False,'calls':[]}
        item=groups[key];item['counts'][kind]+=1;item['total']+=1;item['calls'].append(folder.name);total[kind]+=1;last=key
    for key,item in groups.items():
        task=records.get(item.get('task_region') or item.get('region_id'),{}).get('tasks',{}).get(item.get('task'),{})
        item['outcome']=task.get('status','stage_only')
        item['active']=bool(running and key==last)
    return {'available':True,'session':session.name,'total':sum(total.values()),'counts':total,
            'items':list(groups.values()),'note':'调用含已发起的失败或等待中请求；动作调用不等于已执行GUI。其他含任务/功能整理与纠错。'}
