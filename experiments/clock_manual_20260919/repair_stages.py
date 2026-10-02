"""Stage-owned acceptance, evidence refresh and narrowly scoped record revisions."""
from copy import deepcopy
import json
from pathlib import Path
import jsonschema
import importlib.util


class BindingConflict(ValueError):
    blocked_by="binding_conflict"


class StaleActionSource(BindingConflict):
    refresh_request=True


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def preserve_repair_aliases(original,refreshed,records):
    """Names in the submitted proposal belong to its pre-edit request."""
    old=original.get('discovery_context',{});new=refreshed['discovery_context']
    for label,rid in old.get('region_names',{}).items():
        if rid in records:new['region_names'][label]=rid
    allowed=set(old.get('region_names',{}).values())
    for label,cid in old.get('control_names',{}).items():
        matches=[key for rid,r in records.items() if rid in allowed for key,c in r['controls'].items()
                 if key==cid or any(item['id']==cid for item in c.get('merged_records',[]))]
        if len(matches)==1:new['control_names'][label]=matches[0]


def accept(root,run,job):
    scope=helper('foreground_scope').audit(run,job)
    result=accept_with_edits(root,run,job)
    helper('foreground_scope').remember(run,scope)
    return result


def accept_with_edits(root,run,job):
    reg=helper('register_update')
    if job.get('suspended_recovery') and job.get('record_edit'):
        from step_repair import Paused
        raise Paused('historical_update_conflict','历史补登记不能顺带改写当前身份或任务；保留原证据待核对')
    if job.get('record_edit'):
        with reg.sibling('knowledge_transaction').transaction(run):
            if job['request'].get('historical_inventory'):
                _,before,_=helper('discovery_step').load(run)
                helper('historical_inventory').validate(before[job['request']['source']['region']],job['request'])
            edit_record(root,run,job,job['record_edit'])
            if job['stage']=='update':
                _,records,_=helper('discovery_step').load(run)
                refreshed=deepcopy(job['request'])
                for label,rid in refreshed.get('region_names',{}).items():
                    if rid in records:continue
                    targets=[key for key,r in records.items() if any(v.get('id')==rid for v in r.get('merged_records',[]))]
                    if len(targets)==1:refreshed['region_names'][label]=targets[0]
                job={**job,'request':refreshed}
                reg.write_json(Path(run)/'calls'/job['call']/'effective_request.json',refreshed)
            if job['request'].get('historical_inventory'):
                refreshed=refresh(root,run,job)
                job={**job,'request':refreshed}
                reg.write_json(Path(run)/'calls'/job['call']/'effective_request.json',refreshed)
            if job['stage'] in ('discovery','task_result_review'):
                refreshed=refresh(root,run,job)
                _,records,_=helper('discovery_step').load(run)
                if job['stage']=='discovery':preserve_repair_aliases(job['request'],refreshed,records)
                job={**job,'request':refreshed}
                reg.write_json(Path(run)/'calls'/job['call']/'effective_request.json',job['request'])
            return accept_candidate(root,run,job)
    return accept_candidate(root,run,job)


