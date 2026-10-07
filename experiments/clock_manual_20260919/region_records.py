"""Explicit duplicate-Region consolidation, preserving evidence and graph links."""
from copy import deepcopy
from pathlib import Path

REGION_KEYS={'region','region_ref','source_region','target_region','working_region','task_region',
             'parent_region','deferred_routing_target','inspection_region','return_to','destination_region'}
REGION_LISTS={'interactive_regions','before_regions','region_refs','region_path','visited_regions','partition_children'}

import identity_templates as templates


def rewrite(value,aliases,key=None):
    if isinstance(value,dict):
        return {(aliases.get(k,k) if key in ('control_scan',) else k):rewrite(v,aliases,k) for k,v in value.items()}
    if isinstance(value,list):
        items=[rewrite(v,aliases,key) for v in value]
        return list(dict.fromkeys(items)) if key in REGION_LISTS else items
    if isinstance(value,str) and key in REGION_KEYS|REGION_LISTS:return aliases.get(value,value)
    return value


def merge(records,state,sources,target,*,snapshot,rebase,evidence):
    """Caller establishes identity from evidence; this function never guesses it."""
    sources=[s for s in dict.fromkeys(sources) if s!=target]
    if not sources:return
    merging=set(sources+[target])
    if len({bool(records[r].get('out_of_scope_reason')) for r in merging})>1:
        raise ValueError('区块探索范围不一致，需先核对范围与身份，不能自动传播范围排除')
    if any(link.get('region') in merging for rid in merging for link in records[rid].get('distinct_regions',[])):
        raise ValueError('已观察到行为差异的区块不能仅凭外观重新合并')
    # Work privately so a conflicting task/function cannot leave a partial merge.
    rs,st=deepcopy(records),deepcopy(state);dst=rs[target]
    aliases={s:target for s in sources}
    for source in sources:
        src=rebase(rs[source],snapshot/'regions'/source,snapshot/'regions'/target)
        for field in ('controls','actions','tasks','functions'):
            values=dst.setdefault(field,{})
            for name,item in src.get(field,{}).items():
                if name in values and values[name]!=item:
                    raise ValueError(f'区块合并存在不同的{field}记录：{name}；保留原记录，需先核对')
                values[name]=item
        for field in ('observations','transitions','reached_by','distinct_regions'):
            values=dst.setdefault(field,[])
            for item in src.get(field,[]):
                if item not in values:values.append(item)
        if src.get('behavior_context'):
            if dst.get('behavior_context') and dst['behavior_context']!=src['behavior_context']:
                raise ValueError('行为上下文不同，不能在合并时丢弃已记录差异')
            dst['behavior_context']=src['behavior_context']
        dst.setdefault('merged_records',[]).extend(src.get('merged_records',[]))
        dst['merged_records'].append({'id':source,'name':src['name'],'evidence':evidence,
            'task_inventory':src.get('task_inventory'),'external_entry_policy':src.get('external_entry_policy')})
        if src.get('local_knowledge'):dst.setdefault('prior_local_knowledge',[]).append(deepcopy(src['local_knowledge']))
        del rs[source]
    # Same-region consolidation does not make every same-name control identical.
    # Reuse only uniquely corroborated image evidence; otherwise request review.
    import importlib.util
    from PIL import Image
    spec=importlib.util.spec_from_file_location('merged_controls',Path(__file__).with_name('control_records.py'))
    controls=importlib.util.module_from_spec(spec);spec.loader.exec_module(controls)
    groups={}
    for cid,c in dst.get('controls',{}).items():groups.setdefault(c['name'],[]).append(cid)
    for name,ids in groups.items():
        if len(ids)<2:continue
        signatures=[]
        for cid in ids:
            observed=templates.latest(dst['controls'][cid]) or {}
            image=observed.get('image')
            path=snapshot/'regions'/target/image if image else None
            if not path or not path.is_file():break
            with Image.open(path) as im:
                im=im.convert('RGB');signatures.append((im.size,im.tobytes(),str((snapshot/'regions'/target/observed['source_image']).resolve()) if observed.get('source_image') else cid,repr(observed['bbox']) if observed.get('bbox') else cid))
        if len(signatures)==len(ids) and len(set(signatures))==1:
            controls.merge(rs,st,target,ids[1:],ids[0])
        else:
            dst.setdefault('registration_gaps',{})['duplicate_controls']={'reason':'同名控件需结合历史图核对后merge_into，不能直接当新入口生成任务','controls':ids}
    rs=rewrite(rs,aliases);st=rewrite(st,aliases)
    # Inventory coverage must be checked again when source and target differ.
    dst=rs[target]
    if dst.get('local_knowledge'):dst.setdefault('prior_local_knowledge',[]).append(dst.pop('local_knowledge'))
    dst.pop('function_inventory',None)
    if 'task_inventory' in dst and set(dst['task_inventory'].get('controls',[]))!=set(dst['controls']):
        dst['task_inventory']['inventory']='partial'
    st.pop('visual_navigation',None)
    records.clear();records.update(rs);state.clear();state.update(st)
