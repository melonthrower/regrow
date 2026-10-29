"""Versioned working traces and sequential batches; original traces remain read-only."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import subprocess
import sys
import time
import shutil
from uuid import uuid4
import prompt_review_trace as trace


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def folder(root, key):
    trace.trace(root, key)
    if Path(key).name != key:raise ValueError('无效案例')
    return Path(root) / 'working_traces' / key


def current(root, key):
    base=folder(root,key)
    pointer=trace.read(base/'current.json',{})
    return trace.read(base/'revisions'/str(pointer.get('id'))/'revision.json', {'id':None,'trace':key,'modules':{},'contexts':{},'context_sources':{},'parent':None})


def view(root, key, store):
    revision=current(root,key)
    item=next(t for t in trace.overview(root) if t['id']==key)
    dirty=[name for name,text in revision['modules'].items() if store.read(name)['text']!=text]
    stale={}
    order=[s['call'] for s in item['steps']]
    for status_path in sorted((folder(root,key)/'batches').glob('*/status.json')):
        batch=trace.read(status_path)
        if batch.get('mode')!='test':continue
        baseline=trace.read(status_path.parent/'revision.json',{})
        for row in batch.get('steps',[]):
            if row.get('downstream') and row['call'] in order:
                for later in order[order.index(row['call'])+1:]:
                    if digest([revision['contexts'].get(later),revision.get('context_sources',{}).get(later)])==digest([baseline.get('contexts',{}).get(later),baseline.get('context_sources',{}).get(later)]):
                        stale[later]='上游 '+row['call']+' 的新结果尚未接入本步上下文'
    affected=[]
    for s in item['steps']:
        changed=sorted(set(s['modules']) & set(revision['modules']))
        context=s['call'] in revision['contexts']
        affected.append({**s,'changed_modules':changed,'context_edited':context,
                         'affected':bool(changed or context),'stale':s['call'] in stale,'stale_reason':stale.get(s['call']),'dirty_modules':sorted(set(dirty)&set(s['modules']))})
    return {'revision':revision,'steps':affected,'unsaved_modules':dirty,
            'versions':[trace.read(p) for p in sorted((folder(root,key)/'revisions').glob('*/summary.json'),reverse=True)],
            'batches':[trace.read(p) for p in sorted((folder(root,key)/'batches').glob('*/status.json'),reverse=True)]}


def current_display(root, key, call, store):
    """Never present an archived request as the current draft."""
    revision=current(root,key)
    item=trace.step(root,key,call)
    modules=[{'path':name,'text':store.read(name)['text'],'included':name in revision['modules']}
             for name in item['modules'] if name in store.paths]
    dirty=[m['path'] for m in modules if m['included'] and m['text']!=revision['modules'][m['path']]]
    result={'revision':revision['id'],'modules':modules,'dirty_modules':dirty,'preview':None,'job':None}
    if not revision['id'] or dirty:return result
    for status in trace.jobs(root):
        if status.get('trace')!=key or status.get('call')!=call or status.get('status') not in ('preview_ready','checked'):continue
        dest=Path(root)/'trace_jobs'/status['id']
        spec=trace.read(dest/'job.json',{})
        if spec.get('revision')!=revision['id']:continue
        if not trace.source_matches(dest):continue
        preview=trace.read(dest/'preview.json')
        if preview:result.update(preview=preview,job=status['id']);break
    return result


def validate_context(root, key, call, value):
    source=trace.step(root,key,call)['before']
    if not source:raise ValueError('没有可靠的原始前置记录')
    if not isinstance(value,dict) or set(value)!={'regions','state','snapshot'}:
        raise ValueError('案例上下文须保留regions、state、snapshot')
    if not isinstance(value['regions'],dict) or not isinstance(value['state'],dict):raise ValueError('区块和状态须为对象')
    if value['snapshot']!=source['snapshot']:raise ValueError('请勿修改原始快照来源')
    # The case may edit knowledge/tasks, but cannot manufacture a new screenshot.
    for get in (lambda x:x.get('pending_frame'),lambda x:(x.get('observation') or {}).get('image')):
        if get(value['state'])!=get(source['state'] or {}):raise ValueError('截图来源不能在案例编辑中替换')
    from regrow.records.object_store import Records
    Records(value['regions'])
    return value


def save(root, payload, store, *, provenance=None, module_texts=None):
    with trace.LOCK:
        key=payload['trace'];base=folder(root,key);old=current(root,key)
        if payload.get('parent')!=old['id']:raise ValueError('版本已有更新，请刷新后保存')
        all_modules={n for s in next(t for t in trace.overview(root) if t['id']==key)['steps'] for n in s['modules']}
        selected=payload.get('modules',list(old['modules']))
        if not isinstance(selected,list) or not set(selected)<=all_modules:raise ValueError('模块不属于这个案例')
        modules=deepcopy(module_texts) if module_texts is not None else {n:store.read(n)['text'] for n in selected if n in store.paths}
        contexts=deepcopy(old['contexts']);sources=deepcopy(old.get('context_sources',{}))
        for call,value in payload.get('contexts',{}).items():
            if value is None:contexts.pop(call,None);sources.pop(call,None)
            else:
                contexts[call]=validate_context(root,key,call,value)
                dependency=sources.get(call,{}).get('dependency_job')
                sources[call]=provenance or {'kind':'manual_case_edit', **({'dependency_job':dependency} if dependency else {})}
        if modules==old['modules'] and contexts==old['contexts'] and sources==old.get('context_sources',{}) and old['id']:return view(root,key,store)
        ident=time.strftime('%Y%m%dT%H%M%S',time.gmtime())+'-'+uuid4().hex[:8]
        rev={'id':ident,'trace':key,'parent':old['id'],'modules':modules,'contexts':contexts,'context_sources':sources}
        trace.write(base/'revisions'/ident/'revision.json',rev)
        trace.write(base/'revisions'/ident/'summary.json',{'id':ident,'parent':old['id'],'modules':list(modules),'contexts':list(contexts)})
        trace.write(base/'current.json',{'id':ident})
        return view(root,key,store)


def batch_start(root,payload,store):
    key=payload['trace'];rev=current(root,key)
    if not rev['id']:raise ValueError('先保存工作版本')
    if payload.get('revision')!=rev['id']:raise ValueError('版本已变化，请刷新')
    info=view(root,key,store)
    if info['unsaved_modules']:raise ValueError('模块改动尚未收录到工作版本，请先保存本轮版本')
    mode=payload.get('mode')
    if mode not in ('preview','test'):raise ValueError('未知操作')
    calls=payload.get('calls') or [s['call'] for s in info['steps'] if s['affected']]
    if not calls or not set(calls)<={s['call'] for s in info['steps']}:raise ValueError('请选择本案例需要检查的步骤')
    calls=[s['call'] for s in info['steps'] if s['call'] in calls]
    if mode=='test' and any(s['stale'] for s in info['steps'] if s['call'] in calls):
        raise ValueError('选中的后续步骤仍依赖旧结果，请先采用新登记或更新案例上下文')
    with trace.LOCK:
        if any(b.get('status')=='running' for p in Path(root).glob('working_traces/*/batches/*/status.json') for b in [trace.read(p)]) or any(j['status']=='running' for j in trace.jobs(root)):
            raise ValueError('已有预览或测试运行中')
        ident=time.strftime('%Y%m%dT%H%M%S',time.gmtime())+'-'+uuid4().hex[:8]
        dest=folder(root,key)/'batches'/ident
        trace.write(dest/'revision.json',rev)
        # Pin one code version for the whole batch, not a different source per step.
        shutil.copytree(trace.SOURCE,dest/'source',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        trace.write(dest/'status.json',{'id':ident,'trace':key,'revision':rev['id'],'mode':mode,'status':'running','steps':[{'call':c,'status':'pending'} for c in calls],'calls':0,'GUI':0,'scope':'独立保存帧案例；未执行新GUI，不能视为连续新轨迹'})
        with (dest/'batch.log').open('w') as log:
            subprocess.Popen([sys.executable,str(Path(__file__).resolve()),str(Path(root).resolve()),str(dest.resolve())],stdout=log,stderr=log)
    return trace.read(dest/'status.json')


def batch_view(root,key,ident):
    if Path(ident).name!=ident:raise ValueError('无效批次')
    result=trace.read(folder(root,key)/'batches'/ident/'status.json')
    if result is None:raise ValueError('批次不存在')
    return result


def run_batch(root,dest):
    from prompt_review_editor import EditorStore
    store=EditorStore(root);status=trace.read(dest/'status.json');rev=trace.read(dest/'revision.json');upstream=None
    for row in status['steps']:
        call=row['call'];item=trace.step(root,status['trace'],call)
        if not item['replayable']:
            row.update(status='skipped',reason='独立纠错或缺少前置快照；纠错随正常调用处理')
        elif upstream:
            row.update(status='stale',reason='上游结果已变化；先核对并更新本步案例上下文',upstream=upstream)
        else:
            try:
                names=[n for n in item['modules'] if n in rev['modules']]
                job=trace.start(root,{'trace':status['trace'],'call':call,'mode':status['mode'],'modules':names},store,
                  frozen={'modules':{n:rev['modules'][n] for n in names},'context':rev['contexts'].get(call),'source':str(dest/'source'),'revision':rev['id'],'batch':str(dest), 'dependency_job':rev.get('context_sources',{}).get(call,{}).get('dependency_job')})
                row.update(status='running',job=job['id']);trace.write(dest/'status.json',status)
                while job['status']=='running':
                    time.sleep(.5);job=trace.read(Path(root)/'trace_jobs'/job['id']/'status.json')
                    status['calls']=sum(trace.read(Path(root)/'trace_jobs'/r['job']/'status.json',{}).get('calls',0) for r in status['steps'] if r.get('job'));trace.write(dest/'status.json',status)
                row.update(status=job['status'])
                if job.get('error'):row['reason']=job['error']
                if status['mode']=='test':
                    # Nothing from a new action selection may authorize replaying an old post-action frame.
                    if item['request']['role']=='action_selection' or job['status']!='checked':
                        upstream=call;row['downstream']='动作未执行或本步未通过，后续待更新'
                    else:
                        after=trace.read(Path(root)/'trace_jobs'/job['id']/'after-records.json')
                        historical=item['after']
                        if after and (not historical or digest({'regions':after['regions'],'state':after['state']})!=digest({'regions':historical[-1]['regions'],'state':historical[-1]['state']})):
                            upstream=call;row['downstream']='登记发生变化，后续须采用新记录或独立更新案例'
            except Exception as error:
                row.update(status='failed',reason=str(error),downstream='本步未完成，后续需核对后更新');upstream=call
        trace.write(dest/'status.json',status)
    status['status']='complete' if all(r['status'] in ('preview_ready','checked','skipped') for r in status['steps']) else 'needs_review'
    trace.write(dest/'status.json',status)


def adopt(root,payload,store):
    """Use an accepted non-action result as a new explicit context version for the next saved step."""
    key=payload['trace'];call=payload['call'];ident=payload['job']
    job=trace.job_view(root,ident)
    if job['trace']!=key or job['status']!='checked' or not job['after']:raise ValueError('只能采用本案例已登记的结果')
    steps=trace.trace(root,key)['calls'];pos=steps.index(job['call'])
    if pos+1>=len(steps) or steps[pos+1]!=call:raise ValueError('只能接到紧接的下一步')
    if job['summary']['stage']=='action':raise ValueError('动作尚未执行，不能沿用旧后图继续')
    run,req=trace.source_call(root,key,call)
    frames=req.get('screenshots',[])
    after=deepcopy(job['after']);candidate_frame=(after.get('state',{}).get('observation') or {}).get('image')
    candidate_run=Path(root)/'trace_jobs'/ident/'run'
    if frames and (not candidate_frame or hashlib.sha256((candidate_run/candidate_frame).read_bytes()).digest()!=hashlib.sha256((run/frames[0]).read_bytes()).digest()):
        raise ValueError('下一步截图不同，不能将新记录接到旧后图')
    original=trace.step(root,key,call)['before']
    if not original:raise ValueError('下一步缺少前置记录')
    from regrow.records.object_store import Records,rebase,region_state
    records=Records(after['regions']);records=rebase(records,Path(after['snapshot']),Path(run)/original['snapshot'])
    context={'snapshot':original['snapshot'],'regions':{rid:region_state(r) for rid,r in records.items()},'state':after['state']}
    # Preserve the next step's actual screenshot pointers; semantic state comes from the new record.
    for field in ('pending_frame',):
        if field in original['state']:context['state'][field]=original['state'][field]
    if frames and context['state'].get('observation'):context['state']['observation']['image']=(original['state'].get('observation') or {}).get('image')
    rev=current(root,key)
    return save(root,{'trace':key,'parent':rev['id'],'contexts':{call:context}},store,provenance={'kind':'adopted_registration','job':ident,'dependency_job':ident},module_texts=rev['modules'])


if __name__=='__main__':
    root=Path(sys.argv[1]);dest=Path(sys.argv[2])
    try:run_batch(root,dest)
    except Exception as error:
        value=trace.read(dest/'status.json');value.update(status='failed',error=str(error));trace.write(dest/'status.json',value)
