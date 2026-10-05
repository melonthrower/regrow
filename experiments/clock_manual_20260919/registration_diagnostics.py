"""Read-only acceptance diagnostics. Report independent errors before publication."""
from collections import Counter
import json
import jsonschema
from pathlib import Path

class Rejected(ValueError):
    def __init__(self, report):
        self.report=report
        super().__init__(json.dumps(report,ensure_ascii=False))


def visibility_errors(reply,region_refs,changes):
    current={region_refs[c['region_index']] for c in reply.get('controls',[])
             if isinstance(c.get('region_index'),int) and 0<=c['region_index']<len(region_refs)}-{None}
    errors=[]
    for i,change in enumerate(changes):
        if change.get('region') not in current or change.get('state') not in ('not_visible','visible_background_blocked','uncertain'):continue
        errors.append(dict(code='region_visibility_conflict',path=f'/previous_regions/{i}/state',
            object=reply['previous_regions'][i]['name'],actual=change['state'],
            expected='本轮登记当前控件的同一区块与其可交互状态一致',
            repair='按当前图核对复用身份、可交互状态及控件观察；不能同时登记该区块当前控件又称其不可见、被接管或状态未知。修正有误字段或撤回无依据观察，不为通过校验直接改成可交互。仅归属引用且无本轮直接控件的父区块可保留原状态。'))
    return errors


def check_visibility(reply,region_refs,changes):
    errors=visibility_errors(reply,region_refs,changes)
    if errors:raise Rejected({'errors':errors,'unchecked':[]})