def accept_candidate(root,run,job):
    _,records,_=helper('discovery_step').load(run)
    binding=None
    if job.get('attempt'):
        binding=helper('register_update').read(Path(run)/'action_attempts'/job['attempt']/'binding.json')
    q=job['request']
    # A record rename changes the task's valid names in this same transaction.
    if job.get('record_edit') and job['stage']=='task_proposal':
        q=deepcopy(q);q['response_schema']=helper('region_tasks').proposal_schema()
    if job['stage']=='discovery' and job.get('candidate') is not None:
        report=helper('ownership_review').conflict(q,job['candidate'],records)
        if report:raise helper('registration_diagnostics').Rejected(report)
    if job['stage'] in ('discovery','update') and job.get('candidate') is not None:
        q,candidate,_=helper('region_identity').prepare(run,q,job['candidate'])
        job={**job,'candidate':candidate}
    if job.get('candidate') is not None and job['stage']!='discovery':
        helper('registration_diagnostics').check(job['stage'],q,job['candidate'],records,binding)

    stage=job['stage'];ref=job['call']
    if stage in ('discovery','task_proposal','function_registration','task_result_review'):
        snapshot,_,_=helper('discovery_step').load(run)
        source=helper('register_update').read(snapshot/'source.json')
        tag={'discovery':'discovery-','task_proposal':'task-plan-','function_registration':'functions-','task_result_review':'task-review-'}[stage]+ref
        if source.get('stage')==tag:return helper('register_update').read(Path(run)/'knowledge_current.json')
    if stage=='discovery':return helper('discovery_step').commit(root,run,ref)
    if stage=='task_proposal':return helper('region_tasks').commit_plan(root,run,ref)
    if stage=='function_registration':return helper('region_functions').commit(root,run,ref)
    if stage=='task_result_review':return helper('task_result_review').commit(root,run,ref)
    if stage=='update':return helper('register_update').commit_update(root,run,None,ref,job['attempt'])
    if stage=='action':
        q,proposal=helper('step_repair').submission(run,ref)
        manifest=Path(run)/'run_manifest.json'
        platform='desktop' if manifest.exists() and helper('register_update').read(manifest).get('desktop') else 'android'
        jsonschema.validate(proposal,q['response_schema']);helper('action_commands').validate(proposal,platform)
        proposal=helper('action_commands').normalize(proposal)
        if proposal.get('request_task_review'):
            src=q.get('source',{});rid=src.get('task_region') or src.get('region')
            if records.get(rid,{}).get('tasks',{}).get(src.get('task_name'),{}).get('status')!='pending':raise ValueError('结果核对需要已登记的pending任务')
        binding=helper('stepwise_flow').bind_action_target(q,proposal)
        if binding['status'] not in ('matched','no_action'):raise BindingConflict('动作绑定失败：'+binding.get('reason',binding['status']))
        if binding['status']=='matched':
            current_state=helper('discovery_step').load(run)[2]
            if binding.get('observation_ref')!=(current_state.get('observation') or {}).get('id'):
                raise StaleActionSource('动作来源观察已过期；请按原任务刷新当前观察上下文，旧截图来源不能继续投递')
            helper('action_commands').commands(proposal,platform)
            helper('attempt_guard').check(run,helper('discovery_step').load(run)[1],binding,proposal,(q.get('screenshots') or q.get('image_refs') or [None])[0],correction=job.get('repairs',0)>0)
        return {'binding':binding,'proposal':proposal,'request':q,'call':ref}
    raise RuntimeError('Unknown acceptance stage: '+stage)


def related(run,job):
    _,records,state=helper('discovery_step').load(run)
    q=job['request'];refs=set(q.get('discovery_context',{}).get('region_names',{}).values())
    if job['stage']=='update':refs.update(q.get('region_names',{}).values())
    refs.update(v for k,v in q.get('source',{}).items() if k in ('region','working_region','task_region'))
    if job.get('attempt'):
        binding=helper('register_update').read(Path(run)/'action_attempts'/job['attempt']/'binding.json')
        refs.update(binding.get(k) for k in ('region_ref','working_region','task_region'))
    if not refs:refs.add(state.get('working_region'))
    if job['stage'] in ('action','task_proposal','function_registration'):
        source=q.get('source',{})
        selected={source.get('region'),source.get('task_region')}
        if any(r in records for r in selected):refs=selected
    if job['stage'] in ('discovery','update'):
        names={records[r]['name'] for r in refs if r in records}
        refs.update(r for r,item in records.items() if item['name'] in names)
    result={r:deepcopy(records[r]) for r in sorted(refs-{None}) if r in records}
    if job['stage']=='update' and job.get('candidate'):
        names={v for c in job['candidate'].get('controls',[]) for k in ('name','previous_name') if (v:=c.get(k))}
        binding=helper('register_update').read(Path(run)/'action_attempts'/job['attempt']/'binding.json') if job.get('attempt') else {}
        for rid,r in result.items():
            r['controls']={cid:c for cid,c in r['controls'].items() if c['name'] in names or cid==binding.get('control_ref')}
            r['tasks']={name:t for name,t in r.get('tasks',{}).items() if t.get('control') in r['controls']}
    if job['stage']=='action':
        source=q.get('source',{});owner=source.get('task_region') or source.get('region');name=source.get('task_name')
        task=result.get(owner,{}).get('tasks',{}).get(name)
        if task is not None:
            for rid,r in result.items():
                ids={task.get('control')} if rid==owner else {c['id'] for c in q.get('backend_candidates',[])}
                target=(job.get('candidate') or {}).get('target')
                ids.update(c['id'] for c in q.get('backend_candidates',[]) if c['name']==target)
                r['controls']={cid:c for cid,c in r['controls'].items() if cid in ids}
                r['tasks']={name:task} if rid==owner else {}
    if q.get('action_owner_candidates'):
        scoped={}
        for candidate in q['action_owner_candidates']:
            for prefix in ('from','to'):
                scoped.setdefault(candidate[prefix+'_region'],set()).add(candidate[prefix+'_control'])
        result={rid:r for rid,r in result.items() if rid in scoped}
        for rid,r in result.items():
            names={n for n,t in r.get('tasks',{}).items() if t.get('control') in scoped[rid]}
            names.update(n for n,t in r.get('tasks',{}).items() if t.get('equivalent_to') in names)
            r['tasks']={n:t for n,t in r.get('tasks',{}).items() if n in names}
            ids=scoped[rid] | {t.get('control') for t in r['tasks'].values()}
            r['controls']={cid:c for cid,c in r['controls'].items() if cid in ids}
    return result


