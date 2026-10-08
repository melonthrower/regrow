"""Read-only projection of repair episodes and cross-Region exploration gaps."""
import json
from pathlib import Path

STAGES={'discovery':'发现与登记','task_proposal':'任务登记','function_registration':'功能登记','action':'动作定位','update':'结果更新'}
RESOLUTIONS={'revise':'修正本轮提案','observe':'补充观察','edit_record':'修订记录','defer':'暂挂局部问题','blocked':'保留阻塞'}


def read(path):return json.loads(Path(path).read_text())


def gap_reason(gap):
    if gap.get('reason'):
        return gap['reason']
    pending=gap.get('pending',[])
    if pending:
        return '待补发现登记：'+'；'.join(
            (item.get('item') or item.get('name') or '未命名对象')+
            ('（'+item['proposal']['uncertainty']+'）' if item.get('proposal',{}).get('uncertainty') else '')
            for item in pending)
    return '登记缺口未提供原因说明'


def details(run,regions):
    run=Path(run);gaps=[];episodes={}
    for rid,r in regions.items():
        for name,t in r.get('tasks',{}).items():
            if t.get('status')!='blocked':continue
            evidence=t.get('deferral',{})
            gaps.append({'region':r['name'],'task':name,'reason':evidence.get('reason') or t.get('result_evidence') or t.get('reason','原因未登记'),
                         'retry':('前置条件或允许范围变化后需显式复核；当前不自动解除暂挂' if t.get('blocker',{}).get('condition')=='review_required'
                                  else '发现步重新定位到该控件后再尝试' if evidence else '前置条件满足后再评估'),
                         'episode':evidence.get('episode')})
        for stage,gap in r.get('registration_gaps',{}).items():
            gaps.append({'region':r['name'],'task':STAGES.get(stage,stage)+'缺口','reason':gap_reason(gap),
                         'retry':'补充相关观察或记录后重新检查','episode':gap.get('episode')})
    for gap in gaps:
        path=run/gap['episode'] if gap['episode'] else None
        if path and path.is_file():episodes[str(path)]=(path.stat().st_mtime,read(path))
    latest=None
    for _,job in sorted(episodes.values(),key=lambda v:v[0],reverse=True):
        d=job.get('deferral')
        if d:
            dest=d.get('next');owner=regions.get(d['region'],{}).get('name',d['region'])
            latest={'from_region':owner,'task':d.get('task') or STAGES.get(d['stage'],d['stage'])+'缺口','reason':d['reason'],
                    'next_region':regions.get(dest['region'],{}).get('name',dest['region']) if dest else None,
                    'next_task':dest.get('task') if dest else None}
            break
    repair=None;pointer=run/'pending_step.json'
    if pointer.exists():
        job=read(run/read(pointer)['episode'])
        if job.get('error') or job.get('repairs',0):
            operation='等待纠错回复'
            if job['status']=='observe':operation='补充观察后返回原步骤'
            elif job['status']=='blocked':operation='保留问题，等待处理'
            elif job['status']=='accept':operation='框架正在校验修正提案'
            path=run/'calls'/str(job.get('call'))/'response.json'
            if path.exists():
                reply=read(path)
                if reply.get('resolution'):operation=RESOLUTIONS.get(reply['resolution'],operation)
            repair={'stage':STAGES.get(job['stage'],job['stage']),'reason':job.get('error',''),
                    'operation':operation,'status':job['status']}
    return {'deferred_tasks':gaps,'last_task_switch':latest,'repair':repair}
