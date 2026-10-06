"""Explicit cross-Region behavior links; local observation identity stays local.

One canonical record lives under the first member's Region. Other members hold
only a reference. Existing snapshot transactions persist both atomically.
"""
from copy import deepcopy


def link(records,name,members,reason,evidence):
    members=list(dict.fromkeys(tuple(m) for m in members))
    if not name.strip() or not reason.strip() or len({r for r,c in members})<2:
        raise ValueError('shared behavior needs distinct Regions and an explicit reason')
    for rid,cid in members:
        control=records[rid]['controls'][cid]
        if control.get('shared_control_ref'):raise ValueError('control already linked')
    if not evidence:raise ValueError('shared behavior needs observed action evidence')
    for item in evidence:
        owner=records[item['region']];a=owner['actions'][item['attempt']]
        if (item['region'],a.get('control')) not in members or a.get('delivery')!='executed_receipt_zero' or a.get('result',{}).get('exception')!='none':
            raise ValueError('link evidence is not a successful member action')
    owner=members[0][0]
    if name in records[owner].get('shared_controls',{}):raise ValueError('shared name already exists')
    records[owner].setdefault('shared_controls',{})[name]={
        'name':name,'scope':'behavior_only','reason':reason,'evidence':deepcopy(evidence),
        'members':[{'region':r,'control':c} for r,c in members], 'results':[], 'status':'confirmed'}
    for rid,cid in members:
        records[rid]['controls'][cid]['shared_control_ref']={'region':owner,'name':name}
    refresh(records)


def refresh(records):
    """Refresh canonical behavior from actual member actions, never copy attempts."""
    for owner in records.values():
        for group in owner.get('shared_controls',{}).values():
            if group.get('status')=='separated':continue
            results=[];destinations=set();executed_members=set();broken=False
            for member in group['members']:
                rid,cid=member['region'],member['control'];region=records.get(rid,{})
                c=region.get('controls',{}).get(cid)
                if not c or c.get('shared_control_ref')!={'region':owner['id'],'name':group['name']}:
                    broken=True;continue
                for aid,a in region.get('actions',{}).items():
                    if a.get('control')!=cid or a.get('delivery')!='executed_receipt_zero':continue
                    result=a.get('result',{})
                    if not result.get('description'):continue
                    targets=list(a.get('interactive_regions',[]))
                    row={'source':{'region':rid,'control':cid,'attempt':aid},
                         'operation':a.get('operation'),'description':result['description'],
                         'evidence':result.get('evidence',''),'exception':result.get('exception'),
                         'destination_regions':targets}
                    results.append(row)
                    if result.get('exception')!='none':broken=True
                    if targets and a.get('operation') in ('tap','click') and not result.get('returns_to_previous'):
                        before=set(a.get('evidence',{}).get('before_regions',[]))
                        # A changed source/background is not a destination. Newly
                        # appearing surfaces are conflict hints, not causal proof.
                        direct=set(targets)-before-{rid}
                        if direct:
                            destinations.add(tuple(sorted(direct)));executed_members.add((rid,cid))
            group['results']=results
            from shared_control_review import signature
            reviewed=group.get('reviewed_signature')==signature(group)
            group['status']='needs_review' if broken or not results or (len(executed_members)>1 and len(destinations)>1 and not reviewed) else 'confirmed'

    synchronize_tasks(records)

def view(records,rid,cid):
    ref=records[rid]['controls'][cid].get('shared_control_ref')
    if not ref:return None
    return deepcopy(records.get(ref['region'],{}).get('shared_controls',{}).get(ref['name']))


def disclose(records,rid,cid):
    group=view(records,rid,cid)
    if not group:return []
    return [{'共享关系':group['name'],'关联区块':[records.get(m['region'],{}).get('name',m['region']) for m in group['members']],
             '共享范围':'行为知识；当前状态、位置和执行记录仍属于各自控件',
             '已观察结果':[{'来源区块':records.get(row['source']['region'],{}).get('name',''),
                 '结果':row['description'],'依据':row['evidence'],
                 '目的区块':[records.get(r,{}).get('name',r) for r in row['destination_regions']]} for row in group['results']],
             '用途':('共享结果存在冲突或成员缺失，需重新核对，不能据此跳过探索' if group['status']=='needs_review'
                    else '关联入口的已有行为证据；结合当前对象和状态判断适用性，不代表本地已执行') }]


def render(records,rid):
    lines=[]
    for cid,c in records[rid]['controls'].items():
        group=view(records,rid,cid)
        if not group:continue
        lines.append('共享控件「'+c['name']+'」：'+('关系需重新核对' if group['status']=='needs_review' else '关联入口行为已确认'))
        for row in group['results']:
            source=records.get(row['source']['region'],{}).get('name',row['source']['region'])
            lines.append('  '+source+'中实际观察：'+row['description'])
        lines.append('  不代表本区块已执行；本地状态与任务仍分别登记。')
    return lines


def extend_link(records,old_region,old_control,new_region,new_control,evidence,call):
    """Preserve local observations; only explicitly stable behavior is linked."""
    ref=records[old_region]['controls'][old_control].get('shared_control_ref')
    if ref:
        group=records[ref['region']]['shared_controls'][ref['name']]
        if group['status']!='confirmed':raise ValueError('旧共享关系仍有冲突，不能扩展')
        group['members'].append({'region':new_region,'control':new_control})
        records[new_region]['controls'][new_control]['shared_control_ref']=deepcopy(ref)
    else:
        actions=[{'region':old_region,'attempt':aid} for aid,a in records[old_region]['actions'].items()
                 if a.get('control')==old_control and a.get('delivery')=='executed_receipt_zero' and a.get('result',{}).get('exception')=='none']
        label=records[old_region]['controls'][old_control]['name']+'（'+old_control+'）'
        link(records,label,[(old_region,old_control),(new_region,new_control)],evidence,actions)
        group=records[old_region]['shared_controls'][label]
    group.setdefault('membership_evidence',[]).append({'region':new_region,'control':new_control,'source_call':call,'evidence':evidence})


# Refresh must synchronize tasks before callers clean up detached members.
from shared_tasks import synchronize_tasks, automatic_tasks