def record_capabilities(stage=None):
    historical=['edit_record观察归属纠正：仅本轮control_observation_candidates披露的region/from_control/to_control/retained_name/observations(source_call,source_field)/evidence；只迁移指定观察，不迁移任务或动作，不能整条合并。retained_name必须描述迁移后来源控件剩余观察的职责，不能沿用被移走对象的名称。',
                'edit_record动作归属纠正：attempt/from_region/from_control/to_region/to_control/evidence，只改一笔已执行动作的有效对象；必须提供原前后图及当时目标控件身份，不迁移整个控件，不改原投递。旧完成依据撤回，新任务仍须结果核对。']
    return ([] if stage=='action' else historical)+[
            'edit_record / task_control或suspend_task：在发现/任务清点中用task选择任务；无历史pending可改到披露的唯一控件，有历史只暂挂保留旧事实并重新清点。',
            'edit_record：修订区块description或控件name/description/list_group（可清空错误分组），提供原值、新值和证据。',
            'edit_record / region：同一控件误归区块时，region及before写原区块，control写控件，after写已披露的正确区块；保留身份、历史和任务状态，不能移动待结算动作来源。',
            'edit_record / merge_into：同一物理控件的重复记录可合并；完全同名可用同名作为来源和目标，迁移历史及任务引用。',
            'edit_record / merge_into（区块）：control留空，region与before写重复区块名称，after写保留区块名称，提供同一物理区块的证据；合并本轮披露的对应区块并迁移引用。',
            'edit_record / remove：可删除无动作、任务或跳转引用的误登记控件；已有历史不能直接删除。',
            'revise也可同时填写record_edit和完整proposal；框架在私有快照中检查整批修改，全部通过后一起发布。']


def context(run,job):
    if job['stage']=='shared_control_review':
        return {'开放能力':['edit_record/shared_behavior：核对已披露共享成员，解除该成员共享或依据证据保留共享；原动作不变']}
    records=related(run,job)
    _,history_records,_=helper("discovery_step").load(run)
    describe=helper("task_attempt_context").describe
    target=helper('target_observation').describe
    observation=job['request'].get('source',{}).get('observation')
    def task_view(region,name,task):
        # Use the full owning record: related() may retain only the failed task.
        owner=next((r for r in history_records.values() if r.get('id')==region.get('id') and r.get('name')==region.get('name')),region)
        covered=task.get('equivalent_to') if task.get('handling')=='equivalent' else None
        effective=owner.get('tasks',{}).get(covered,task) if covered else task
        return {'名称':name,'入口':region['controls'].get(task.get('control'),{}).get('name',region['name']),
                '状态':effective['status'],'处理方式':task.get('handling'),'覆盖任务':covered,
                '说明':task['reason'],'动作':task.get('action'),'类型':task.get('task_type'),
                '尝试事实':describe(effective,history_records)}
    value={'区块':[{'名称':r['name'],'描述':r['description'],
                   '控件':[{'名称':c['name'],'说明':c.get('description',''),'列表分组':c.get('list_group',''),'视觉描述':c.get('icon_description') or (c.get('observations') or [{}])[-1].get('icon_description',''),'目标观察':target(c,observation),'已登记动作数':len(c.get('action_refs',[]))} for c in r['controls'].values()],
                   '任务':[task_view(r,n,t) for n,t in r.get('tasks',{}).items()]} for r in records.values()],
            '开放能力':['修正本轮完整提案','补充一次观察，之后回原步骤','defer：提议暂挂当前局部问题，框架确认后选择其他已登记独立任务',
                     *record_capabilities(job['stage'])]}

    source=job['request'].get('source',{});owner=source.get('task_region') or source.get('region');name=source.get('task_name')
    region=records.get(owner,{})
    if job['stage']=='action' and name in region.get('tasks',{}):
        task=region['tasks'][name];control=region['controls'].get(task.get('control'),{})
        value['任务目标']={'区块':region['name'],'任务':name,'控件':control.get('name')}
        proposal=job.get('candidate') or {}
        value['失败对象']={**value['任务目标'],'控件':proposal.get('target') or control.get('name'),
                         '动作':proposal.get('action'),'依据':'被拒绝回复的实际操作对象' if proposal.get('target') else '尚无动作提案，沿用原任务对象'}
        owners=[r['name'] for r in records.values() if any(c['name']==value['失败对象']['控件'] for c in r['controls'].values())]
        value['失败对象']['区块']=owners[0] if len(owners)==1 else None
        value['本轮约束']={k:job['request'][k] for k in ('allow_back','allow_input','allow_scroll','region_target','navigation_path') if k in job['request']}
    if job.get('blocked_by')=='binding_conflict':
        _,all_records,state=helper('discovery_step').load(run)
        q=job['request'];source=q.get('source',{});targets={source.get('region'),source.get('task_region')}
        incoming=[];seen=set()
        for rid,r in all_records.items():
            for edge in r.get('transitions',[]):
                cid=edge.get('source_control');control=r.get('controls',{}).get(cid)
                if edge.get('target_region') not in targets or not control or (rid,cid) in seen:continue
                seen.add((rid,cid))
                incoming.append({'区块':r['name'],'控件':control['name'],
                    '历史外观':target(control,None),'历史目的区块':all_records.get(edge['target_region'],{}).get('name'),
                    '说明':'这是历史进入入口，不是已确认当前可交互的候选；结合截图判断。'})
        proposal=job.get('candidate') or {}
        value['定位与绑定冲突']={
            '框架认定的当前区块':[all_records[r]['name'] for r in state.get('interactive_regions',[]) if r in all_records],
            '模型建议目标':proposal.get('target'),'模型建议位置':[proposal.get('x'),proposal.get('y')],
            '当前动作候选':[{'区块':all_records.get(c.get('region_ref',source.get('region')),{}).get('name'),
                '控件':c['name'],'匹配位置':q.get('visual_choices',{}).get(c['id'],[])} for c in q.get('backend_candidates',[])],
            '框架拒绝依据':job.get('error'),'历史进入目标的入口':incoming,
            '处理说明':'候选为空仅表示框架没有定位记录，不证明截图没有按钮。核对框架落点；落点错误用observe重定位并刷新候选，再回动作步执行。菜单选项与打开菜单的按钮是不同对象，不能通过改名相互替换。'}
    if job['stage']=='action':
        source=job['request'].get('source',{});rid=source.get('task_region') or source.get('region')
        task=history_records.get(rid,{}).get('tasks',{}).get(source.get('task_name'),{})
        evidence=[]
        for attempt in task.get('attempts',[])[-2:]:
            folder=Path(run)/'action_attempts'/attempt
            item={'尝试':attempt}
            for key,file in [('提案','proposal.json'),('执行回执','receipt.json')]:
                path=folder/file
                if path.is_file():item[key]=json.loads(path.read_text())
            for key,file in [('动作前图','before.png'),('动作后图','after.png')]:
                path=folder/file
                if path.is_file():item[key]=str(path.resolve())
            evidence.append(item)
        value['最近尝试原始证据']=evidence
    return value


