"""Explicit, previously observed navigation routes with bounded Luna fallback."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .records import EvidenceStore,valid_box
from .protocol import obj,T,BOX,POINT
from .reidentify import rgb,pixel_box,normalized,same_view,locate_control

FALLBACK_SCHEMA=obj(dict(surface=T,surface_kind={'type':'string','enum':['page','dialog','popup','unknown']},surface_box=BOX,
    control_box=BOX,context_box=BOX,point=POINT,state={'type':'string','enum':['enabled','disabled','selected','unselected','unknown']},
    target_found={'type':'boolean'},destination_matches={'type':'boolean'},reason=T))
FALLBACK_PROMPT='''你是已登记GUI导航的纠正者，只输出一份最终JSON，不输出commentary。
图片按顺序为登记参考、当前截图；当前图最后。mode=ground时，仅定位指定控件；先独立确认当前接管输入的surface_kind及surface_box，背景控件不算找到。禁止猜测不可见目标、关闭弹层或执行其他动作。target_found不确定时false。
mode=confirm时只核对当前图是否确实到达参考的已知导航落点；外观像但功能/弹层不同写destination_matches=false，不因程序期待而确认。此时target_found=false。
坐标统一0..1000；control_box必须是当前控件真实框，point在内部，state反映当前状态。context_box为包含control_box及可读标签的最小语义范围，不登记无意义的裸复选框。没有控件时control_box=[0,0,0,0],context_box=[0,0,0,0],point=[0,0],state=unknown。不能把禁用、遮挡或未知控件当可点击。
'''


class KnownRoute:
    def __init__(self,frames,steps):self.frames=frames;self.steps=steps

    @classmethod
    def from_records(cls,records,attempt_refs):
        if not attempt_refs or len(set(attempt_refs))!=len(attempt_refs):raise ValueError('explicit distinct route attempts required')
        frames={f['ref']:deepcopy(f) for f in records['frames']};attempts={a['ref']:a for a in records['attempts']};steps=[]
        for ref in attempt_refs:
            if ref not in attempts:raise ValueError('unknown route attempt')
            a=deepcopy(attempts[ref])
            if a.get('status')!='observed' or a.get('intent')!='met' or a.get('outcome')!='changed' or a['action']['kind'] not in {'click','back'}:
                raise ValueError('route requires observed successful click/back navigation')
            if a['before'] not in frames or a.get('after') not in frames:raise ValueError('missing route frame')
            if steps and steps[-1]['after']!=a['before']:
                previous=frames[steps[-1]['after']];following=frames[a['before']]
                if previous.get('surface_kind')!=following.get('surface_kind') or not same_view(Path(previous['image']).read_bytes(),Path(following['image']).read_bytes(),previous['surface_box']):
                    raise ValueError('disconnected route')
            for f in [frames[a['before']],frames[a['after']]]:
                if f.get('surface_kind','unknown')=='unknown' or not valid_box(f['surface_box']):raise ValueError('route requires known input layers')
                data=Path(f['image']).read_bytes()
                if f.get('image_sha256') and hashlib.sha256(data).hexdigest()!=f['image_sha256']:raise ValueError('reference image changed')
            if a['action']['kind']=='click' and not any(c['ref']==a['action'].get('owner') for c in frames[a['before']]['controls']):raise ValueError('missing registered owner')
            steps.append(a)
        return cls(frames,steps)

    def save(self,root):
        root=Path(root);root.mkdir(parents=True,exist_ok=True);copied={}
        for ref in {s[k] for s in self.steps for k in ['before','after']}:
            f=deepcopy(self.frames[ref]);dest=root/f'{ref}.png';dest.write_bytes(Path(f['image']).read_bytes());f['image']=str(dest);copied[ref]=f
        (root/'catalog.json').write_text(json.dumps(dict(schema='evidence_known_route.v1',frames=copied,steps=self.steps,
            identity_scope='source observation refs; no name-based canonical merging'),ensure_ascii=False,indent=2))


class RouteRuntime:
    def __init__(self,*,driver,agent,route,output,max_calls=16,max_actions=12,before_action=None,record_regions=False):
        self.driver=driver;self.agent=agent;self.route=route;self.store=EvidenceStore(output)
        self.calls=0;self.actions=0;self.max_calls=max_calls;self.max_actions=max_actions;self.before_action=before_action
        self.record_regions=record_regions
        self.corrections=[];self.route.save(self.store.root/'memory')

    def _regions(self,reference,current,observation,step,phase):
        if not self.record_regions:return
        from .region_revisit import region_candidates
        try:result=region_candidates(reference,current)
        except Exception as exc:result=dict(error=type(exc).__name__,regions=[],identity_verified=False,boundary_verified=False)
        self.store.write(f'region_revisit/{observation["ref"]}.json',dict(result,
            current_frame=observation['ref'],source_attempt=step['ref'],phase=phase))

    def _fallback(self,mode,reference,current,step,control=None):
        if self.calls>=self.max_calls:return None
        self.calls+=1;folder=self.store.root/'calls'/f'{self.calls:04d}';folder.mkdir(parents=True,exist_ok=True)
        context=dict(mode=mode,reason=step['action']['reason'],registered_surface=reference['surface'],
            target=None if control is None else {k:control[k] for k in ['ref','label','function','box']},
            instruction='定位或核对本步，不规划其他动作；当前截图是最后一张。')
        images=[Path(reference['image']).read_bytes(),current]
        for i,data in enumerate(images):(folder/f'input_{i}.png').write_bytes(data)
        self.store.write(f'calls/{self.calls:04d}/request.json',dict(system=FALLBACK_PROMPT,input=context,schema=FALLBACK_SCHEMA))
        raw=self.agent._call(role='evidence_route_'+mode,system_prompt=FALLBACK_PROMPT,user_prompt=json.dumps(context,ensure_ascii=False),screenshots=images,response_schema=FALLBACK_SCHEMA)
        self.store.write(f'calls/{self.calls:04d}/response.json',raw)
        return raw

    def _raw(self,reference,*,control=None,action=None,receipt=None,foreground=None):
        f=foreground or reference
        return dict(surface=f['surface'],surface_kind=f.get('surface_kind','unknown'),surface_box=f['surface_box'],
            controls=[] if control is None else [control],regions=[],claims=[],links=[],uncertain=[],receipt=receipt,
            action=action or dict(kind='observe',point=[0,0],direction='',reason='Verify known route destination'))

    def run(self):
        status='route_complete';error='';completed=0;confirmed_view=None
        try:
            for step in self.route.steps:
                if (self.store.root/'STOP').exists():status='supervised_stop';break
                if self.actions>=self.max_actions:status='action_limit';break
                if not self.driver.scope_ok():status='foreground_lost';break
                current=self.driver.observe();source=self.route.frames[step['before']];destination=self.route.frames[step['after']]
                reference=Path(source['image']).read_bytes();source_known=same_view(reference,current,source['surface_box'])
                alias=(not source_known and confirmed_view is not None and confirmed_view['destination']==step['before']
                    and same_view(confirmed_view['image'],current,confirmed_view['foreground']['surface_box']))
                action=deepcopy(step['action']);action.pop('owner',None);action.pop('frame',None);control=None;foreground=confirmed_view['foreground'] if alias else source;correction=None
                if action['kind']=='click':
                    registered=next(c for c in source['controls'] if c['ref']==step['action']['owner']);control=deepcopy(registered);control.pop('ref',None)
                    match=locate_control(reference,current,pixel_box(registered['box'],rgb(reference).shape),pixel_box(foreground['surface_box'],rgb(current).shape),context_box=(pixel_box(registered['context_box'],rgb(reference).shape) if 'context_box' in registered else None)) if source_known or alias else dict(accepted=False,reason='input_layer_requires_confirmation')
                    self.store.write(f'route/step_{completed+1}_match.json',match)
                    if alias and match['accepted']:
                        from .reidentify import crop
                        import cv2
                        registered_pixels=crop(rgb(reference),pixel_box(registered['box'],rgb(reference).shape))
                        current_pixels=crop(rgb(current),match['box'])
                        current_pixels=cv2.resize(current_pixels,(registered_pixels.shape[1],registered_pixels.shape[0]))
                        if not same_view(registered_pixels,current_pixels):match=dict(accepted=False,reason='control_state_requires_confirmation')
                    if match['accepted']:
                        control['box']=normalized(match['box'],rgb(current).shape)
                        if 'context_box' in registered:control['context_box']=normalized(match['context_box'],rgb(current).shape)
                        b=control['box'];action['point']=[(b[0]+b[2])//2,(b[1]+b[3])//2]
                    else:
                        fallback=self._fallback('ground',source,current,step,registered)
                        if fallback is None:status='call_limit';break
                        if fallback.get('target_found') is not True:status='target_unresolved';break
                        foreground=fallback;control['box']=fallback['control_box'];control['state']=fallback['state'];action['point']=fallback['point'];correction=fallback
                        if 'context_box' in fallback:control['context_box']=fallback['context_box']
                        else:control.pop('context_box',None)
                elif not source_known:
                    # Back is only deterministic in an already confirmed source surface.
                    status='source_unconfirmed';break
                raw=self._raw(source,control=control,action=action,foreground=foreground)
                obs,allowed=self.store.accept(raw,current)
                self._regions(source,current,obs,step,'source')
                if allowed is None:status='grounding_rejected';break
                planned=self.store.plan(allowed)
                if self.before_action and not self.before_action(planned,obs):status='supervised_stop';break
                if (self.store.root/'STOP').exists():status='supervised_stop';break
                if not self.driver.scope_ok():status='foreground_lost_before_dispatch';break
                fresh=self.driver.observe()
                # No cached point survives an input-layer change during approval or latency.
                if not same_view(current,fresh,foreground['surface_box']):status='changed_before_dispatch';break
                try:
                    result=self.driver.execute(allowed)
                    if result and result.get('action_error'):raise RuntimeError('controller delivery error')
                except Exception as exc:
                    self.store.delivery_failed(planned['ref'],type(exc).__name__);status='delivery_unknown';break
                self.actions+=1;self.store.delivered(planned['ref'])
                if not self.driver.scope_ok():status='foreground_lost_after_dispatch';break
                after=self.driver.observe();dest_image=Path(destination['image']).read_bytes()
                visual=same_view(dest_image,after,destination['surface_box']);confirmed=visual;fg=destination
                if not visual:
                    fallback=self._fallback('confirm',destination,after,step)
                    if fallback is None:status='call_limit';break
                    confirmed=fallback.get('destination_matches') is True and fallback.get('surface_kind','unknown')!='unknown'
                    fg=fallback
                receipt=dict(outcome='changed' if confirmed else 'uncertain',intent='met' if confirmed else 'uncertain',
                    description=('Known navigation destination visually matched' if visual else 'Luna destination confirmation: '+str(confirmed))+'; not a business-goal completion claim')
                landed,_=self.store.accept(self._raw(destination,receipt=receipt,foreground=fg),after)
                self._regions(destination,after,landed,step,'destination')
                self.store.write(f'route/step_{completed+1}_verification.json',dict(source_attempt=step['ref'],visual=visual,confirmed=confirmed))
                if not confirmed:status='destination_unconfirmed';break
                if correction:
                    self.corrections.append(dict(source_control=registered['ref'],frame=obs['ref'],box=control['box'],
                        state=control['state'],context_box=control.get('context_box'),confirmed_destination=step['after'],basis='Luna grounding plus observed destination; candidate appearance'))
                    self.store.write('memory/corrections.json',self.corrections)
                confirmed_view=dict(destination=step['after'],image=after,foreground=deepcopy(fg))
                self.store.write(f'memory/confirmed_{completed+1}.json',dict(destination_ref=step['after'],frame=landed['ref'],foreground={k:fg[k] for k in ['surface','surface_kind','surface_box']},basis='visual' if visual else 'Luna'))
                completed+=1
        except Exception as exc:status='error';error=type(exc).__name__
        finally:
            self.store.flush();result=dict(status=status,error=error,model_calls=self.calls,delivered_actions=self.actions,
                completed_steps=completed,total_steps=len(self.route.steps),pending=None if self.store.pending is None else self.store.pending['ref'],
                scope='explicit known navigation route; not whole-app or arbitrary business completion')
            self.store.write('status.json',result)
        return result
