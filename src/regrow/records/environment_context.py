"""Purpose-specific visit context, derived from accepted entries and actions.

This is a route tree, not parent_region containment or an operation whitelist.
"""
from regrow.records.object_store import owned_controls, owned_actions, owned_tasks
from regrow.records.function_scope import entries
from regrow.traversal.task_routing import path_for


def short(text):
    value=' '.join(str(text or '').split()).split('；',1)[0]
    return value if len(value)<=44 else value[:44]+'…'


def links(records,rid):
    rows=[]
    for e in entries(records[rid],records):
        a=owned_actions(records[rid]).get(e.get('attempt'),{})
        if e['status']!='registered_entry' or e['region']==rid or a.get('delivery')!='executed_receipt_zero' or a.get('returns_to_previous') or a.get('result',{}).get('returns_to_previous') or a.get('operation')=='back':
            continue
        rows.append(e)
    return rows


def render(records,state,focus,goal=None,kind='observation'):
    if focus not in records:
        return ''
    goal=goal or {};raw=path_for(records,state,focus)
    path=[focus]
    # Keep only the suffix supported by accepted forward entry meanings.
    for parent in reversed(raw[:-1] if raw and raw[-1]==focus else []):
        if any(e['region']==path[0] for e in links(records,parent)) and parent not in path:
            path.insert(0,parent)
        else:
            break
    path=path[-3:]
    out=['来路层级（已登记访问关系，不表示物理包含；当前图仍由本步核对）']
    for depth,rid in enumerate(path):
        prefix='  '*depth
        if depth:
            parent=path[depth-1]
            matches=[e for e in links(records,parent) if e['region']==rid]
            edge=matches[-1]
            control=owned_controls(records[parent]).get(edge['control'],{})
            prefix+='└─ '+control.get('name','入口')+' → '
        mark='（本轮区块）' if rid==focus else ''
        if rid==focus and goal.get('region')==focus and not goal.get('control'):
            mark='（当前探索区块）'
        out.append(prefix+records[rid]['name']+mark+'：'+short(records[rid].get('description')))
        if depth+1<len(path):
            chosen=path[depth+1];known=set()
            for edge in links(records,rid):
                if edge['region']==chosen or edge['region'] in known:
                    continue
                known.add(edge['region']);target=records[edge['region']]
                control=owned_controls(records[rid]).get(edge['control'],{})
                destination = edge.get('target_name')+'（位于'+target['name']+'）' if edge.get('target_control') else target['name']+'：'+short(target.get('description'))
                out.append('  '*(depth+1)+'├─ '+control.get('name','入口')+' → '+destination)
                if len(known)>=2:
                    break
            linked={e['control'] for e in links(records,rid)}
            unconfirmed=[c['name'] for cid,c in owned_controls(records[rid]).items() if cid not in linked and c.get('may_open_content') is True]
            for name in unconfirmed[:2]:
                out.append('  '*(depth+1)+'├─ '+name+'（入口，目标区块未确认）')
    gr,cid=goal.get('region'),goal.get('control')
    if gr in records and cid in owned_controls(records[gr]):
        out.append(('  '*len(path)+'└─ ' if gr==focus else '原探索目标：'+records[gr]['name']+' / ')+owned_controls(records[gr])[cid]['name']+'（当前探索）')
    elif gr in records and gr!=focus:
        out.append('原探索目标：'+records[gr]['name']+'（当前探索；实际导航不改绑）')
    last=state.get('last_action_result') or {}
    action=owned_actions(records.get(last.get('region'),{})).get(last.get('action'),{})
    obs=state.get('observation') or {}
    oid=obs.get('id') or action.get('evidence',{}).get('after_observation')
    foreground=state.get('interactive_regions',[]) if obs else action.get('interactive_regions',[])
    background=[c['region'] for c in action.get('region_changes',[]) if c.get('state')=='visible_background_blocked' and c.get('region') in records]
    if foreground:
        out.append('上次已登记前景：'+'、'.join(records[r]['name'] for r in foreground if r in records))
    if background:
        out.append('上次更新所报背景：'+'、'.join(records[r]['name'] for r in background))
    if kind=='update':
        out.append('此处为动作前记录；动作后的前景与身份由本次前后图核对。')
    elif oid:
        out.append('上述前景属于已登记观察，不据历史名单代替本次看图。')
    return '\n'.join(out)


def for_request(request,records,state):
    source=request.get('source',{})
    work=request.get('work_context',{})
    focus=source.get('region') or request.get('discovery_context',{}).get('focus') or work.get('region') or state.get('working_region')
    rid=source.get('task_region');goal={}
    if rid in records:
        t=owned_tasks(records[rid]).get(source.get('task_name'),{})
        goal={'region':rid,'control':source.get('task_control',t.get('control'))}
    elif source.get('return_to') in records:
        goal={'region':source['return_to']}
    elif request.get('stage')=='task_proposal':
        goal={'region':focus}
    return render(records,state,focus,goal,kind='update' if request.get('role')=='observation_update' else work.get('kind',request.get('role')))