def refresh(root,run,job):
    discovery=helper('discovery_step');_,records,state=discovery.load(run)
    stage=job['stage'];old=job['request']
    if stage=='task_result_review':return helper('task_result_review').request(root,run,old['source'],old['screenshots'])
    if stage=='discovery':return discovery.request_from_run(root,run)
    if stage in ('task_proposal','function_registration'):
        rid=old['source']['region']
        if stage=='task_proposal' and old.get('historical_inventory'):
            saved=deepcopy(state)
            saved['observation']={'id':old['source']['observation'],'image':old['screenshots'][0],'control_refs':[]}
            q=helper('region_tasks').plan_request(root,records,saved,rid)
            q['historical_inventory']={'evidence_digest':helper('historical_inventory').digest(records[rid])}
            q['user_prompt']=q['dynamic_prompt']=q['user_prompt']+'\n材料是原历史截图；记录已按本次显式修订刷新，不表示当前可见。'
            return q
        if rid not in state['interactive_regions']:raise ValueError('原任务区块当前未确认可交互，不能将修复转成其他任务')
        if stage=='task_proposal':return helper('region_tasks').plan_request(root,records,state,rid)
        return helper('region_functions').request(root,records[rid],state,records)
    if stage=='action':
        src=old.get('source',{})
        task_ref={'region':src.get('task_region',src.get('region')),'name':src['task_name']} if src.get('task_name') else None
        q=helper('stepwise_flow').assemble_current_context(root,run,src.get('working_region'),task_ref=task_ref)
        for key in ('task_name','task_region'):
            if q.get('source',{}).get(key)!=old.get('source',{}).get(key):raise ValueError('补观察改变了原动作任务；保留原任务等待定位')
        if not q.get('action_ready'):raise ValueError('原动作任务仍未定位')
        frame=str((Path(run)/state['observation']['image']).resolve())
        q.update(role='action_selection',screenshots=[frame],image_refs=[frame])
        helper('region_scroll').attach(run,state,q)
        if job.get('pre_dispatch_review'):
            job.setdefault('pre_dispatch_review_history',[]).append({
                'evidence':job.pop('pre_dispatch_review'),'invalidated_by':'action_request_refresh'})
        return q
    # Preserve original before/after frames, source binding, task and receipt.
    q=deepcopy(old)
    text=old['user_prompt']+'\n核对后的相关记录：\n'+json.dumps(context(run,job),ensure_ascii=False)
    q['user_prompt']=q['dynamic_prompt']=text;return q


