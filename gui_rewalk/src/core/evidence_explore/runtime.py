"""One model call per frame; optional knowledge is never an action prerequisite."""
from copy import deepcopy
import json
import time
import io
from PIL import Image
from pathlib import Path
from .protocol import PROMPT,SCHEMA
from .records import EvidenceStore,valid_box


class EvidenceRuntime:
    def __init__(self,*,driver,agent,output,goal,max_calls=16,max_actions=12,before_action=None,separate_receipts=False,verify_before_dispatch=False,review_inventory=False):
        self.driver=driver;self.agent=agent;self.store=EvidenceStore(output);self.goal=goal
        self.max_calls=max_calls;self.max_actions=max_actions;self.before_action=before_action
        self.verify_before_dispatch=verify_before_dispatch or review_inventory
        self.separate_receipts=separate_receipts or review_inventory
        self.review_inventory=review_inventory;self.quality_feedback=None;self.quality_cache=[];self.registration_details=None
        self.calls=0;self.actions=0;self.registration_error=''

    def _receipt_only(self,raw,frame,folder):
        if not self.separate_receipts or self.store.pending is None:return None
        receipt=raw.get('receipt')
        if not isinstance(receipt,dict) or set(receipt)!={'outcome','intent','description'}:return None
        if receipt['outcome'] not in {'changed','unchanged','uncertain'} or receipt['intent'] not in {'met','not_met','uncertain'} or not isinstance(receipt['description'],str):return None
        if raw.get('surface_kind') not in {'page','dialog','popup','unknown'} or not valid_box(raw['surface_box']):return None
        derived={k:raw[k] for k in ['surface','surface_kind','surface_box','receipt']}
        kind='stop' if raw['action']['kind']=='stop' else 'observe'
        derived.update(controls=[],regions=[],claims=[],links=[],uncertain=['Inventory quarantined: '+self.registration_error],
            action=dict(kind=kind,point=[0,0],direction='',reason='Receipt-only recovery; invalid inventory grants no action'))
        obs,_=self.store.accept(derived,frame)
        self.store.write(f'frames/{obs["ref"]}/derivation.json',dict(source_reply=str(folder.relative_to(self.store.root)/'response.json'),
            receipt_modified=False,inventory_admitted=False,new_model_calls=0,reason=self.registration_error))
        return obs

    def _review(self,raw,frame,images,pending_before,obs):
        if not self.review_inventory:return 'ok'
        from .quality import REVIEW_SCHEMA,REVIEW_PROMPT,valid_review
        from .reidentify import same_view
        scrolling=bool(pending_before and pending_before['action']['kind']=='scroll')
        if not scrolling and not self.quality_feedback and any(same_view(old,frame,box) for old,box in self.quality_cache):return 'ok'
        if self.calls>=self.max_calls:return 'budget'
        previous=None
        if pending_before:
            previous=self.store.frames[int(pending_before['before'][1:])-1]
        context=dict(goal=self.goal,surface=raw['surface'],surface_kind=raw['surface_kind'],surface_box=raw['surface_box'],
            controls=raw['controls'],regions=raw['regions'],pending_action=pending_before['action'] if pending_before else None,
            previous_controls=previous['controls'] if scrolling and previous else [])
        prompt=json.dumps(context,ensure_ascii=False)
        if len(prompt.encode())>24000:return 'context'
        self.calls+=1;folder=self.store.root/'calls'/f'{self.calls:04d}';folder.mkdir(parents=True)
        review_images=images if scrolling else [frame]
        for i,data in enumerate(review_images):(folder/f'input_{i}.png').write_bytes(data)
        self.store.write(f'calls/{self.calls:04d}/request.json',dict(system=REVIEW_PROMPT,input=context,schema=REVIEW_SCHEMA))
        reviewed=self.agent._call(role='evidence_quality',system_prompt=REVIEW_PROMPT,user_prompt=prompt,screenshots=review_images,response_schema=REVIEW_SCHEMA)
        self.store.write(f'calls/{self.calls:04d}/response.json',reviewed)
        if not valid_review(reviewed):return 'invalid'
        self.store.write(f'quality/{obs["ref"]}.json',dict(review=reviewed,model_call=self.calls,scope='model audit, not ground truth or canonical identity'))
        if scrolling and reviewed['unexpected_changes']:
            obs['note_errors'].append('unexpected scroll changes: '+'; '.join(reviewed['unexpected_changes']))
            self.store.write(f'frames/{obs["ref"]}/observation.json',obs);self.store.flush()
            return 'side_effect'
        failed=reviewed['misidentified'] or (reviewed['inventory_required'] and (not reviewed['visible_complete'] or reviewed['missing']))
        if failed:
            self.quality_feedback=dict(review=reviewed,registered_draft=dict(controls=raw['controls'],regions=raw['regions']),
                instruction='先根据当前截图补齐或纠正登记，再提出下一步；不能原样忽略审核。')
            obs['note_errors'].append('inventory review requires correction')
            self.store.write(f'frames/{obs["ref"]}/observation.json',obs);self.store.flush()
            return 'retry'
        self.quality_feedback=None;self.quality_cache.append((frame,raw['surface_box']))
        self.quality_cache=self.quality_cache[-8:]
        return 'ok'

    def run(self):
        previous_image=Path(self.store.frames[-1]['image']).read_bytes() if self.store.frames else None
        status='call_limit';error='';consecutive_errors=0
        try:
            while self.calls<self.max_calls:
                if (self.store.root/'STOP').exists():status='supervised_stop';break
                if not self.driver.scope_ok():status='foreground_lost';break
                frame=self.driver.observe();context=self.store.context();pending_before=deepcopy(self.store.pending)
                context['goal']=self.goal
                if self.registration_error:context['registration_correction']=self.registration_details or self.registration_error
                if self.quality_feedback:context['quality_feedback']=self.quality_feedback
                context['image_order']='If two images: first is before/comparison, last is CURRENT. If one: it is CURRENT.'
                try:
                    width,height=Image.open(io.BytesIO(frame)).size
                    context['coordinate_system']=dict(image_width=width,image_height=height,instruction='输出0..1000归一化坐标：x=像素x/图宽*1000，y=像素y/图高*1000；不要把像素y直接当归一化y。')
                except Exception:pass
                context['budget']=dict(calls_remaining=self.max_calls-self.calls,actions_remaining=self.max_actions-self.actions,
                    instruction='预留调用确认最后动作；临时改动恢复后安全取消退出。')
                if self.actions>=self.max_actions:context['budget']['instruction']='动作预算已到，只核对pending并记录，不再提出新GUI动作。'
                prompt=json.dumps(context,ensure_ascii=False,separators=(',',':'))
                if len(prompt.encode())>24000:status='context_limit';break
                self.calls+=1;folder=self.store.root/'calls'/f'{self.calls:04d}';folder.mkdir(parents=True)
                before_image=(Path(self.store.frames[int(self.store.pending['before'][1:])-1]['image']).read_bytes()
                    if self.store.pending else previous_image)
                images=([before_image] if before_image is not None else [])+[frame]
                for i,image in enumerate(images):(folder/f'input_{i}.png').write_bytes(image)
                self.store.write(str(folder.relative_to(self.store.root)/'request.json'),dict(system=PROMPT,input=context,schema=SCHEMA))
                print('CALL',self.calls,flush=True)
                raw=self.agent._call(role='evidence_explore',system_prompt=PROMPT,user_prompt=prompt,screenshots=images,response_schema=SCHEMA)
                self.store.write(str(folder.relative_to(self.store.root)/'response.json'),raw)
                try:
                    obs,action=self.store.accept(raw,frame)
                except ValueError as exc:
                    if 'semantic context' not in str(exc):raise
                    from .quality import geometry_feedback
                    self.registration_error=str(exc);self.registration_details=geometry_feedback(raw,self.registration_error)
                    self.store.write(f'calls/{self.calls:04d}/validation_error.json',self.registration_details)
                    recovered=self._receipt_only(raw,frame,folder)
                    if recovered is not None:
                        previous_image=frame
                        if self.review_inventory:
                            derived=json.loads((self.store.root/'frames'/recovered['ref']/'raw.json').read_text())
                            quality=self._review(derived,frame,images,pending_before,recovered)
                            if quality in {'budget','invalid','side_effect','context'}:
                                status={'budget':'review_budget_limit','invalid':'invalid_quality_review','side_effect':'unexpected_scroll_change','context':'review_context_limit'}[quality];break
                            if quality=='retry':
                                if self.calls>=self.max_calls:status='review_budget_limit';break
                                continue
                        if raw['action']['kind']=='stop':status='stopped_by_model';break
                        # A rejected inventory never supplies a new action. The next
                        # observation sees pending=null and the registration error.
                        continue
                    consecutive_errors+=1
                    if consecutive_errors>=2:status='local_correction_limit';break
                    continue
                self.registration_error='';self.registration_details=None
                previous_image=frame
                if action is None:
                    consecutive_errors+=1
                    if consecutive_errors>=2:status='local_correction_limit';break
                    continue
                consecutive_errors=0
                quality=self._review(raw,frame,images,pending_before,obs)
                if quality in {'budget','invalid','side_effect','context'}:
                    status={'budget':'review_budget_limit','invalid':'invalid_quality_review','side_effect':'unexpected_scroll_change','context':'review_context_limit'}[quality];break
                if quality=='retry':
                    if self.calls>=self.max_calls:status='review_budget_limit';break
                    continue
                if action['kind']=='stop':status='stopped_by_model';break
                if self.actions>=self.max_actions:status='action_limit';break
                if action['kind']=='observe':continue
                if self.max_calls-self.calls<(2 if self.review_inventory else 1):status='reserve_receipt_budget';break
                planned=self.store.plan(action)
                if self.before_action and not self.before_action(planned,obs):status='supervised_stop';break
                if not self.driver.scope_ok():status='foreground_lost_before_dispatch';break
                if self.verify_before_dispatch:
                    from .reidentify import same_view
                    if not same_view(frame,self.driver.observe(),obs['surface_box']):status='changed_before_dispatch';break
                try:
                    delivery=self.driver.execute(action)
                    if delivery and delivery.get('action_error'):raise RuntimeError('controller reported delivery error')
                except Exception as exc:
                    self.store.delivery_failed(planned['ref'],type(exc).__name__);status='delivery_unknown';break
                self.actions+=1;self.store.delivered(planned['ref'])
                print('DELIVERED',planned['ref'],action['kind'],flush=True)
        except Exception as exc:
            status='error';error=type(exc).__name__
        finally:
            self.store.flush()
            result=dict(status=status,error=error,model_calls=self.calls,delivered_actions=self.actions,
                pending=None if not self.store.pending else self.store.pending['ref'],
                note_gaps=sum(len(f['note_errors'])+len(f['uncertain']) for f in self.store.frames),
                observation_errors=sum(bool(f['receipt_error'] or f['action_error']) for f in self.store.frames),
                scope='bounded exploration; not whole-app completion or verified canonical graph')
            self.store.write('status.json',result)
        return result
