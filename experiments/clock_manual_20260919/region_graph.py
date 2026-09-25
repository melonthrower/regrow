"""Read-only Region graph projection from a single committed knowledge snapshot."""
import json
from pathlib import Path
from urllib.parse import urlencode
from region_tasks import coverage
from stepwise_flow import contextual_return, navigation_description


def read(path):return json.loads(Path(path).read_text())


def snapshot(run,version=None):
    run=Path(run).resolve()
    version=version or read(run/'knowledge_current.json')['snapshot']
    base=(run/version).resolve()
    base.relative_to(run/'knowledge_snapshots')
    return run,base,version


def asset(run,version,rid,cid=None):
    run,base,_=snapshot(run,version)
    regions={p.parent.name:p for p in (base/'regions').glob('*/region.json')}
    if rid not in regions:raise ValueError('Unknown region')
    record=read(regions[rid])
    item=record['controls'][cid] if cid else record
    row=next((x for x in reversed(item.get('observations',[])) if x.get('image')),None)
    if not row:raise ValueError('No saved crop')
    path=(regions[rid].parent/row['image']).resolve();path.relative_to(run)
    if path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):raise ValueError('Not an image')
    return path


def project(run):
    run,base,version=snapshot(run)
    records={p.parent.name:read(p) for p in (base/'regions').glob('*/region.json')}
    state=read(base/'runtime_state.json');nodes=[];edges={}
    def picture(rid,cid=None):
        try:asset(run,version,rid,cid)
        except (OSError,ValueError,KeyError):return None
        args={'snapshot':version,'region':rid}
        if cid:args['control']=cid
        return '/graph-image?'+urlencode(args)
    for rid,r in records.items():
        controls=[]
        for cid,c in r['controls'].items():
            actions=[{'attempt':aid,'operation':a.get('operation'),'description':navigation_description(a),
                      'exception':a.get('result',{}).get('exception','none'),'delivery':a.get('delivery')}
                     for aid,a in r.get('actions',{}).items() if a.get('control')==cid]
            controls.append({'id':cid,'name':c['name'],'description':c.get('description') or c.get('icon_description',''),
                             'image':picture(rid,cid),'actions':actions,
                             'tasks':[{'name':n,'status':t.get('status'),'reason':t.get('reason','')} for n,t in r.get('tasks',{}).items() if t.get('control')==cid]})
        nodes.append({'id':rid,'name':r['name'],'description':r.get('description',''),'image':picture(rid),
                      'current':rid in state.get('interactive_regions',[]),'working':rid==state.get('working_region'),
                      'progress':coverage(r,records),'controls':controls})
        for t in r.get('transitions',[]):
            aid=t.get('attempt');a=r.get('actions',{}).get(aid,{})
            dest=t.get('target_region');cid=t.get('source_control')
            if dest==rid or dest not in records or a.get('delivery')!='executed_receipt_zero':continue
            if dest not in a.get('interactive_regions',[]) or a.get('result',{}).get('exception','none')!='none':continue
            op=a.get('operation','click');key=(rid,cid,dest,op)
            if key not in edges:
                edges[key]={'source':rid,'target':dest,'control':cid,'control_name':r['controls'].get(cid,{}).get('name','系统操作')+('（返回目标依赖进入路径）' if contextual_return(a) else ''),
                            'operation':op,'attempts':[],'description':navigation_description(a)}
            if aid not in edges[key]['attempts']:edges[key]['attempts'].append(aid)
    return {'snapshot':version,'app':read(run/'run_manifest.json').get('app',run.name),'working':state.get('working_region'),
            'nodes':nodes,'edges':list(edges.values())}