def edit_record(root,run,job,edit):
    if job['stage']=='shared_control_review':
        if isinstance(edit,list):raise ValueError('共享核对每次处理一个成员')
        case=job['request']['shared_control_conflict']
        def revise(records,state,snapshot,temp):
            helper('shared_control_review').apply(records,state,case,edit,job['call'])
        return helper('discovery_step').publish(run,'shared-review-'+job['call'],revise)
    edits=edit if isinstance(edit,list) else [edit]
    if not edits:raise ValueError('empty record edits')
    if job['stage']=='action' and any('attempt' in item or 'observations' in item for item in edits):
        raise ValueError('单图动作纠错不能迁移历史动作或观察归属；保留原证据，进入历史核对')
    if not (job['request'].get('screenshots') or job.get('supplements')):raise ValueError('无图像依据时不开放视觉记录修订')
    allowed=related(run,job)
    def mutate(records,state,snapshot,temp):
        scope=deepcopy(allowed)
        migrations={};merges=[]
        for item in edits:
            if not item['evidence'].strip():raise ValueError('记录修订需要证据')
            if 'observations' in item:
                bound=helper('control_observation_repair').validate_scope(run,job,item,records,scope)
                helper('control_observation_repair').apply(records,state,bound,job['call'])
                continue
            if 'attempt' in item:
                if job.get('attempt') or (Path(run)/'execution_pending.json').exists():
                    raise ValueError('先完成待结算动作，不能借历史纠正改写当前执行')
                for region_key,control_key in [('from_region','from_control'),('to_region','to_control')]:
                    matches=[r for r in scope.values() if r['name']==item[region_key]
                             and any(c['name']==item[control_key] for c in r['controls'].values())]
                    if len(matches)!=1:raise ValueError('动作纠正对象不在本轮披露范围')
                candidates=job['request'].get('action_owner_candidates',[])
                if not any(c['attempt']==item['attempt'] and all(
                    records[c[p+'_region']]['name']==item[p+'_region'] and records[c[p+'_region']]['controls'][c[p+'_control']]['name']==item[p+'_control']
                    for p in ('from','to')) for c in candidates):
                    raise ValueError('这笔历史动作及归属候选没有随本轮披露')
                action_dir=Path(run)/'action_attempts'/item['attempt']
                provided={str((Path(run)/f).resolve()) for f in job['request'].get('screenshots',[])}
                if Path(item['attempt']).name!=item['attempt'] or not all(str((action_dir/f).resolve()) in provided for f in ['before.png','after.png']):
                    raise ValueError('动作归属纠正必须提供该笔动作原前后图')
                if job['request'].get('source',{}).get('snapshot')!=str((helper('discovery_step').load(run)[0]).relative_to(Path(run).resolve())):
                    raise ValueError('动作归属纠正快照已变化')
                helper('action_owner_correction').apply(records,state,item,job['call'],snapshot)
                continue
            matches=[rid for rid,r in scope.items() if r['name']==item['region']]
            if 'task' in item:
                if len(matches)!=1 or item['task'] not in scope[matches[0]].get('tasks',{}):raise ValueError('任务不在本轮修订范围')
                rid=matches[0]
                if item['field']=='task_control' and not any(c['name']==item['after'] for c in scope[rid]['controls'].values()):raise ValueError('目标控件未在本轮披露，先补观察')
                if job['stage'] not in ('task_proposal','discovery'):raise ValueError('任务归属请在补发现后的任务清点中修订，不能改变执行中的绑定')
                helper('task_record_repair').apply(records[rid],state,item,job['call'])
                continue
            if item['field']=='merge_into' and not item['control']:
                targets=[rid for rid,r in scope.items() if r['name']==item['after']]
                if not matches or not targets or item['before']!=item['region']:
                    raise ValueError('区块合并来源或目标不在本轮范围')
                if item['region']!=item['after'] and len(targets)!=1:raise ValueError('区块合并目标不唯一')
                # Retain current execution source, so immutable dispatch remains valid.
                binding=helper('register_update').read(Path(run)/'action_attempts'/job['attempt']/'binding.json') if job.get('attempt') else {}
                target=binding.get('region_ref') if binding.get('region_ref') in targets else sorted(targets)[0]
                disclosed_controls={cid for key in set(matches+[target]) for cid in scope[key]['controls']}
                helper('region_records').merge(records,state,matches,target,snapshot=snapshot,
                    rebase=helper('register_update').rebase,evidence=item['evidence'])
                for key in matches:
                    if key!=target:scope.pop(key,None)
                scope[target]=deepcopy(records[target])
                scope[target]['controls']={cid:c for cid,c in scope[target]['controls'].items() if cid in disclosed_controls}
                continue
            if len(matches)!=1:raise ValueError('修订区块不在本轮范围或名称有歧义')
            rid=matches[0];r=records[rid];field=item['field']
            names=[cid for cid,c in r['controls'].items() if c['name']==item['control']]
            if any(cid not in scope[rid]['controls'] for cid in names):raise ValueError('控件不在本轮修订范围')
            if field=='region':
                targets=[key for key,value in scope.items() if value['name']==item['after']]
                if len(names)!=1 or len(targets)!=1 or targets[0]==rid or item['before']!=r['name']:
                    raise ValueError('控件归属修订需要唯一已披露来源及不同目标区块，原值必须一致')
                if not job.get('attempt') and (Path(run)/'execution_pending.json').exists():
                    raise ValueError('待结算动作未随本轮披露，不能迁移控件')
                binding=helper('register_update').read(Path(run)/'action_attempts'/job['attempt']/'binding.json') if job.get('attempt') else {}
                if binding.get('control_ref')==names[0] or any(t.get('control')==names[0] and
                        binding.get('task_region')==rid and binding.get('task_name')==name for name,t in r.get('tasks',{}).items()):
                    raise ValueError('不能迁移待结算动作的来源控件或任务')
                episode=migrations.setdefault(rid,{'source_region':rid,'conflicts':{},'assignments':{},'targets':{}})
                if names[0] in episode['assignments']:raise ValueError('同一批次控件归属重复修订')
                episode['assignments'][names[0]]={'region':item['after'],'description':records[targets[0]]['description'],
                    'evidence':item['evidence'],'call':job['call']}
                episode['targets'][item['after']]=targets[0]
            elif field=='merge_into':
                targets=[cid for cid,c in r['controls'].items() if c['name']==item['after']]
                if any(cid not in scope[rid]['controls'] for cid in targets):raise ValueError('合并目标不在本轮修订范围')
                if not names or not targets or item['before']!=item['control']:raise ValueError('merge source/target mismatch')
                if len(targets)>1 and item['control']!=item['after']:raise ValueError('merge destination ambiguous')
                merges.append({'region':rid,'name':item['control'],'target':targets[0],'sources':set(names)})
            elif field=='remove':
                if len(names)!=1 or item['before']!=item['control']:raise ValueError('remove source ambiguous')
                helper('control_records').remove(records,state,rid,names[0])
            else:
                if field!='list_group' and not item['after'].strip():raise ValueError('记录修订内容不能为空')
                if item['control']:
                    if len(names)!=1:raise ValueError('控件修订对象不唯一：'+str(names))
                    if field not in ('name','description','list_group'):raise ValueError('控件只支持名称、描述或列表分组修订')
                    if field=='name' and any(cid!=names[0] and c['name']==item['after'] for cid,c in r['controls'].items()):raise ValueError('修订会产生重复控件名称')
                    target=r['controls'][names[0]]
                else:
                    if field!='description':raise ValueError('区块只允许描述修订')
                    target=r
                if target.get(field,'')!=item['before']:raise ValueError('修订原值已变化')
                target[field]=item['after']
        active=deepcopy(state.get('active_task'))
        merge_controls=set()
        for source,episode in migrations.items():
            for cid,item in episode['assignments'].items():
                target=episode['targets'][item['region']];name=records[source]['controls'][cid]['name']
                collisions={key for key,c in records[target]['controls'].items() if c['name']==name}
                matching=[m for m in merges if m['region']==target and m['name']==name and
                          records[target]['controls'][m['target']]['name']==name and collisions<=m['sources']]
                if collisions and len(matching)==1:
                    merge_controls.add((target,cid,frozenset(collisions)))
                    matching[0]['sources'].add(cid)
        for rid,episode in migrations.items():
            helper('ownership_review').repartition(records,state,episode,snapshot,existing_targets=episode['targets'],merge_controls=merge_controls)
            if active and active.get('region')==rid and active.get('name') not in records[rid].get('tasks',{}):
                destinations=[key for key in episode['targets'].values() if active.get('name') in records[key].get('tasks',{})]
                if len(destinations)==1:active['region']=destinations[0]
        for merge in merges:
            helper('control_records').merge(records,state,merge['region'],sorted(merge['sources']-{merge['target']}),merge['target'])
        if active:state['active_task']=active
        helper('register_update').write_json(temp/'record_revision.json',{'source_call':job['call'],'edit':edit})
    helper('discovery_step').publish(run,'record-revision-'+job['call'],mutate)


