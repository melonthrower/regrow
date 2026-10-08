"""Read-only traversal view plus small, optional execution-status hooks."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import uuid

_ACTIVE=ContextVar('traversal_progress',default=None)
PHASES={'discovery':'发现与登记','action':'动作选择与执行','update':'结果核对与更新','recovery':'异常恢复'}
DETAILS={'step_correction':'修复失败步骤','task_correction':'纠正任务登记提案','task_proposal':'清点区块探索任务','function_registration':'整理区块功能','recovery_action':'判断恢复动作'}


class CapturePaused(Exception):
    """User paused screenshot waiting; delivered actions remain pending."""


def check_capture_pause():
    session=_ACTIVE.get()
    if session and Path(session['output']).parent.with_suffix('.pause').exists():
        raise CapturePaused('截图等待已暂停，保留待更新动作')


def read(path):
    return json.loads(Path(path).read_text())


def _write(session):
    # Monitoring failure must not turn a delivered GUI action into a failed task.
    try:
        run=Path(session['run']);run.mkdir(parents=True,exist_ok=True)
        session['updated_at']=datetime.now(timezone.utc).isoformat()
        data=json.dumps(session,ensure_ascii=False,indent=2)+'\n'
        target=run/'progress_current.json';temp=target.with_suffix('.tmp')
        temp.write_text(data);temp.replace(target)
        history=run/'progress_events';history.mkdir(exist_ok=True)
        with (history/(session['round']+'.jsonl')).open('a') as f:f.write(json.dumps(session,ensure_ascii=False)+'\n')
    except OSError:
        pass


def failure_reason(error,run):
    reason='运行校验或调用失败；当前步骤没有完成。'
    if str(error)=='task owner ambiguous or missing':reason='任务提案引用了未登记或无法唯一匹配的控件。'
    elif str(error)=='cannot erase or reclassify existing task':reason='任务提案改写了已有任务的归属或类型，框架拒绝覆盖。'
    try:
        call=error.cmd[-1] if isinstance(error,subprocess.CalledProcessError) and isinstance(error.cmd,list) and len(error.cmd)>=3 and Path(error.cmd[-2]).name=='call_once.py' else None
        path=run/'calls'/str(call)/'http_error.json'
        if call and path.exists():
            response=read(path);status=response.get('status')
            if status==400:reason='模型接口拒绝本轮请求格式（HTTP 400），需要检查请求与输出格式。'
            elif status==429:reason='模型接口限制了本轮请求（HTTP 429）。'
            elif isinstance(status,int):reason=f'模型接口返回 HTTP {status}，未完成本轮调用。'
    except (OSError,ValueError,KeyError):pass
    return {'code':type(error).__name__,'reason':reason,'next':'检查本轮日志与最近调用；不把中断当作探索完成。'}


@contextmanager
def round_status(run,out):
    session={'run':str(Path(run).resolve()),'output':str(Path(out).resolve()),'round':uuid.uuid4().hex,
             'pid':os.getpid(),'status':'running','phase':None,'detail':'准备本轮观察','task':None}
    token=_ACTIVE.set(session);_write(session)
    try:
        yield
    except CapturePaused:
        session.update(status='paused',detail='截图等待已按请求暂停；保留待更新动作');_write(session);raise
    except BaseException as error:
        session['failure']=failure_reason(error,Path(run))
        session.update(status='interrupted',detail='执行中断，请检查本轮日志');_write(session);raise
    else:
        session.update(status='paused',detail='本轮已停止，等待下一步');_write(session)
    finally:
        _ACTIVE.reset(token)


def tracked(fn):
    @wraps(fn)
    def wrapped(root,run,out,**kwargs):
        with round_status(run,out):return fn(root,run,out,**kwargs)
    return wrapped


def request(q):
    session=_ACTIVE.get()
    if session is None:return
    phase='recovery' if q.get('role')=='recovery' else q.get('pipeline_step')
    session.update(phase=phase,detail=DETAILS.get(q.get('stage'),'等待模型回复'),
                   task=q.get('source',{}).get('task_name') or (session.get('task') if phase in ('update','recovery') else None))
    _write(session)


def detail(text):
    session=_ACTIVE.get()
    if session is not None:
        session['detail']=text;_write(session)


def snapshot(run, tasks=None):
    run=Path(run);pointer=read(run/'knowledge_current.json');base=run/pointer['snapshot']
    state=read(base/'runtime_state.json')
    regions={p.parent.name:read(p) for p in (base/'regions').glob('*/region.json')}
    work=regions.get(state.get('working_region'),{})
    if tasks is None:
        spec=importlib.util.spec_from_file_location('progress_tasks',Path(__file__).with_name('region_tasks.py'))
        tasks=importlib.util.module_from_spec(spec);spec.loader.exec_module(tasks)
    cov=tasks.coverage({**work,'controls':work.get('controls',{})},regions)
    total=sum(len(cov[k]) for k in ('done','pending','blocked'))
    cov['total']=total;cov['percent']=round(100*len(cov['done'])/total) if cov['inventory_complete'] and total else None
    runtime=read(run/'progress_current.json') if (run/'progress_current.json').exists() else {'status':'idle','phase':None,'detail':'当前没有运行中的遍历回合'}
    if runtime['status']=='running':
        try:
            if runtime.get('pid',0)<=0:raise ProcessLookupError()
            os.kill(runtime['pid'],0)
        except (ProcessLookupError,PermissionError):
            runtime={**runtime,'status':'interrupted','detail':'执行进程已退出；保留最后阶段供检查'}
    controls=work.get('controls',{});actions=work.get('actions',{})
    observed=sum(any(actions.get(a,{}).get('result') for a in c.get('action_refs',[])) for c in controls.values())
    active=state.get('active_task') or {}
    current=runtime.get('task') or active.get('name')
    blocker=None
    if runtime['status']=='interrupted':
        blocker={**runtime.get('failure',{'code':'execution_interrupted','reason':'上轮执行中断，尚未确认的结果不能视为完成。','next':'检查最近调用与运行日志后再继续。'}),'tasks':[]}
    # Missing recorded localization is advisory, not an execution blocker.
    visible=set((state.get('observation') or {}).get('control_refs',[]))
    missing=[controls[t['control']]['name'] for t in work.get('tasks',{}).values()
             if t.get('status')=='pending' and t.get('handling')=='explore'
             and t.get('control') in controls and t['control'] not in visible]
    localization_notice=({'region':work.get('name',''),'controls':list(dict.fromkeys(missing))} if missing else None)
    if blocker is None and state.get('next_action_mode')=='review_result':
        blocker={'code':'observation_needs_review','tasks':[],'reason':'当前观察或返回路径尚未确认。','next':'先复核观察，不能直接执行任务。'}
    spec=importlib.util.spec_from_file_location('progress_details',Path(__file__).with_name('progress_details.py'))
    projection=importlib.util.module_from_spec(spec);spec.loader.exec_module(projection)
    extras=projection.details(run,regions)
    if extras['repair'] and runtime['status']!='running':
        blocker={'code':'pending_step_repair','tasks':[],'reason':extras['repair']['reason'],
                 'next':'先继续修复'+extras['repair']['stage']+'，不重做已执行动作。'}
    return {**extras,'status':runtime['status'],'phase':runtime.get('phase'),'phase_label':PHASES.get(runtime.get('phase')),
        'blocker':blocker,'localization_notice':localization_notice,'detail':runtime.get('detail'),'updated_at':runtime.get('updated_at'),'source_call':state.get('source_call'),
        'work_region':{'name':work.get('name','尚未定位'),'description':work.get('description','')},
        'visible_regions':[regions[r]['name'] for r in state.get('interactive_regions',[]) if r in regions],
        'current_task':current if runtime['status']=='running' else None,'unfinished_task':active.get('name'),
        'progress':cov,'observed_controls':observed,'total_controls':len(controls),
        'exception':state.get('exception') or (state.get('observation') or {}).get('foreground',{}).get('exception','none'),
        'action_results':[{'control':controls.get(a.get('control'),{}).get('name',work.get('name','区块动作')),
            'action':a.get('operation','未知动作'),'delivery':a.get('delivery'),
            'description':a.get('result',{}).get('description','具体结果尚未观察'),
            'exception':a.get('result',{}).get('exception','none'),'evidence':a.get('result',{}).get('evidence','')}
            for a in actions.values()],
        'tasks':[{'name':name,'status':effective.get('status'),'handling':t.get('handling'),'purpose':t.get('reason',''),'reason':(effective.get('deferral',{}).get('reason') or effective.get('result_evidence') or effective.get('reason','')) if effective.get('status')=='blocked' else ''} for name,t in work.get('tasks',{}).items() for effective in [tasks.effective_task(work.get('tasks',{}),t)]],
        'next_mode':state.get('next_action_mode'),'snapshot':pointer['snapshot']}
