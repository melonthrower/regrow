"""Persistent, bounded repair at stage acceptance boundaries. No GUI dispatch."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import uuid
import subprocess
import jsonschema
import importlib.util


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def read(path):return json.loads(Path(path).read_text())

def diagnostic(error):
    if hasattr(error,'report'):return error.report
    if isinstance(error,jsonschema.ValidationError):return '/'.join(map(str,error.absolute_path))+': '+error.message
    return str(error)


def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,path)


class Paused(Exception):
    def __init__(self,status,reason):self.status=status;self.reason=reason;super().__init__(reason)


def submission(run,ref):
    """Resolve a corrected candidate without modifying the actual model artifacts."""
    folder=Path(run)/'calls'/ref;q=read(folder/'request.json');reply=read(folder/'response.json')
    if q.get('role')=='step_correction':
        jsonschema.validate(reply,q['response_schema'])
        normalized=folder/'effective_candidate.json'
        if reply['resolution']=='edit_record' and normalized.exists():
            return read(folder/'effective_request.json'),read(normalized)
        if reply['resolution']!='revise' or reply['proposal'] is None:raise ValueError('not a revised candidate')
        effective=folder/'effective_request.json'
        return (read(effective) if effective.exists() else deepcopy(q['original_request'])),deepcopy(reply['proposal'])
    return q,reply


def pending(run,pointer_name='pending_step.json'):
    pointer=Path(run)/pointer_name
    if not pointer.exists():return None
    job=read(Path(run)/read(pointer)['episode'])
    return job


def confirmed_dispatch_review(run,job,current_calls,window,current_frame):
    """One fresh correction for this specific, still undispatched frame change."""
    evidence=job.get('pre_dispatch_review')
    if not evidence or job.get('stage')!='action' or job.get('status')!='complete':return False
    if evidence.get('current')!=str(current_frame):return False
    if job.get('repairs')!=1 or job.get('observations',0) or job.get('record_edit'):return False
    ref=job.get('call')
    if ref not in current_calls or not window or window!=evidence.get('window'):return False
    if (Path(run)/'execution_pending.json').exists():return False
    folder=Path(run)/'calls'/str(ref)
    if not (folder/'request.json').exists() or not (folder/'response.json').exists():return False
    sent=read(folder/'request.json');reply=read(folder/'response.json')
    if sent.get('role')!='step_correction' or reply.get('resolution')!='revise' or reply.get('blocked_by')!='none':return False
    frames=sent.get('screenshots',[])
    current=evidence['current']
    return (evidence['before'] in frames and current in frames
            and job['request'].get('screenshots')==[current]
            and sent.get('original_request',{}).get('screenshots')==[current]
            and reply.get('proposal')==job.get('candidate'))


def reopen_blocked(run,frame):
    """A new run may reobserve an unexecuted blocked proposal, keeping its audit."""
    job=pending(run)
    if not job or job['status']!='blocked' or job.get('attempt'):return False
    if job['stage'] not in ('action','discovery','task_proposal','function_registration','task_result_review'):return False
    if any((Path(run)/p).exists() for p in ('execution_pending.json','visual_navigation_pending.json')):return False
    helper('discovery_step').await_discovery(run,str(Path(frame).resolve()),'blocked-'+Path(job['path']).parent.name)
    job.update(status='superseded_by_observation',resume_frame=str(Path(frame).resolve()))
    atomic(Path(run)/job['path'],job)
    (Path(run)/'pending_step.json').unlink()
    return True


def request(root,job,context):
    if job['stage']=='shared_control_review':
        return helper('shared_control_review').correction_request(root,job)
    original=deepcopy(job['request'])
    if job['stage']=='action' and not original.get('needs_task_inspection'):original=helper('visual_choices').prepare(original)
    edit={'type':'object','properties':{n:{'type':'string'} for n in ('region','control','field','before','after','evidence')},
          'required':['region','control','field','before','after','evidence'],'additionalProperties':False}
    task_edit={'type':'object','properties':{n:{'type':'string'} for n in ('region','task','field','before','after','evidence')},'required':['region','task','field','before','after','evidence'],'additionalProperties':False}
    task_edit['properties']['field']={'type':'string','enum':['task_control','suspend_task']}
    edit={'anyOf':[edit,task_edit,helper('action_owner_correction').schema(),helper('control_observation_repair').schema()]}
    fields={'blocked_by':{'type':'string','enum':['none','blocking_popup','system_error','unexpected_exit','external_app','control_not_visible','binding_conflict','region_ownership_review','shared_control_conflict','model_response_parse_error','review_required']},'reason':{'type':'string'},'resolution':{'type':'string','enum':['revise','observe','edit_record','defer','blocked']},
            'proposal':{'anyOf':[deepcopy(original['response_schema']),{'type':'null'}]},
            'record_edit':{'anyOf':[edit,{'type':'array','items':edit},{'type':'null'}]}}
    if job['stage']=='update':
        # Older saved update contracts omitted these existing boolean fields from required.
        proposal=fields['proposal']['anyOf'][0]['properties']
        for obj,key in [(proposal.get('regions',{}).get('items',{}),'controls_complete'),
                        (proposal.get('action_result',{}),'returns_to_previous')]:
            if obj.get('properties',{}).get(key,{}).get('type')=='boolean':
                obj['required']=list(dict.fromkeys(obj.get('required',[])+[key]))
    if job['stage']=='task_proposal':fields['proposal']['anyOf'][0]['properties']['operations']['items']['properties']['control'].pop('enum',None)
    schema={'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
    dynamic={'失败步骤':job['stage'],'原任务要求':original['system_prompt'],'原动态上下文':original['user_prompt'],
             '相关记录与可用能力':context,'被拒绝回复':job.get('candidate'),'上次失败或停止诊断（保留原文，非当前能力清单）':job.get('error'),'框架错误分类':job.get('blocked_by','none'),
             '执行状态':'动作已执行，只能修复登记，禁止重做动作' if job.get('attempt') else '本步骤未执行动作',
             '本次修复历史':job['history'],'补充观察':job.get('supplements',[]),
             '图片说明':'前面的图片仍为原请求证据；追加图片仅用于稍后的补充观察，不能代替原动作后图。'}
    dynamic.update(helper('correction_prompts').parse_disclosure(job))
    if context.get('失败对象') and context.get('失败对象',{}).get('控件')==context.get('任务目标',{}).get('控件') and original.get('source',{}).get('region')==original.get('source',{}).get('task_region',original.get('source',{}).get('region')):
        dynamic['原动态上下文']='继续下方失败对象对应的原任务；遵守所列任务目的、动作类型和本轮约束。无关任务历史已省略。'
    if original.get('needs_task_inspection'):
        dynamic['当前前置缺口']='原任务控件缺少已登记的当前定位，点击坐标或改写名称不能补齐登记。请选择observe定向观察原任务控件，或defer保留缺口；补定位成功后回正常动作选择。'
        dynamic['原任务']=original.get('source',{}).get('task_name')
    if original.get('visual_choices'):
        dynamic['待消歧控件']=helper('visual_choices').describe(original)

    principle=Path(root)/'遍历prompt/通用/探索验证原则.prompt'
    parts=helper('correction_prompts').parts(root,job,context)
    parts.append({'path':'通用/探索验证原则.prompt','text':principle.read_text()})
    if job['stage']=='action':
        target_prompt=Path(root)/'遍历prompt/动作/目标观察阅读.prompt'
        parts.append({'path':'动作/目标观察阅读.prompt','text':target_prompt.read_text()})
    dispatch_review=job.get('pre_dispatch_review')
    if dispatch_review:
        path='纠错/投递前画面变化.prompt'
        parts.append({'path':path,'text':(Path(root)/'遍历prompt'/path).read_text()})
    if original.get('visual_choices'):
        choice_prompt=Path(root)/'遍历prompt/纠错/控件候选消歧.prompt'
        parts.append({'path':'纠错/控件候选消歧.prompt','text':choice_prompt.read_text()})
    text=json.dumps(dynamic,ensure_ascii=False,indent=2)
    frames=list(original.get('screenshots',[]))+[s['image'] for s in job.get('supplements',[])]
    image_roles=[{'图片':i+1,'用途':'原请求或补充观察'} for i in range(len(frames))]
    if dispatch_review:
        frames.insert(0,dispatch_review['before'])
        image_roles=[{'图片':i+1,'用途':'旧选择依据，动作尚未执行' if i==0 else '最新投递前画面' if frame==dispatch_review['current'] else '补充观察'} for i,frame in enumerate(frames)]
    for item in context.get('最近尝试原始证据',[]):
        for key in ('动作前图','动作后图'):
            if item.get(key) and item[key] not in frames:
                frames.append(item[key]);image_roles.append({'图片':len(frames),'用途':'历史尝试 '+item['尝试']+' '+key+'，不是当前状态'})
    dynamic['图片顺序']=image_roles
    dynamic['图片说明']='依图片顺序逐张核对用途；历史尝试前后图仅解释过去的投递与效果，不代表当前状态。补充观察也不能替代原动作后图。'
    text=json.dumps(dynamic,ensure_ascii=False,indent=2)
    return {**original,'role':'step_correction','stage':'step_correction','original_request':deepcopy(original),
            'system_prompt':'\n\n'.join(p['text'] for p in parts),'user_prompt':text,'dynamic_prompt':text,
            'screenshots':frames,'image_refs':frames,'response_schema':schema,
            'fixed_parts':parts}


class Runner:
    def __init__(self,root,run,call,screenshot,available,pointer_name='pending_step.json',review_update=None):
        self.root=Path(root);self.run=Path(run);self.call=call;self.screenshot=screenshot;self.available=available
        self.adapters=helper('repair_stages')
        self.pointer_name=pointer_name
        self.review_update=review_update

    def save(self,job):atomic(self.run/job['path'],job)

    def sent_request(self,job,q,ref,repairing):
        path=self.run/'calls'/str(ref)/'request.json'
        if path.exists():
            q=read(path)
            if not repairing:job['request']=deepcopy(q)
        return q

    def repair_parse_failure(self,job):
        manifest=self.run/'run_manifest.json'
        failed=read(manifest).get('last_call') if manifest.exists() else None
        path=self.run/'calls'/str(failed)/'parse_error.json'
        if not path.exists():return False
        detail=read(path)
        job.update(status='repair',candidate=None,blocked_by='model_response_parse_error',
                   parse_failure={'call':failed,**detail},error='模型回复解析错误：'+detail['reason'])
        job['history'].append({'call':failed,'error':job['error']})
        self.save(job)
        return True

    def stop(self,job,reason):
        if not isinstance(reason,str):reason=json.dumps(reason,ensure_ascii=False)
        decision=self.adapters.helper('task_deferral').defer(self.run,job,reason)
        if decision is not None:
            job.update(status='deferred',deferral=decision,error=reason);self.save(job)
            (self.run/self.pointer_name).unlink(missing_ok=True)
            raise Paused('task_deferred' if decision['next'] else 'task_blocked',reason)
        job.update(status='blocked',error=reason);self.save(job);raise Paused('correction_blocked',reason)

    def repair_unlocated(self,q,reason):
        if pending(self.run,self.pointer_name):raise Paused('correction_blocked','先处理已有待修复步骤')
        key=uuid.uuid4().hex
        job={'path':f'repair_episodes/{key}/episode.json','stage':'action','request':deepcopy(q),'attempt':None,
             'status':'repair','repairs':0,'observations':0,'history':[{'framework':reason}],
             'seen':[],'supplements':[],'error':reason}
        self.save(job);atomic(self.run/self.pointer_name,{'episode':job['path']})
        return self.perform('action')

    def reject_action(self,q,candidate,ref,reason,pre_dispatch_review=None):
        if pending(self.run,self.pointer_name):raise Paused('correction_blocked','已有步骤待修复')
        key=uuid.uuid4().hex
        job={'path':f'repair_episodes/{key}/episode.json','stage':'action','request':deepcopy(q),'attempt':None,
             'status':'repair','repairs':0,'observations':0,'history':[{'call':ref,'error':reason}],
             'seen':[],'supplements':[],'candidate':candidate,'call':ref,'error':reason,'requires_observation':True}
        if pre_dispatch_review:job['pre_dispatch_review']=deepcopy(pre_dispatch_review)
        self.save(job);atomic(self.run/self.pointer_name,{'episode':job['path']})
        raise Paused('repair_pending',reason)

    def switch_branch(self,job):
        if self.available()<1:
            raise Paused('repair_pending','本轮调用额度已用完；下一轮继续原纠错请求')
        decision=helper('branch_switch').correct(self,job)
        if decision:
            raise Paused('ready_next_round' if decision.get('resumed') else 'task_deferred',
                '纠错已解决本次循环判断；重新发现后按新办法继续' if decision.get('resumed') else '纠错已暂挂当前分支；重新发现后继续独立区块')
        raise Paused('correction_blocked','当前分支未切换；保留未完成记录')

    def perform(self,stage,q=None,attempt=None):
        job=pending(self.run,self.pointer_name)
        if job is None:
            if stage in ('action','task_proposal','function_registration','task_result_review'):
                helper('shared_control_review').run_pending(self)
            key=uuid.uuid4().hex
            job={'path':f'repair_episodes/{key}/episode.json','stage':stage,'request':deepcopy(q),'attempt':attempt,
                 'status':'initial','repairs':0,'observations':0,'history':[],'seen':[],'supplements':[]}
            if stage=='shared_control_review':
                job.update(status='repair',blocked_by='shared_control_conflict',error='共享关系有实际结果冲突，请核对共享范围')
            self.save(job);atomic(self.run/self.pointer_name,{'episode':job['path']})
        elif stage!=job['stage']:raise Paused('correction_blocked','必须先处理尚未完成的步骤：'+job['stage'])
        if stage=='update' and self.review_update is not None and not job.get('requires_update_review'):
            job['requires_update_review']=True;self.save(job)
        if job['stage']=='function_registration' and job.get('status') in ('repair','blocked') and not job.get('attempt') and not (self.run/'execution_pending.json').exists() and not job.get('service_failure'):
            rid=job['request'].get('source',{}).get('region')
            if helper('region_functions').request_support_review(self.run,rid,job.get('call')):
                job.update(status='superseded_by_support_review');self.save(job)
                (self.run/self.pointer_name).unlink(missing_ok=True)
                raise Paused('ready_next_round','功能缺少任务依据，返回任务提出步骤补充仅观察记录；未新增GUI动作')
        if job.get('service_failure') and job['stage']=='function_registration':
            self.stop(job,'模型服务失败，仅暂挂本区块的功能整理；其他探索可继续，原请求与错误保留')
        if job.get('service_failure') or job.get('switch_trigger'):
            self.switch_branch(job)
        if job['status']=='blocked':
            last=read(self.run/'calls'/job['call']/'response.json') if job.get('call') else {}
            if last.get('resolution')=='edit_record' and self.adapters.edit_proposal(self.run,job,last.get('record_edit')):
                self.save(job)
            else:self.stop(job,job['error'])
        if job['status']=='deferred':
            (self.run/self.pointer_name).unlink(missing_ok=True)
            raise Paused('task_deferred' if job['deferral']['next'] else 'task_blocked',job['error'])
        while True:
            if job['status']=='complete':
                (self.run/self.pointer_name).unlink(missing_ok=True)
                return job
            if job['status']=='observe':
                if self.available()<1:raise Paused('repair_pending','等待下一轮额度补观察')
                try:
                    self.adapters.observe(self,job)
                    if job['stage']=='action' and job['request'].get('action_ready'):
                        job['status']='initial';self.save(job);continue
                except subprocess.CalledProcessError:
                    if not self.repair_parse_failure(job):raise
                except (ValueError,jsonschema.ValidationError) as error:
                    job['error']=diagnostic(error);job['history'].append({'observation_error':diagnostic(error)})
                job['status']='repair';self.save(job);continue
            if job['status']=='accept':
                if job['stage']=='update' and (self.review_update or job.get('requires_update_review')):
                    job['requires_update_review']=True;self.save(job)
                    review=helper('update_semantic_review')
                    try:
                        review.check(self.run,job,self.review_update)
                    except review.Pending as error:
                        raise Paused('review_pending',str(error))
                    except review.Rejected as error:
                        job.update(error=str(error),blocked_by=error.blocked_by,status='repair')
                        job['history'].append({'call':job['call'],'error':str(error),'source':'supervisor_review'})
                        self.save(job);continue
                try:
                    result=self.adapters.accept(self.root,self.run,job)
                except (ValueError,jsonschema.ValidationError) as error:
                    if job['stage']=='action' and getattr(error,'refresh_request',False):
                        try:
                            refreshed=self.adapters.refresh(self.root,self.run,job)
                        except (ValueError,jsonschema.ValidationError) as refresh_error:
                            error=refresh_error
                        else:
                            job['history'].append({'call':job['call'],'error':diagnostic(error),'resolution':'refresh_original_task'})
                            job.update(request=refreshed,status='initial',candidate=None,record_edit=None)
                            self.save(job);continue
                    if job['stage']=='function_registration' and not job.get('attempt') and helper('region_functions').request_support_review(self.run,job['request'].get('source',{}).get('region'),job.get('call')):
                        job.update(status='superseded_by_support_review',error=diagnostic(error));self.save(job)
                        (self.run/self.pointer_name).unlink(missing_ok=True)
                        raise Paused('ready_next_round','功能缺少任务依据，返回任务提出步骤补充仅观察记录')
                    if helper('ownership_review').begin(self.run,job,diagnostic(error)):
                        raise Paused('repair_pending','区块归属需实地复查；原记录与提案已保存')
                    if getattr(error,'defer_task',False):self.stop(job,str(error))
                    if getattr(error,'blocked_by',None):job['blocked_by']=error.blocked_by
                    job['error']=diagnostic(error);job['status']='repair'
                    job['history'].append({'call':job['call'],'error':diagnostic(error)})
                    self.save(job);continue
                job.update(status='complete',result=result);self.save(job);continue
            if self.available()<1:raise Paused('repair_pending','等待下一轮额度继续原步骤')
            repairing=job['status']=='repair'
            if job.get('service_retry_request'):
                q=job.pop('service_retry_request');self.save(job)
            elif repairing:
                if job['repairs']>=2:self.stop(job,'纠错次数已用完；保留原任务和未解决记录')
                q=request(self.root,job,self.adapters.context(self.run,job))
                job['repairs']+=1;self.save(job)
            else:q=job['request']
            try:
                ref,reply=self.call(q)
            except subprocess.CalledProcessError:
                manifest=Path(self.run)/'run_manifest.json'
                failed=read(manifest).get('last_call') if manifest.exists() else None
                folder=Path(self.run)/'calls'/str(failed)
                q=self.sent_request(job,q,failed,repairing)
                if self.repair_parse_failure(job):continue
                evidence=folder/'http_error.json'
                if not evidence.exists():raise
                failure=read(evidence)
                job.setdefault('service_error_history',[]).append({'call':failed,'error':failure})
                if failure.get('status') in (429,500,502,503,504) and not job.get('service_retry_used'):
                    job['service_retry_used']=True;job['service_retry_request']=deepcopy(q);self.save(job)
                    continue  # Retry only the same model request, never a GUI dispatch.
                job['service_failure']={'call':failed,'error':failure};self.save(job)
                if job['stage']=='function_registration':self.stop(job,'模型服务失败，仅暂挂功能整理，其他探索继续')
                self.switch_branch(job)
            q=self.sent_request(job,q,ref,repairing)
            job['call']=ref;job['history'].append({'call':ref,'role':q.get('role')})
            try:
                if repairing:
                    repeated=reply.get('proposal') if isinstance(reply,dict) else None
                    if repeated is not None:
                        check=hashlib.sha256(json.dumps([repeated,job['request'],job.get('supplements'),reply.get('record_edit')],sort_keys=True).encode()).hexdigest()
                        if check in job['seen']:self.stop(job,'重复提交同一证据下已拒绝的提案')
                    if job['stage']=='shared_control_review':job['last_shared_reply']=deepcopy(reply)
                    helper('registration_diagnostics').check('correction',{'response_schema':q['response_schema']},reply,{})
                    resolution=reply['resolution']
                    job['blocked_by']=reply['blocked_by']
                    if not reply['reason'].strip():raise ValueError('需要说明修复依据')
                    if resolution!='revise' and reply['proposal'] is not None:
                        raise ValueError(f'resolution={resolution}要求proposal=null；保留你的修复方式，将proposal改为null，观察对象或原因写在reason。动作none也属于提案，不能代替null。')
                    if resolution=='revise' and reply['proposal'] is None:
                        raise ValueError('resolution=revise需要完整proposal；若需要补观察应选择observe并保持proposal=null。')
                    if resolution=='edit_record' and reply['record_edit'] is None:
                        raise ValueError('resolution=edit_record需要record_edit说明具体修订。')
                    if resolution not in ('revise','edit_record') and reply['record_edit'] is not None:
                        raise ValueError(f'resolution={resolution}要求record_edit=null；保留修复方式，不混入记录修订。')
                    if resolution in ('blocked','defer'):
                        job['blocked_by']=reply['blocked_by']
                        self.stop(job,reply['reason'])
                    if resolution=='observe':
                        if job['observations']>=1:self.stop(job,'本次纠错已补观察，仍缺少依据')
                        job.update(status='observe',observation_question=reply['reason']);self.save(job);continue
                    if resolution=='edit_record':
                        if self.adapters.edit_proposal(self.run,job,reply['record_edit']):
                            self.save(job);continue
                        self.adapters.edit_record(self.root,self.run,job,reply['record_edit'])
                        if job['stage']=='shared_control_review':
                            job.update(status='complete',result={'record_edit':reply['record_edit'],'resolution':'shared_relation_reviewed'})
                            self.save(job);continue
                        job['request']=self.adapters.refresh(self.root,self.run,job)
                        job['error']='记录修订已保存；请依据新记录修正原步骤提案'
                        job['status']='repair';self.save(job);continue
                    job['record_edit']=reply['record_edit']
                    candidate=reply['proposal']
                else:candidate=reply
                fingerprint=hashlib.sha256(json.dumps([candidate,job['request'],job.get('supplements'),job.get('record_edit')],sort_keys=True).encode()).hexdigest()
                if fingerprint in job['seen']:self.stop(job,'重复提交同一证据下已拒绝的提案')
                job['seen'].append(fingerprint);job.update(candidate=candidate,status='accept');self.save(job)
            except (ValueError,jsonschema.ValidationError) as error:
                job.update(error=diagnostic(error),status='repair');self.save(job)