def update_observation_request(root,run,job,frame):
    """Answer a repair question without changing inventory or action evidence."""
    _,records,_=helper('discovery_step').load(run)
    original=job['request'];candidate=job.get('candidate') or {}
    names={v for item in candidate.get('regions',[]) for key in ('name','previous_name') if (v:=item.get(key))}
    controls={v for item in candidate.get('controls',[]) for key in ('name','previous_name') if (v:=item.get(key))}
    related=[]
    for rid in dict.fromkeys(original.get('region_names',{}).values()):
        region=records.get(rid)
        if not region:continue
        matches=[c for c in region['controls'].values() if c['name'] in controls]
        if region['name'] not in names and not matches:continue
        related.append({'区块':region['name'],'历史描述':region['description'],
                        '相关控件':[{'名称':c['name'],'说明':c.get('description','')} for c in region['controls'].values()]})
    attempt=Path(run)/'action_attempts'/job['attempt']
    frames=[str((attempt/name).resolve()) for name in ('before.png','after.png')]+[str(Path(frame).resolve())]
    path='纠错/更新补充观察.prompt';text=(Path(root)/'遍历prompt'/path).read_text()
    dynamic={'待核对问题':job['observation_question'],'相关历史记录':related,
             '图片说明':['第一张是原动作前保存证据，不能视为严格投递瞬间。','第二张是原动作后图，仅说明原动作后的时点。','第三张是稍后的补充观察，不是重新执行动作后的图。'],
             '记录范围':'仅检索原请求已披露区块；未列出不代表不存在。候选提案只用于检索，不是身份结论。'}
    return {'pipeline_step':'update','stage':'step_observation','role':'step_observation',
            'system_prompt':text,'user_prompt':json.dumps(dynamic,ensure_ascii=False),
            'screenshots':frames,'fixed_parts':[{'path':path,'text':text}],
            'response_schema':{'type':'object','properties':{'evidence':{'type':'string','minLength':1}},
                               'required':['evidence'],'additionalProperties':False}}


