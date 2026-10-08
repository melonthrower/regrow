"""Stable control roles, representative lists and explicit graph record repairs."""

def extend_schema(schema, required=False):
    item=schema['properties']['controls']['items']
    item['properties'].update(name={'type':'string'},list_group={'type':'string'})
    item['properties']['previous_name']['description']='当前控件对应本区块历史控件时逐字填旧name；当前name可描述新条件用途，但不能因此清空previous_name另建身份。对照历史图标外观和当前匹配位置，只有确实不同的控件才填空。'
    if required:item['required']=list(dict.fromkeys(item['required']+['name','list_group','click_bbox']))
    return schema


def validate(controls):
    seen=set()
    for c in controls:
        group=c.get('list_group','').strip()
        if group:
            key=(c['region_index'],group)
            if key in seen:raise ValueError('list group requires one representative per interaction type')
            seen.add(key)


def rewrite(value, old, new):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('control','source_control','control_ref','required_control') and item==old:value[key]=new
            elif key in ('control_refs','controls') and isinstance(item,list) and all(isinstance(v,str) for v in item):
                value[key]=list(dict.fromkeys(new if v==old else v for v in item))
            else:rewrite(item,old,new)
    elif isinstance(value,list):
        for item in value:rewrite(item,old,new)


def merge(records,state,rid,sources,target):
    r=records[rid];canonical=r['controls'][target]
    for cid in sources:
        if cid==target:continue
        c=r['controls'][cid]
        canonical.setdefault('observations',[]).extend(c.get('observations',[]))
        canonical['action_refs']=list(dict.fromkeys(canonical.get('action_refs',[])+c.get('action_refs',[])))
        canonical['task_refs']=list(dict.fromkeys(canonical.get('task_refs',[])+c.get('task_refs',[])))
        canonical.setdefault('merged_records',[]).append({'id':cid,'name':c.get('name')})
        del r['controls'][cid]
        rewrite(records,cid,target);rewrite(state,cid,target)
    names=[c['name'] for c in r['controls'].values()]
    if len(names)==len(set(names)):
        r.get('registration_gaps',{}).pop('duplicate_controls',None)
    state.pop('visual_navigation',None)


def remove(records,state,rid,cid):
    r=records[rid];c=r['controls'][cid]
    if c.get('action_refs') or any(a.get('control')==cid for rr in records.values() for a in rr.get('actions',{}).values()) or any(t.get('control')==cid for t in r.get('tasks',{}).values()) or any(
        e.get('source_control')==cid for rr in records.values() for e in rr.get('transitions',[])):
        raise ValueError('referenced control cannot be removed; merge duplicate or retain history')
    del r['controls'][cid]
    if cid in r.get('task_inventory',{}).get('controls',[]):r['task_inventory']['controls'].remove(cid)
    if cid in state.get('observation',{}).get('control_refs',[]):state['observation']['control_refs'].remove(cid)
    if state.get('required_control')==cid:state.pop('required_control')
    state.pop('visual_navigation',None)