def collect(stage,q,p,records,binding=None):
    errors=[];unchecked=[]
    def add(code,path,obj,actual,expected,repair):
        errors.append(dict(code=code,path=path,object=obj,actual=actual,expected=expected,repair=repair))
    schema=q.get('response_schema')
    if schema:
        if stage=='update' and 'working_context' not in schema.get('properties',{}):
            p={k:v for k,v in p.items() if k!='working_context'}
        for e in jsonschema.Draft202012Validator(schema).iter_errors(p):
            add('schema','/'+ '/'.join(map(str,e.absolute_path)),stage,e.instance,e.message,'按该字段格式修订，不修改其他真实证据。')
        if errors:return {'errors':errors,'unchecked':['结构不合格，依赖这些字段的身份、归属和结果校验尚未执行。']}
    if stage in ('discovery','update'):
        if stage=='discovery':
            import local_partition
            errors.extend(local_partition.errors(q,p))
        ctx=q.get('discovery_context',{});rids=[]
        for i,r in enumerate(p.get('regions',[])):
            previous=r.get('previous_name');rid=None
            parent=r.get('parent_index')
            if parent is not None and (not isinstance(parent,int) or not 0<=parent<len(p['regions']) or parent==i):
                add('parent_region',f'/regions/{i}/parent_index',r['name'],parent,'其他已提交区块索引或null','只登记实际容器关系，不虚构父区块。')
            if stage=='discovery':
                if r.get('identity')=='same':rid=ctx.get('region_names',{}).get(previous)
                if r.get('identity')=='uncertain' or (r.get('identity')=='same')!=bool(previous):
                    add('region_identity',f'/regions/{i}/identity',r['name'],r.get('identity'),'same需有效候选；new需新对象证据','依据截图确认身份，证据不足时补观察。')
            elif r.get('_matched_id') in records:
                rid=r['_matched_id']
            elif previous:
                ids=[q['region_names'][previous]] if previous in q.get('region_names',{}) else [k for k,v in records.items() if v['name']==previous]
                if len(ids)==1:rid=ids[0]
            if previous and rid not in records:
                add('unknown_region',f'/regions/{i}/previous_name',r['name'],previous,list(ctx.get('region_names',{})) if stage=='discovery' else list(q.get('region_names') or [v['name'] for v in records.values()]),'复用本轮可对应的区块名称。')
            rids.append(rid)
            if rid in records and records[rid].get('behavior_context') and r.get('context_matches') is not True:
                add('region_context',f'/regions/{i}/context_matches',r['name'],r.get('context_matches'),
                    records[rid]['behavior_context'],
                    '根据当前截图核对历史适用上下文。匹配才复用；不同则选择正确候选或登记有依据的新区块；不清楚则补观察，不因外观相似填写true。')
        changes=[]
        for i,previous in enumerate(p.get('previous_regions',[])):
            ids=([q['region_names'][previous['name']]] if previous['name'] in q.get('region_names',{})
                 else [rid for rid,r in records.items() if r['name']==previous['name']])
            changes.append({'region':ids[0] if len(ids)==1 and ids[0] in records else None,'state':previous.get('state')})
            if (len(ids)==1 and records[ids[0]].get('behavior_context')
                    and previous.get('state') in ('retained_interactive','changed_interactive')
                    and previous.get('context_matches') is not True):
                add('region_context',f'/previous_regions/{i}/context_matches',previous['name'],previous.get('context_matches'),
                    records[ids[0]]['behavior_context'],
                    '保留旧区块可交互也必须核对当前适用上下文；不匹配不要恢复旧控件，按图2报告实际区块。背景或不可见状态无需此确认。')
        if stage=='update':errors.extend(visibility_errors(p,rids,changes))
        # Every submitted parent edge must form a forest, not just avoid self-parenting.
        reported=set()
        for start in range(len(rids)):
            chain=[];node=start
            while isinstance(node,int) and 0<=node<len(rids):
                if node in chain:
                    cycle=chain[chain.index(node):];key=frozenset(cycle)
                    if key not in reported:
                        reported.add(key)
                        add('parent_cycle',f'/regions/{node}/parent_index',p['regions'][node]['name'],[p['regions'][n]['name'] for n in cycle],'无循环的父子归属','依据实际容器关系修正父级；无父容器时使用null。')
                    break
                chain.append(node);node=p['regions'][node].get('parent_index')
        groups={};seen={};bound={}
        for i,c in enumerate(p.get('controls',[])):
            path=f'/controls/{i}';idx=c['region_index'];name=c.get('name') or c.get('text','');previous=c.get('previous_name')
            if not 0<=idx<len(rids):
                add('owner',path+'/region_index',name,idx,list(range(len(rids))),'归属到本轮实际区块。');continue
            rid=rids[idx];region=records.get(rid,{});controls=region.get('controls',{})
            obj=(region.get('name') or p['regions'][idx]['name'])+' → '+name
            rb=p['regions'][idx].get('bbox');cb=c.get('click_bbox') or c.get('bbox')
            if rb and cb and (cb['right']<=rb['left'] or cb['left']>=rb['right']
                              or cb['bottom']<=rb['top'] or cb['top']>=rb['bottom']):
                add('control_owner_surface',path+'/region_index',obj,{'region_box':rb,'control_box':cb},
                    '同一截图中操作区域与所属区块不应完全分离',
                    '核对区块划分或控件归属。可修正区块范围或挂到实际所属区块；不要改变正确点击位置来迁就旧归属。')
            for j,other in enumerate(p.get('controls',[])[:i]):
                oi=other.get('region_index');ob=other.get('click_bbox') or other.get('bbox')
                if (oi!=idx and isinstance(oi,int) and 0<=oi<len(rids) and cb and cb==ob
                        and name==(other.get('name') or other.get('text',''))
                        and (p['regions'][idx].get('parent_index')==oi or p['regions'][oi].get('parent_index')==idx)):
                    add('duplicate_control_owner',path,obj,{'other':f'/controls/{j}','box':cb},
                        '父子区块同一物理控件只保留一个归属',
                        '核对后只提交实际所属区块中的一份控件；已有重复记录通过现有移动/合并接口保留历史。不同物理对象不可合并。')
            key=(idx,name)
            if key in seen:add('duplicate_submission',path+'/name',obj,name,seen[key],'同一对象只提交一次；不同对象需可区分名称。')
            seen[key]=path
            group=c.get('list_group','')
            if group:
                key=(idx,group)
                if key in groups:add('list_representative',path+'/list_group',obj,group,groups[key],(Path(__file__).parent/'遍历prompt/发现手册/列表代表项.prompt').read_text())
                groups[key]=path
            cid=None
            if stage=='discovery':
                identity=c.get('identity')
                if identity=='uncertain' or (identity=='same')!=bool(previous):add('control_identity',path+'/identity',obj,identity,'same需有效对应；new需新对象证据','核对身份，不把未知编辑能力当作身份不明。')
                if identity=='same':cid=ctx.get('control_names',{}).get(previous)
            elif c.get('_matched_id') in controls:
                cid=c['_matched_id']
            elif previous:
                ids=[k for k,v in controls.items() if v['name']==previous]
                if len(ids)==1:cid=ids[0]
            if previous and cid not in controls:
                owners=[key for key,r in records.items() if cid and cid in r.get('controls',{})]
                if stage=='discovery' and len(owners)==1:
                    add('region_ownership_review',path+'/region_index',obj,
                        {'control_id':cid,'control':previous,'current_region':records[owners[0]]['name']},
                        p['regions'][idx]['name'],'已找到旧控件，但新归属尚未确认；进入实地归属复查，不改名绕过、不凭当前标签猜其他标签的归属。')
                else:
                    add('unknown_candidate_control',path+'/previous_name',obj,previous,list(ctx.get('control_names',{})) if stage=='discovery' else [v['name'] for v in controls.values()],'只用本轮绑定名称；历史存在但未披露时补充候选核对，不能为绕过错误重复新建。')
            if cid:
                if cid in bound:add('duplicate_binding',path+'/previous_name',obj,previous,bound[cid],'同一旧对象只绑定一次。')
                bound[cid]=path
            conflicts=[k for k,v in controls.items() if v['name']==name and k!=cid]
            if conflicts:add('existing_control_conflict',path+'/name',obj,name,{'matching_records':conflicts},'核对旧对象后复用；已重复登记用merge_into保留历史；不同对象用可区分名称。')
    if stage=='task_proposal':
        region=records.get(q.get('source',{}).get('region'),{});controls=region.get('controls',{})
        covered={t['control'] for t in region.get('tasks',{}).values() if t.get('control') in controls}
        for i,op in enumerate(p.get('operations',[])):
            ids=[k for k,c in controls.items() if c['name']==op['control']]
            if op.get('task_type')=='scroll' and not op['control']:continue
            if len(ids)!=1:add('task_owner',f'/operations/{i}/control',op['name'],op['control'],{'matches':ids},'多条匹配先核对并修订重复记录；无匹配先发现登记，不猜控件名称。')
            else:covered.add(ids[0])
        if p.get('inventory')=='complete' and covered!=set(controls):
            add('inventory_coverage','/operations',region.get('name'),sorted(covered),[c['name'] for k,c in controls.items() if k not in covered],'修订重复记录后覆盖保留控件；未清点完整填写partial并说明缺口。')
    if stage=='update' and binding:
        owner=records.get(binding.get('task_region',binding.get('region_ref')),{});task=owner.get('tasks',{}).get(binding.get('task_name'),{})
        for i,previous in enumerate(p.get('previous_regions',[])):
            matches=[q['region_names'][previous['name']]] if previous['name'] in q.get('region_names',{}) else [k for k,v in records.items() if v['name']==previous['name']]
            if len(matches)!=1 or matches[0] not in records:add('previous_region',f'/previous_regions/{i}/name',previous['name'],previous['name'],list(q.get('region_names') or [v['name'] for v in records.values()]),'按本轮候选完整名称报告可见性；同名不意味着同一区块。')
        assessment=p.get('task_update') or p.get('task_result') or {}
        for i,fact in enumerate(assessment.get('findings',[])):
            old=task.get('findings',{}).get(fact['name'])
            if old and (old['domain']['type']!=fact['domain']['type']):
                add('parameter_fact_conflict',f'/task_update/findings/{i}',fact['name'],{'conditions':fact['conditions'],'type':fact['domain']['type']},{'conditions':old['conditions'],'type':old['domain']['type']},'不同类型的参数使用不同事实名称；条件变化可按新观察保存。')
    return {'errors':errors,'unchecked':unchecked}


def check(stage,q,p,records,binding=None):
    report=collect(stage,q,p,records,binding)
    if report['errors']:raise Rejected(report)
    return report