def observe(runner,job):
    discovery=helper('discovery_step');reg=helper('register_update')
    if job['stage'] in ('action','task_proposal','function_registration'):
        return observe_registered(runner,job)
    if job['observations']>=1:raise ValueError('补观察已尝试；使用已保存证据，不重复调用')
    folder=runner.run/Path(job['path']).parent;frame=folder/'supplement.png'
    # Never overwrite a saved supplementary frame on restart.
    if not frame.exists():runner.screenshot(frame)
    if job['stage']=='update':
        q=update_observation_request(runner.root,runner.run,job,frame)
    else:
        _,records,state=discovery.load(runner.run)
        local=deepcopy(state);local['inspection_region']=job['request'].get('source',{}).get('region') or state.get('working_region')
        discovery.focus_task(records,local,job['request'])
        snapshot,_,_=discovery.load(runner.run)
        for rid,r in records.items():
            for v in r['observations']+[v for c in r['controls'].values() for v in c['observations']]:
                if v.get('image'):v['image']=str((snapshot/'regions'/rid/v['image']).resolve())
        q=discovery.prepare(runner.root,records,local,str(frame.resolve()))
        queries=[r for r in (job.get('candidate') or {}).get('regions',[]) if r.get('identity')=='uncertain']
        if queries and not q['discovery_context'].get('completion'):
            q=helper('discovery_completion').recall_into_request(q,records,queries)
        dynamic=json.loads(q['user_prompt']);dynamic['历史疑问（不代表本轮仍缺失）']=job['observation_question'];dynamic['本轮要求']='依据本轮候选和截图重新核对，已补齐的历史信息不再作为缺口。'+local.get('correction_context','')
        dynamic['用途']='补充观察，不推断原动作效果；输出后回到原失败步骤'
        manifest=reg.read(runner.run/'run_manifest.json') if (runner.run/'run_manifest.json').exists() else {}
        dynamic['目标应用']=manifest.get('app','')
        q['user_prompt']=json.dumps(dynamic,ensure_ascii=False)
    job['observations']+=1;runner.save(job)
    ref,reply=runner.call(q)
    # A supplemental call has its own sent contract, not the original step's.
    q=runner.sent_request(job,q,ref,repairing=True)
    # Evidence must survive rejection; preserving it does not register identities.
    evidence={'source_call':ref,'image':str(frame.resolve()),'reply':reply,
              'validation':{'status':'pending'}}
    job['supplements'].append(evidence)
    runner.save(job)
    try:
        jsonschema.validate(reply,q['response_schema'])
        if job['stage']!='update':discovery.validate_identity(reply)
    except (ValueError,jsonschema.ValidationError) as error:
        evidence['validation']={'status':'rejected','error':helper('step_repair').diagnostic(error)}
        runner.save(job)
        raise
    evidence['validation']={'status':'validated'}
    runner.save(job)
    if job['stage']!='update':
        def await_frame(records,state,snapshot,temp):
            state.update(next_action_mode='discover',pending_frame=str(frame.resolve()))
        discovery.publish(runner.run,'repair-observe-'+ref,await_frame)
        if job['stage']!='discovery':discovery.commit(runner.root,runner.run,ref)
        job['request']=refresh(runner.root,runner.run,job)
        job.pop('requires_observation',None)
    job['error']='补充观察已取得，请结合证据修复原步骤；补观察不是原动作后图'


def observe_registered(runner,job):
    """Supplementary discovery uses its own discovery contract and resumable repair."""
    discovery=helper('discovery_step');repair=helper('step_repair')
    folder=runner.run/Path(job['path']).parent;frame=folder/'supplement.png'
    pointer=str(Path(job['path']).parent/'pending_observation.json')
    child=type(runner)(runner.root,runner.run,runner.call,runner.screenshot,runner.available,pointer)
    q=None
    registered=any(v.get('image')==str(frame.resolve()) for v in job.get('supplements',[]))
    if not repair.pending(runner.run,pointer) and not registered:
        if job['observations']>=1:raise ValueError('补观察已尝试；使用已保存证据，不重复调用')
        if not frame.exists():runner.screenshot(frame)
        snapshot,records,state=discovery.load(runner.run);local=deepcopy(state)
        discovery.focus_task(records,local,job['request'])
        if job.get('blocked_by')=='binding_conflict':
            local['discovery_mode']='relocate';local.pop('inspection_region',None);local.pop('required_control',None)
        for rid,r in records.items():
            for v in r['observations']+[v for c in r['controls'].values() for v in c['observations']]:
                if v.get('image'):v['image']=str((snapshot/'regions'/rid/v['image']).resolve())
        q=discovery.prepare(runner.root,records,local,str(frame.resolve()))
        dynamic=json.loads(q['user_prompt'])
        dynamic.update(历史疑问=job['observation_question'],用途='补充当前定位；不推断原动作效果。')
        manifest=runner.run/'run_manifest.json'
        if manifest.exists():dynamic['目标应用']=json.loads(manifest.read_text()).get('app','')
        q['user_prompt']=q['dynamic_prompt']=json.dumps(dynamic,ensure_ascii=False)
        def await_frame(records,state,*args):state.update(next_action_mode='discover',pending_frame=str(frame.resolve()))
        discovery.publish(runner.run,'repair-observe-'+folder.name,await_frame)
        job['observations']+=1;runner.save(job)
    # One observation episode can contain global relocation followed by local controls.
    # Save each completed discovery so a budget pause resumes the unfinished stage.
    while q is not None or repair.pending(runner.run,pointer) or discovery.load(runner.run)[2].get('next_action_mode')=='discover':
        completed=sum(v.get('image')==str(frame.resolve()) for v in job.get('supplements',[]))
        if completed>=3:raise ValueError('本次补观察的发现流程仍未完成；保留已取得证据')
        if q is None and not repair.pending(runner.run,pointer):q=discovery.request_from_run(runner.root,runner.run)
        result=child.perform('discovery',q)
        job['supplements'].append({'source_call':result['call'],'image':str(frame.resolve()),'reply':result['candidate']})
        runner.save(job);q=None
        if job['stage']=='action' and helper('inventory_scroll').resume_after_region_observation(
                runner.run,job['request'],result['call']):
            break
    job['request']=refresh(runner.root,runner.run,job)
    job.pop('requires_observation',None)
    job['error']='补充定位已登记；使用刷新后的候选继续原任务。'


def edit_proposal(run,job,edits):
    """Apply matching field edits to an uncommitted proposal before publishing it."""
    if job['stage'] not in ('discovery','update'):return False
    candidate=deepcopy(job.get('candidate') or {})
    if not candidate.get('regions'):return False
    for edit in edits if isinstance(edits,list) else [edits]:
        if not edit or edit.get('field') not in ('name','description','list_group') or not edit['evidence'].strip():return False
        matches=[(i,r) for i,r in enumerate(candidate['regions']) if r['name']==edit['region']]
        if len(matches)!=1:return False
        index,region=matches[0]
        if edit['control']:
            targets=[c for c in candidate.get('controls',[]) if c['region_index']==index and c.get('name',c.get('text'))==edit['control']]
        else:
            if edit['field']=='list_group':return False
            targets=[region]
        if len(targets)!=1 or targets[0].get(edit['field'],'')!=edit['before']:return False
        if edit['field']!='list_group' and not edit['after'].strip():return False
        targets[0][edit['field']]=edit['after']
    folder=Path(run)/'calls'/job['call']
    helper('register_update').write_json(folder/'effective_candidate.json',candidate)
    helper('register_update').write_json(folder/'effective_request.json',job['request'])
    job.update(candidate=candidate,status='accept',record_edit=None)
    job['history'].append({'call':job['call'],'framework':'修订对象尚未入库，将字段修订应用到待接受提案；原回复保留'})
    return True
