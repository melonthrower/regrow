from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.paths import SOURCE_ROOT
'Persistent, bounded repair at stage acceptance boundaries. No GUI dispatch.'
from regrow.records.tasks import audit as task_audit
from regrow.records.object_store import owned_tasks
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import uuid
import subprocess
import jsonschema
from regrow.records.diagnostics import DiagnosticUnavailable, diagnostic, require_report, reject

def read(path):
    return json.loads(Path(path).read_text())

def support_review_eligible(error):
    """A malformed reply needs correction, not invented support tasks."""
    if isinstance(error, jsonschema.ValidationError):
        return False
    report = getattr(error, 'report', error)
    if isinstance(report, dict) and any(row.get('code') == 'schema' for row in report.get('errors', [])):
        return False
    return True

def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(tmp, path)

def refresh_retained_identity_candidate(run, job):
    """An identity-only answer cannot migrate a retained stage's other fields."""
    history = job.get('history', [])
    if not (job.get('control_identity_pair') or job.get('control_identity_candidates') or any((row.get('role') in ('control_identity_comparison',) for row in history))):
        return False
    rebuilt = [i for (i, row) in enumerate(history) if row.get('framework') == 'rebuilt_stage_image_contract']
    if not rebuilt or any((row.get('framework') == 'refresh_incompatible_retained_candidate' for row in history[rebuilt[-1]:])):
        return False
    try:
        from regrow.runtime.update_reply import main_pair
        spec, main = main_pair(job['request']['response_schema'], job.get('candidate'))
        jsonschema.validate(main, spec)
    except jsonschema.ValidationError as error:
        digest = hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()[:12]
        archive = Path(job['path']).with_name('episode-before-candidate-refresh-' + digest + '.json')
        atomic(Path(run) / archive, job)
        job['history'].append({'framework': 'refresh_incompatible_retained_candidate', 'original_episode': str(archive), 'previous_call': job.get('call'), 'error': diagnostic(error)})
        job.update(status='initial', candidate=None, record_edit=None)
        for key in ('control_identity_pair', 'control_identity_candidates', 'service_retry_request'):
            job.pop(key, None)
        return True
    return False

def content_rejection(failure):
    """Identify the provider's recorded content refusal, not every HTTP 402."""
    if failure.get('status') != 402:
        return False
    try:
        error = json.loads(failure.get('body', '')).get('error', {})
    except (ValueError, TypeError):
        return False
    return error.get('type') == 'param_error' and '敏感词' in error.get('message', '')

def resume_service_failure(run, episode=None, frame=None):
    """Explicitly retry one retained refusal; automatic rounds never call this."""
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.recognition import locator as _locator
    run = Path(run)
    current = pending(run)
    if episode is None:
        if not current:
            raise ValueError('没有待重试的服务失败步骤')
        episode = current['path']
    if current and current['path'] != episode:
        raise ValueError('先结算当前待处理步骤')
    path = (run / episode).resolve()
    if not path.is_relative_to(run.resolve()):
        raise ValueError('步骤不属于当前运行')
    job = read(path)
    failure = job.get('service_failure')
    if not failure or not (content_rejection(failure['error']) or job.get('suspended_recovery')):
        raise ValueError('不是已记录的内容拒绝或归档更新服务失败')
    execution = run / 'execution_pending.json'
    if (run / 'visual_navigation_pending.json').exists():
        raise ValueError('先结算待导航动作')
    if job.get('attempt'):
        if not execution.exists() or read(execution).get('attempt') != job['attempt']:
            raise ValueError('原动作的待结算记录缺失或不匹配')
    elif execution.exists():
        raise ValueError('已有其他待结算动作')
    discovery = _discovery_step
    source = job['request'].get('source', {})
    rid = source.get('task_region') or source.get('region')
    name = source.get('task_name')
    if job['stage'] == 'action' and (not job.get('attempt')) and (job.get('status') in ('deferred', 'suspended')):
        (_, records, _) = _record_load(run)
        task = owned_tasks(records.get(rid, {})).get(name, {})
        if task.get('status') != 'blocked' or task.get('deferral', {}).get('episode') != episode or task.get('blocker', {}).get('condition') != 'review_required' or task.get('blocker', {}).get('exception'):
            raise ValueError('原任务的暂挂来源不匹配')

        def reopen(records, state, *args):
            task = owned_tasks(records[rid])[name]
            task_audit(task).setdefault('deferral_history', []).append(task.pop('deferral'))
            if task.get('blocker'):
                task_audit(task).setdefault('blocker_history', []).append(task.pop('blocker'))
            task.update(status='pending')
            state.update(working_region=rid, active_task={'region': rid, 'name': name})
        _record_publish(run, 'service-retry-' + Path(episode).parent.name + '-' + str(len(job.get('service_resume_history', []))), reopen)
    if frame is not None and job['stage'] == 'discovery':
        discovery.await_discovery(run, str(Path(frame).resolve()), 'service-retry-' + failure['call'])
        job['request'] = _locator.request_from_run(SOURCE_ROOT, run)
    job.setdefault('service_resume_history', []).append({'failure': failure, 'previous_status': job['status'], 'explicit_retry': True})
    job.pop('service_failure', None)
    for key in ('branch_switch_attempted', 'branch_review_signature', 'switch_trigger'):
        job.pop(key, None)
    job.update(status='initial', candidate=None)
    atomic(path, job)
    atomic(run / 'pending_step.json', {'episode': episode})
    return job

class Paused(Exception):

    def __init__(self, status, reason):
        self.status = status
        self.reason = reason
        super().__init__(reason)

def pending(run, pointer_name='pending_step.json'):
    pointer = Path(run) / pointer_name
    if not pointer.exists():
        return None
    job = read(Path(run) / read(pointer)['episode'])
    return job

def retire_shared_review(run, pointer_name='pending_step.json'):
    """Keep an old review episode, but never resume its retired model contract."""
    run = Path(run)
    job = pending(run, pointer_name)
    if job is None or job.get('stage') not in ('shared_control_review', 'function_registration', 'task_result_review'):
        return False
    atomic((run / job['path']).with_name('retired_shared_review.json'),
           {'episode': job['path'], 'reason': 'redundant_call_removed', 'stage': job['stage'], 'gui_actions': 0})
    from regrow.runtime.reply_correction import abandon
    abandon(run, '独立复查/总结已退出；保留原调用与回复，由普通任务和更新继续。')
    (run / pointer_name).unlink()
    return True

def confirmed_dispatch_review(run, job, current_calls, window, current_frame):
    """One fresh correction for this specific, still undispatched frame change."""
    evidence = job.get('pre_dispatch_review')
    if not evidence or job.get('stage') != 'action' or job.get('status') != 'complete':
        return False
    if evidence.get('current') != str(current_frame):
        return False
    if job.get('repairs') != 1 or job.get('observations', 0) or job.get('record_edit'):
        return False
    ref = job.get('call')
    if ref not in current_calls or not window or window != evidence.get('window'):
        return False
    if (Path(run) / 'execution_pending.json').exists():
        return False
    folder = Path(run) / 'calls' / str(ref)
    if not (folder / 'request.json').exists() or not (folder / 'response.json').exists():
        return False
    sent = read(folder / 'request.json')
    reply = read(folder / 'response.json')
    if sent.get('role') != 'step_correction' or reply.get('resolution') != 'revise' or reply.get('blocked_by', 'none') != 'none':
        return False
    frames = sent.get('screenshots', [])
    current = evidence['current']
    return frames == [current] and job['request'].get('screenshots') == [current] and (sent.get('original_request', {}).get('screenshots') == [current]) and (reply.get('proposal') == job.get('candidate'))

def reobservable_block(run):
    """Return only a blocked proposal with no executed action left to register."""
    job = pending(run)
    if not job or job['status'] != 'blocked' or job.get('attempt') or job.get('diagnostic_failure'):
        return None
    if job.get('service_failure') and content_rejection(job['service_failure']['error']):
        return None
    if job['stage'] not in ('action', 'discovery', 'task_proposal'):
        return None
    if any(((Path(run) / p).exists() for p in ('execution_pending.json', 'visual_navigation_pending.json'))):
        return None
    return job

def reopen_blocked(run, frame):
    """Reobserve an unexecuted blocked proposal, keeping its audit."""
    from regrow.traversal import discovery_step as _discovery_step
    job = reobservable_block(run)
    if job is None:
        return False
    _discovery_step.await_discovery(run, str(Path(frame).resolve()),
                                  'blocked-' + Path(job['path']).parent.name,
                                  retain_target=job['stage'] in ('action', 'discovery'))
    job.update(status='superseded_by_observation', resume_frame=str(Path(frame).resolve()))
    atomic(Path(run) / job['path'], job)
    (Path(run) / 'pending_step.json').unlink()
    return True

def task_review_images(value):
    """A review and its saved correction retain the same validated evidence pair."""
    original = value.get('original_request', value)
    if not original.get('done_task_review') and original.get('role') not in ('observation_update', 'appearance_comparison'):
        return False
    from regrow.prompts.frame_context import validate
    validate(value)
    return True

def request(root, job, context):
    job = deepcopy(job)
    job['error'] = require_report(job.get('error'), job.get('rejected_reply', job.get('candidate')))
    from regrow.prompts import frame_context as _frame_context
    from regrow.runtime import model_transport as _model_transport
    from regrow.prompts import target_observation as _target_observation
    from regrow.records import action_owner_correction as _action_owner_correction
    from regrow.recognition import control_observation_repair as _control_observation_repair
    from regrow.traversal import correction_prompts as _correction_prompts
    from regrow.records import page_context as _page_context
    from regrow.recognition import matching as _visual_choices
    from regrow.recognition import control_identity_review as _control_identity_review
    if job['stage'] == 'action' and job.get('action_target_doubt'):
        from regrow.recognition import action_target_review
        return action_target_review.request(root, job)
    if not (job.get('control_identity_pair') or job.get('control_identity_candidates')
            or job['request'].get('needs_task_inspection') or job.get('record_edit') or job['request'].get('done_task_review') or job['request'].get('action_owner_review')
            or job.get('pre_dispatch_review') or _correction_prompts.needs_record_repair(job)):
        return _correction_prompts.original_reply(root, job)
    original = deepcopy(job['request'])
    rejected = deepcopy(job.get('rejected_reply', job.get('candidate')))
    identity_review = bool(job.get('control_identity_pair') or job.get('control_identity_candidates'))
    if job['stage'] == 'update' and not identity_review:
        # Registration uses the after-frame for geometry. Correcting the action
        # result must return to its original semantic pair and output contract.
        from regrow.traversal.object_registration import semantic_revision
        original, rejected = semantic_revision(original, rejected)
    if not task_review_images(original):
        _frame_context.select(original, _frame_context.primary(original))
    original['response_schema'] = _model_transport.expand_schema(original['response_schema'])
    if job['stage'] == 'action' and (not original.get('needs_task_inspection')):
        original = _target_observation.refresh(original)
    edit = {'type': 'object', 'properties': {n: {'type': 'string'} for n in ('region', 'control', 'field', 'before', 'after', 'evidence')}, 'required': ['region', 'control', 'field', 'before', 'after', 'evidence'], 'additionalProperties': False}
    task_edit = {'type': 'object', 'properties': {n: {'type': 'string'} for n in ('region', 'task', 'field', 'before', 'after', 'evidence')}, 'required': ['region', 'task', 'field', 'before', 'after', 'evidence'], 'additionalProperties': False}
    task_edit['properties']['field'] = {'type': 'string', 'enum': ['task_control', 'suspend_task']}
    edits = [edit] if original.get('screenshots') else []
    if edits and job['stage'] in ('discovery', 'task_proposal'):
        edits.append(task_edit)
    if edits and job['stage'] != 'action':
        if original.get('action_owner_candidates') and (not job.get('attempt')):
            edits.append(_action_owner_correction.schema())
        if original.get('control_observation_candidates'):
            edits.append(_control_observation_repair.schema())
    edit = {'anyOf': edits} if edits else {'type': 'null'}
    fields = {'reason': {'type': 'string'}, 'resolution': {'type': 'string', 'enum': ['revise', 'observe', 'edit_record', 'defer']}, 'proposal': {'anyOf': [deepcopy(original['response_schema']), {'type': 'null'}]}, 'record_edit': {'anyOf': [edit, {'type': 'array', 'items': edit}, {'type': 'null'}]}}
    if not edits:
        fields['record_edit'] = {'type': 'null'}
        fields['resolution']['enum'].remove('edit_record')
    if job['stage'] in ('object_registration', 'appearance_comparison'):
        fields['resolution']['enum'] = ['revise', 'defer']
        fields['record_edit'] = {'type':'null'}
    if job['stage'] == 'task_proposal':
        fields['proposal']['anyOf'][0]['properties']['new_tasks']['items']['properties']['control'].pop('enum', None)
    from regrow.traversal.proposal_revision import prepare as prepare_revision, guidance, display, examples, MODE
    review = original.get('done_task_review')
    if review:
        task_edit['properties'].update({key: {'const': value} for key, value in {
            'region': review['region'], 'task': review['task'], 'field': 'reopen_task',
            'before': review['before'].get('control') or ''}.items()})
        fields['proposal'] = {'type': 'null'}
        fields['record_edit'] = {'anyOf': [task_edit, {'type': 'null'}]}
        fields['resolution']['enum'] = ['edit_record', 'defer']
        proposal_base = None
    elif original.get('action_owner_review'):
        owner_edit = _action_owner_correction.schema()
        candidate = original['action_owner_candidates'][0]
        owner_edit['properties'].update({key: {'const': value} for key, value in candidate.items()})
        fields['proposal'] = {'type': 'null'}
        fields['record_edit'] = {'anyOf': [owner_edit, {'type': 'null'}]}
        fields['resolution']['enum'] = ['edit_record', 'defer']
        proposal_base = None
    else:
        proposal_base = prepare_revision(job, original, fields['proposal']['anyOf'][0])
    if fields.get('record_edit') == {'type': 'null'}:
        fields.pop('record_edit')
    schema = {'type': 'object', 'properties': fields, 'required': [name for name in fields if name != 'record_edit'], 'additionalProperties': False,
              'allOf': [{'if': {'properties': {'resolution': {'const': 'edit_record'}}, 'required':['resolution']},
                         'then': {'required':['record_edit'], 'properties':{'record_edit':{'not':{'type':'null'}}}}}]}
    dynamic = {'失败步骤': job['stage'], '原动态上下文': original['user_prompt'], '相关记录与可用能力': context, '被拒绝回复': rejected, '上次失败或停止诊断（保留原文，非当前能力清单）': job.get('error'), '框架错误分类': job.get('blocked_by', 'none'), '执行状态': '原动作已执行；本次纠错只登记其结果，不再次投递原动作。next_action描述后续尚未执行的步骤，仍按原问题与动作后图判断；无需因本次是纠错而清空。' if job.get('attempt') else '本步骤未执行动作', '本次修复历史': job['history'], '补充观察': job.get('supplements', []), '图片说明': '前面的图片仍为原请求证据；追加图片仅用于稍后的补充观察，不能代替原动作后图。'}
    if proposal_base is not None:
        dynamic['本次合并基准'] = display(proposal_base)
        dynamic['修订方式'] = guidance()
        dynamic['局部修订格式示例'] = examples(proposal_base)
        if dynamic['被拒绝回复'] == proposal_base:
            dynamic['被拒绝回复'] = '同下方本次合并基准。'
    dynamic.update(_correction_prompts.parse_disclosure(job))
    (dynamic['原动态上下文'], shared_map) = _page_context.separate_map(original)
    if shared_map:
        dynamic[_page_context.TITLE] = shared_map
    if original.get('needs_task_inspection'):
        dynamic['当前前置缺口'] = '原任务控件缺少已登记的当前定位，点击坐标或改写名称不能补齐登记。请选择observe定向观察原任务控件，或defer保留缺口；补定位成功后回正常动作选择。'
        dynamic['原任务'] = original.get('source', {}).get('task_name')
    if original.get('visual_choices'):
        dynamic['待消歧控件'] = _visual_choices.describe(original)
    parts = _correction_prompts.parts(root, job, context)
    if job['stage'] == 'action':
        target_prompt = Path(root) / 'regrow/prompts/动作/目标观察阅读.prompt'
        parts.append({'path': '动作/目标观察阅读.prompt', 'text': target_prompt.read_text()})
    dispatch_review = job.get('pre_dispatch_review')
    if dispatch_review:
        path = '纠错/投递前画面变化.prompt'
        parts.append({'path': path, 'text': (Path(root) / 'regrow/prompts' / path).read_text()})
    if original.get('visual_choices'):
        choice_prompt = Path(root) / 'regrow/prompts/纠错/控件候选消歧.prompt'
        parts.append({'path': '纠错/控件候选消歧.prompt', 'text': choice_prompt.read_text()})
    from regrow.prompts.compose import compose
    original_parts = original.get('fixed_parts', [])
    if '\n\n'.join((p['text'] for p in original_parts)) != original['system_prompt']:
        original_parts = [{'path': '原步骤保存规则', 'text': original['system_prompt']}]
    parts = compose(original_parts, parts)
    text = json.dumps(dynamic, ensure_ascii=False, indent=2)
    frames = list(original.get('screenshots', []))
    if job['stage'] == 'action':
        if len(frames) != 1:
            raise ValueError('动作纠错需要唯一当前执行依据图；先沿正常发现刷新原任务')
        if dispatch_review and frames != [dispatch_review['current']]:
            raise ValueError('动作纠错当前图不是指定的最新投递前画面')
        image_roles = [{'图片': 1, '用途': '最新投递前画面' if dispatch_review else '当前动作执行依据'}]
        dynamic['图片说明'] = '唯一图片是本次选点依据。历史及补充观察中的图片路径仅为审计引用，图片未附入本请求；历史文字描述不能证明当前坐标。'
        dynamic['历史视觉修订'] = '单图动作纠错不提供历史图，不能迁移历史动作或控件观察归属；需要历史视觉核对时保留缺口，沿已有观察或任务结果核对处理。'
    else:
        image_roles = _frame_context.roles(original)
        dynamic['图片说明'] = '本图沿用原步骤依据；补充观察与历史按其文字记录和来源读取。'
    dynamic['图片顺序'] = image_roles
    text = json.dumps(dynamic, ensure_ascii=False, indent=2)
    correction = {**original, 'role': 'step_correction', 'stage': 'step_correction', 'original_request': deepcopy(original), 'system_prompt': '\n\n'.join((p['text'] for p in parts)), 'user_prompt': text, 'dynamic_prompt': text, 'screenshots': frames, 'image_refs': frames, 'response_schema': schema, 'fixed_parts': parts}
    if proposal_base is not None:
        correction['proposal_base'] = proposal_base
        correction['proposal_revision'] = MODE
    correction['frame_context'] = {str(frame): role['用途'] for (frame, role) in zip(frames, image_roles)}
    correction = _control_identity_review.attach(root, job, correction)
    if correction.get('role') == 'step_correction':
        retained = deepcopy(dynamic)
        for key in ('被拒绝回复', '本次合并基准', '上次失败或停止诊断（保留原文，非当前能力清单）'):
            retained.pop(key, None)
        correction['_correction_context'] = {
            'context': json.dumps(retained, ensure_ascii=False, indent=2),
            'reply': deepcopy(dynamic.get('本次合并基准', rejected)),
            'issues': [], 'notes': None, 'report': deepcopy(job['error'])}
        if proposal_base is not None and job.get('rejected_reply') is not None:
            correction['_correction_context']['latest_reply'] = deepcopy(
                job.get('rejected_model_reply', job['rejected_reply']))
    return correction

class Runner:

    def __init__(self, root, run, call, screenshot, available, pointer_name='pending_step.json', review_update=None):
        from regrow.traversal import repair_stages as _repair_stages
        self.root = Path(root)
        self.run = Path(run)
        self.call = call
        self.screenshot = screenshot
        self.available = available
        self.adapters = _repair_stages
        self.pointer_name = pointer_name
        self.review_update = review_update
        retire_shared_review(self.run, pointer_name)

    def save(self, job):
        atomic(self.run / job['path'], job)

    def pause_diagnostic(self, job, error):
        job.update(status='blocked', diagnostic_failure=deepcopy(error.detail))
        if error.detail.get('call'):
            job['call'] = error.detail['call']
        self.save(job)
        raise Paused(error.status, error.reason) from error

    def correction_request(self, job):
        try:
            require_report(job.get('error'), job.get('rejected_reply', job.get('candidate')))
            display_job = deepcopy(job)
            if job.get('rejected_reply') is not None and job.get('call'):
                source = self.run / 'calls' / job['call'] / 'response.json'
                if source.exists():
                    display_job['rejected_model_reply'] = read(source)
            return request(self.root, display_job, self.adapters.context(self.run, job))
        except DiagnosticUnavailable as error:
            self.pause_diagnostic(job, error)

    def sent_request(self, job, q, ref, repairing):
        path = self.run / 'calls' / str(ref) / 'request.json'
        if path.exists():
            q = read(path)
            from regrow.records.calls import business_request
            q = business_request(self.run, q)
            if not repairing:
                job['request'] = deepcopy(q)
            elif q.get('role') == 'step_correction' and q.get('original_request'):
                # Transport may append disclosed identities and bind a new schema.
                # Validate/interpret the proposal using that exact sent contract.
                job['request'] = deepcopy(q['original_request'])
        return q

    def format_budget(self, job):
        from regrow.runtime.reply_correction import budget
        def consume():
            job['repairs'] += 1
            self.save(job)
        return budget(lambda: 2 - job['repairs'], consume)

    def stop(self, job, reason):
        from regrow.runtime.reply_correction import abandon
        abandon(self.run, str(reason))
        from regrow.traversal import task_deferral as _task_deferral
        if not isinstance(reason, str):
            reason = json.dumps(reason, ensure_ascii=False)
        # Stopping/retry-budget messages do not replace the latest failed facts.
        try:
            retained = require_report(job.get('error'), job.get('rejected_reply', job.get('candidate')))
        except DiagnosticUnavailable:
            retained = job.get('error') or reason
        job['stop_reason'] = reason
        if job['request'].get('done_task_review'):
            job.update(status='deferred', error=retained,
                       deferral={'next': False, 'record_review_only': True})
            self.save(job)
            (self.run / self.pointer_name).unlink(missing_ok=True)
            raise Paused('record_review_deferred', reason)
        decision = _task_deferral.defer(self.run, job, reason)
        if decision is not None:
            job.update(status='deferred', deferral=decision, error=retained)
            self.save(job)
            (self.run / self.pointer_name).unlink(missing_ok=True)
            raise Paused('task_deferred' if decision['next'] else 'task_blocked', reason)
        job.update(status='blocked', error=retained)
        self.save(job)
        raise Paused('correction_blocked', reason)

    def repair_step(self, stage, q, reason):
        if pending(self.run, self.pointer_name):
            raise Paused('correction_blocked', '先处理已有待修复步骤')
        key = uuid.uuid4().hex
        job = {'path': f'repair_episodes/{key}/episode.json', 'stage': stage, 'request': deepcopy(q), 'attempt': None, 'status': 'repair', 'repairs': 0, 'observations': 0, 'history': [{'framework': reason}], 'seen': [], 'supplements': [], 'error': reason}
        self.save(job)
        atomic(self.run / self.pointer_name, {'episode': job['path']})
        return self.perform(stage)

    def reject_action(self, q, candidate, ref, reason, pre_dispatch_review=None, action_target_doubt=None):
        if pending(self.run, self.pointer_name):
            raise Paused('correction_blocked', '已有步骤待修复')
        key = uuid.uuid4().hex
        actual = action_target_doubt or ({key: pre_dispatch_review[key] for key in
                  ('frame_comparison', 'changed_window') if key in pre_dispatch_review}
                  if pre_dispatch_review else None)
        report = {'errors': [{'code': 'action_evidence_review', 'object': candidate.get('target'),
                             'actual': actual, 'expected': reason}], 'unchecked': []} if actual else reason
        job = {'path': f'repair_episodes/{key}/episode.json', 'stage': 'action', 'request': deepcopy(q), 'attempt': None, 'status': 'repair', 'repairs': 0, 'observations': 0, 'history': [{'call': ref, 'error': report}], 'seen': [], 'supplements': [], 'candidate': candidate, 'call': ref, 'error': report, 'requires_observation': True}
        if action_target_doubt:
            job['action_target_doubt'] = deepcopy(action_target_doubt)
        if pre_dispatch_review:
            job['pre_dispatch_review'] = deepcopy(pre_dispatch_review)
        self.save(job)
        atomic(self.run / self.pointer_name, {'episode': job['path']})
        raise Paused('repair_pending', reason)

    def switch_branch(self, job):
        from regrow.tools import branch_switch as _branch_switch
        failure = job.get('service_failure', {}).get('error', {})
        if failure and (not content_rejection(failure)):
            failed = job.pop('service_failure')
            job['service_retry_request'] = read(self.run / 'calls' / failed['call'] / 'request.json')
            if failed not in job.setdefault('service_error_history', []):
                job['service_error_history'].append(failed)
            if job['status'] == 'blocked':
                role = job['service_retry_request'].get('role')
                job['status'] = 'repair' if role in ('step_correction', 'control_identity_comparison') else 'initial'
            self.save(job)
            raise Paused('model_service_unavailable', '模型接口失败；保留原步骤和任务，修复服务或请求后继续，不据此切换业务区块。')
        if job.get('suspended_recovery'):
            job.update(status='blocked', error='归档结果恢复仍失败；保留原待登记动作，不再次归档或重复GUI')
            self.save(job)
            raise Paused('correction_blocked', job['error'])
        if content_rejection(failure):
            reason = '服务拒绝请求：检测到敏感词；有限重试已结束，保留原请求与未完成结果。'
            if job.get('attempt') or (self.run / 'execution_pending.json').exists():
                job.update(status='blocked', error=reason)
                self.save(job)
                raise Paused('correction_blocked', reason + '原GUI已执行，只能重试登记。')
            if job['stage'] in ('action', 'task_proposal'):
                self.stop(job, reason)
        if self.available() < 1:
            raise Paused('repair_pending', '本轮调用额度已用完；下一轮继续原纠错请求')
        if job['request'].get('done_task_review'):
            self.stop(job, job.get('error') or '本次指定原题复核未形成可接受修订')
        from regrow.runtime.reply_correction import abandon
        abandon(self.run, '原业务分支暂挂，转入分支继续策略')
        decision = _branch_switch.correct(self, job)
        if decision:
            raise Paused('ready_next_round' if decision.get('resumed') else 'task_deferred', '纠错已解决本次循环判断；重新发现后按新办法继续' if decision.get('resumed') else '纠错已暂挂当前分支；重新发现后继续独立区块')
        raise Paused('correction_blocked', '当前分支未切换；保留未完成记录')

    def perform(self, stage, q=None, attempt=None, *, candidate=None, source_call=None):
        from regrow.prompts import history_disclosure as _history_disclosure
        from regrow.traversal import result_updater as _result_updater
        from regrow.traversal import correction_crop_feedback as _correction_crop_feedback

        from regrow.records import update_semantic_review as _update_semantic_review
        from regrow.recognition import ownership_review as _ownership_review
        from regrow.runtime import model_transport as _model_transport
        from regrow.recognition import control_identity_review as _control_identity_review
        from regrow.records import registration_diagnostics as _registration_diagnostics
        job = pending(self.run, self.pointer_name)
        if job is None:
            key = uuid.uuid4().hex
            job = {'path': f'repair_episodes/{key}/episode.json', 'stage': stage, 'request': deepcopy(q), 'attempt': attempt, 'status': 'initial', 'repairs': 0, 'observations': 0, 'history': [], 'seen': [], 'supplements': []}
            if source_call is not None:
                job.update(status='accept', candidate=deepcopy(candidate), call=source_call)
            self.save(job)
            atomic(self.run / self.pointer_name, {'episode': job['path']})
        elif stage != job['stage']:
            raise Paused('correction_blocked', '必须先处理尚未完成的步骤：' + job['stage'])
        if job.get('diagnostic_failure'):
            failure = job['diagnostic_failure']
            raise Paused(DiagnosticUnavailable.status,
                         DiagnosticUnavailable(failure.get('diagnostic'), failure['missing']).reason)
        if job['status'] in ('repair', 'blocked') and not job.get('service_failure'):
            try:
                require_report(job.get('error'), job.get('rejected_reply', job.get('candidate')))
            except DiagnosticUnavailable as error:
                self.pause_diagnostic(job, error)
        # Active identity comparisons do not make the execution-source contract old.
        if (stage == 'update' and job['status'] not in ('complete', 'deferred', 'blocked')
                and (_result_updater.has_source_revision(job['request'])
                     or job.get('suspended_recovery') and 'next_action' in job['request'].get('response_schema', {}).get('properties', {}))):
            archive = Path(job['path']).with_name('episode-before-fixed-source.json')
            if not (self.run / archive).exists():
                atomic(self.run / archive, job)
            fresh = _result_updater.rebuild_retained(self.root, self.run, job)
            job['history'].append({'framework': 'rebuilt_fixed_execution_source',
                                   'original_episode': str(archive), 'previous_call': job.get('call')})
            job.update(request=fresh, status='initial', candidate=None, record_edit=None)
            for key in ('service_retry_request', 'identity_recheck_request',
                        'control_identity_pair', 'control_identity_candidates',
                        'identity_candidate', 'registration_submission', 'object_registration'):
                job.pop(key, None)
            self.save(job)
        if stage == 'action' and job['status'] != 'complete':
            source_text = _history_disclosure.structured_text(job['request'])
            try:
                structured = json.JSONDecoder().raw_decode(source_text)[0]
            except (ValueError, TypeError):
                structured = None
            if not isinstance(structured, dict):
                saved = deepcopy(job['request'])
                fresh = self.adapters.refresh(self.root, self.run, job)
                digest = hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest()[:12]
                archive = Path(job['path']).with_name('request-before-material-' + digest + '.json')
                if not (self.run / archive).exists():
                    atomic(self.run / archive, saved)
                episode_archive = archive.with_name('episode-before-material-' + digest + '.json')
                if not (self.run / episode_archive).exists():
                    atomic(self.run / episode_archive, job)
                if job.get('service_retry_request'):
                    retry_path = archive.with_name('service-retry-before-material-' + digest + '.json')
                    if not (self.run / retry_path).exists():
                        atomic(self.run / retry_path, job['service_retry_request'])
                    job.pop('service_retry_request')
                job['history'].append({'framework': 'rebuilt_original_action_material', 'original_request': str(archive), 'original_episode': str(episode_archive), 'previous_call': job.get('call')})
                job.update(request=fresh, status='initial', candidate=None, record_edit=None)
                self.save(job)
        if job.get('control_identity_candidates'):
            from regrow.traversal.object_registration import partition_request, save_candidate
            group = job['control_identity_candidates']
            reason = str(_control_identity_review.CandidateConflict(group))
            try:
                revised, retained = partition_request(job['request'], job['candidate'],
                    {'/controls/' + str(group[0]['control_index']): reason})
            except ValueError as required_object:
                self.stop(job, str(required_object))
            job.pop('control_identity_candidates')
            job.update(status='accept')
            save_candidate(self, job, revised, retained)
        retry = job.get('service_retry_request', {})
        old_retry = len(retry.get('screenshots', [])) > 1 and retry.get('role') != 'control_identity_comparison' and not task_review_images(retry)
        if ((len(job['request'].get('screenshots', [])) > 1 and not task_review_images(job['request'])) or old_retry) and job['status'] != 'complete':
            archive = Path(job['path']).with_name('request-before-image-contract.json')
            if not (self.run / archive).exists():
                atomic(self.run / archive, job['request'])
            if stage == 'update':
                fresh = _result_updater.rebuild_retained(self.root, self.run, job)
            else:
                fresh = self.adapters.refresh(self.root, self.run, job)
            job['request'] = fresh
            job['history'].append({'framework': 'rebuilt_stage_image_contract', 'original_request': str(archive)})
            if job.get('control_identity_pair'):
                job['control_identity_pair']['current_image'] = 1
            if old_retry:
                retry_archive = archive.with_name('service-retry-before-image-contract.json')
                if not (self.run / retry_archive).exists():
                    atomic(self.run / retry_archive, retry)
                rebuilt = self.correction_request(job) if job['status'] == 'repair' else deepcopy(fresh)
                if job['status'] == 'repair':
                    _correction_crop_feedback.attach(self.run, job, rebuilt)
                job['service_retry_request'] = rebuilt
                job['history'].append({'framework': 'rebuilt_service_retry_image_contract', 'original_request': str(retry_archive)})
            self.save(job)
        if job['status'] != 'complete' and refresh_retained_identity_candidate(self.run, job):
            self.save(job)
        if stage == 'update' and self.review_update is not None and (not job.get('requires_update_review')):
            job['requires_update_review'] = True
            self.save(job)
        if job.get('service_failure') and (not content_rejection(job['service_failure']['error'])):
            self.switch_branch(job)
        if job.get('service_failure') or job.get('switch_trigger'):
            self.switch_branch(job)
        if job['status'] == 'blocked':
            if job.get('suspended_recovery'):
                raise Paused('historical_update_conflict', job['error'])
            last = read(self.run / 'calls' / job['call'] / 'response.json') if job.get('call') else {}
            if last.get('resolution') == 'edit_record' and self.adapters.edit_proposal(self.run, job, last.get('record_edit')):
                self.save(job)
            else:
                self.stop(job, job.get('stop_reason') or job['error'])
        if job['status'] == 'deferred':
            (self.run / self.pointer_name).unlink(missing_ok=True)
            raise Paused('task_deferred' if job['deferral']['next'] else 'task_blocked', job.get('stop_reason') or job['error'])
        while True:
            if job['status'] == 'complete':
                (self.run / self.pointer_name).unlink(missing_ok=True)
                return job
            if job['status'] == 'repair':
                try:
                    require_report(job.get('error'), job.get('rejected_reply', job.get('candidate')))
                except DiagnosticUnavailable as error:
                    self.pause_diagnostic(job, error)
            if job['status'] == 'observe':
                from regrow.runtime import reply_correction
                if self.available() < 1:
                    raise Paused('repair_pending', '等待下一轮额度补观察')
                try:
                    with self.format_budget(job):
                        self.adapters.observe(self, job)
                    if job['stage'] == 'action' and job['request'].get('action_ready'):
                        job['request'].pop('action_target_confirmation', None)
                        job.pop('action_target_doubt', None)
                        job['status'] = 'initial'
                        self.save(job)
                        continue
                except reply_correction.Pending as error:
                    self.save(job)
                    raise Paused('repair_pending', str(error))
                except reply_correction.Failed as error:
                    self.stop(job, str(error))
                except DiagnosticUnavailable as error:
                    self.pause_diagnostic(job, error)
                except (ValueError, jsonschema.ValidationError) as error:
                    job['error'] = diagnostic(error)
                    job['history'].append({'observation_error': diagnostic(error)})
                job['status'] = 'repair'
                self.save(job)
                continue
            if job['status'] == 'accept':
                if job['stage'] == 'update' and (self.review_update or job.get('requires_update_review')):
                    job['requires_update_review'] = True
                    self.save(job)
                    review = _update_semantic_review
                    try:
                        review.check(self.run, job, self.review_update)
                    except review.Pending as error:
                        raise Paused('review_pending', str(error))
                    except review.Rejected as error:
                        job.update(error=str(error), blocked_by=error.blocked_by, status='repair')
                        job['identity_controls'] = error.identity_controls
                        job['history'].append({'call': job['call'], 'error': str(error), 'source': 'supervisor_review'})
                        self.save(job)
                        continue
                try:
                    # Collect every schema error before readers/registration can
                    # stop on the first malformed field. Task names can be
                    # checked independently even when another field is invalid.
                    if not job.get('record_edit'):
                        _, records, _ = _record_load(self.run)
                        _registration_diagnostics.check(
                            'task_proposal' if job['stage'] == 'task_proposal' else 'reply',
                            job['request'], job['candidate'], records)
                    from regrow.traversal.object_registration import complete as complete_objects
                    complete_objects(self, job)
                    result = self.adapters.accept(self.root, self.run, job)
                except Paused as error:
                    if job['stage'] == 'update' and error.status == 'correction_blocked':
                        self.stop(job, error.reason)
                    raise
                except DiagnosticUnavailable as error:
                    self.pause_diagnostic(job, error)
                except (ValueError, jsonschema.ValidationError) as error:
                    if job['stage'] == 'action' and getattr(error, 'refresh_request', False):
                        try:
                            refreshed = self.adapters.refresh(self.root, self.run, job)
                        except (ValueError, jsonschema.ValidationError) as refresh_error:
                            error = refresh_error
                        else:
                            job['history'].append({'call': job['call'], 'error': diagnostic(error), 'resolution': 'refresh_original_task'})
                            refreshed.pop('action_target_confirmation', None)
                            job.pop('action_target_doubt', None)
                            job.update(request=refreshed, status='initial', candidate=None, record_edit=None)
                            self.save(job)
                            continue
                    if _ownership_review.begin(self.run, job, diagnostic(error)):
                        raise Paused('repair_pending', '区块归属需实地复查；原记录与提案已保存')
                    if getattr(error, 'defer_task', False):
                        self.stop(job, str(error))
                    if getattr(error, 'blocked_by', None):
                        job['blocked_by'] = error.blocked_by
                    if getattr(error, 'control_identity_pair', None):
                        job['control_identity_pair'] = error.control_identity_pair
                    if getattr(error, 'control_identity_candidates', None):
                        from regrow.traversal.object_registration import partition_request, save_candidate
                        group = error.control_identity_candidates
                        failed = {'/controls/' + str(group[0]['control_index']): str(error)}
                        try:
                            q, retained = partition_request(job['request'], job['candidate'], failed)
                        except ValueError as required_object:
                            self.stop(job, str(required_object))
                        job.pop('control_identity_candidates', None)
                        job.pop('control_identity_pair', None)
                        job['history'].append({'call': job['call'], 'unresolved_identity': group, 'reason': str(error)})
                        save_candidate(self, job, q, retained)
                        continue
                    if getattr(error, 'action_target_doubt', None):
                        job['action_target_doubt'] = error.action_target_doubt
                    job['error'] = diagnostic(error)
                    job['status'] = 'repair'
                    job['history'].append({'call': job['call'], 'error': diagnostic(error)})
                    self.save(job)
                    continue
                job.update(status='complete', result=result)
                self.save(job)
                continue
            if self.available() < 1:
                raise Paused('repair_pending', '等待下一轮额度继续原步骤')
            repairing = job['status'] == 'repair'
            if job.get('identity_recheck_request'):
                q = job.pop('identity_recheck_request')
                self.save(job)
            elif job.get('service_retry_request'):
                q = job.pop('service_retry_request')
                self.save(job)
            elif repairing:
                if job['repairs'] >= 2:
                    self.stop(job, '纠错次数已用完；保留原任务和未解决记录')
                q = self.correction_request(job)
                _correction_crop_feedback.attach(self.run, job, q)
                job['repairs'] += 1
                self.save(job)
            else:
                q = job['request']
            try:
                from regrow.runtime import reply_correction
                with self.format_budget(job):
                    (ref, reply) = self.call(q)
            except reply_correction.Pending as error:
                if error.different_request:
                    raise Paused('correction_blocked', str(error))
                job['service_retry_request'] = deepcopy(error.state['next'])
                self.save(job)
                raise Paused('repair_pending', str(error))
            except reply_correction.Failed as error:
                job['error'] = error.state['error']
                job['call'] = error.state['last_call']
                self.save(job)
                self.stop(job, str(error))
            except DiagnosticUnavailable as error:
                self.pause_diagnostic(job, error)
            except subprocess.CalledProcessError:
                manifest = Path(self.run) / 'run_manifest.json'
                failed = read(manifest).get('last_call') if manifest.exists() else None
                folder = Path(self.run) / 'calls' / str(failed)
                q = self.sent_request(job, q, failed, repairing)
                failure = _model_transport.read_service_error(folder)
                if failure is None:
                    raise
                job.setdefault('service_error_history', []).append({'call': failed, 'error': failure})
                transient = failure.get('status') in (429, 500, 502, 503, 504) or failure.get('exception_type') in ('ReadTimeout', 'ConnectTimeout', 'ConnectionError')
                if (transient or content_rejection(failure)) and (not job.get('service_retry_used')):
                    job['service_retry_used'] = True
                    job['service_retry_request'] = deepcopy(q)
                    self.save(job)
                    continue
                if not content_rejection(failure):
                    job['service_retry_request'] = deepcopy(q)
                    self.save(job)
                    raise Paused('model_service_unavailable', '模型接口或回复失败；原步骤、任务、失败和计数保留，修复后续接原请求。')
                job['service_failure'] = {'call': failed, 'error': failure}
                self.save(job)
                self.switch_branch(job)
            q = self.sent_request(job, q, ref, repairing)
            previous_call = job.get('call')
            if q.get('role') not in ('control_identity_comparison',):
                job.pop('registration_submission', None)
            job['call'] = ref
            job['history'].append({'call': ref, 'role': q.get('role')})
            try:
                if repairing:
                    if q.get('correction_format') == 'original':
                        from regrow.traversal.proposal_revision import merge
                        from regrow.traversal.object_registration import revised_request
                        candidate = merge(q, reply)
                        corrected_request = revised_request(q['original_request'], previous_call) if job['stage'] == 'update' else deepcopy(q['original_request'])
                        fingerprint = hashlib.sha256(json.dumps([candidate, job['request'], job.get('supplements'), job.get('record_edit')], sort_keys=True).encode()).hexdigest()
                        if fingerprint in job['seen']:
                            self.stop(job, '重复提交同一证据下已拒绝的提案')
                        job['seen'].append(fingerprint)
                        atomic(self.run / 'calls' / ref / 'effective_request.json', corrected_request)
                        atomic(self.run / 'calls' / ref / 'effective_candidate.json', candidate)
                        job.pop('rejected_reply', None)
                        job.update(request=corrected_request, candidate=candidate, status='accept')
                        self.save(job)
                        continue
                    if q.get('role') == 'action_target_review':
                        from regrow.recognition import action_target_review
                        reviewed, candidate = action_target_review.accept(q, reply, ref)
                        atomic(self.run / 'calls' / ref / 'effective_request.json', reviewed)
                        atomic(self.run / 'calls' / ref / 'effective_candidate.json', candidate)
                        job.pop('action_target_doubt', None)
                        job.update(request=reviewed, candidate=candidate, status='accept')
                        self.save(job)
                        continue
                    if q.get('role') == 'control_identity_comparison':
                        (reviewed, candidate) = _control_identity_review.compared_candidate(q, reply)
                        if candidate is None:
                            self.stop(job, '身份比较仍未确认：' + reply['reason'])
                        if job['stage'] == 'update':
                            from regrow.traversal.object_registration import revised_request
                            reviewed = revised_request(reviewed, previous_call)
                        atomic(self.run / 'calls' / ref / 'effective_request.json', reviewed)
                        atomic(self.run / 'calls' / ref / 'effective_candidate.json', candidate)
                        if not q.get('identity_rules_recheck'):
                            job['repairs'] = max(0, job['repairs'] - 1)
                        job.pop('control_identity_pair', None)
                        job.update(request=reviewed, candidate=candidate, status='accept')
                        if reply['control_identity'] == 'different' and q['control_identity_pair'].get('kind') == 'reuse':
                            from regrow.traversal.object_registration import semantic_revision
                            original, revised = semantic_revision(reviewed, candidate)
                            job.update(request=original, candidate=revised)
                            job.pop('registration_submission', None)
                            pair = q['control_identity_pair']
                            report = {'errors': [{'code': 'control_reuse_denied',
                                'object': pair['region_name'] + '中的' + pair['current_name'],
                                'field': '旧控件引用',
                                'actual': {'提交的引用': pair.get('submitted_ref', pair['ref']),
                                           '历史控件': pair['old_name'], '身份比较结论': reply['control_identity'],
                                           '比较依据': reply['reason']},
                                'reason': '当前控件与所引用的历史控件不是同一对象。',
                                'expected': '不再把当前对象的作用写入该历史控件',
                                'repair': '修正本次对象登记及相关任务知识、访问目标和下一步：旧对象未出现则撤回引用；当前为新对象则省略ref并补充资料。'}],
                                'unchecked': []}
                            job.update(status='repair', error=report)
                        self.save(job)
                        continue
                    repeated = reply.get('proposal') if isinstance(reply, dict) else None
                    if repeated is not None and (not q.get('control_identity_pair')):
                        check = hashlib.sha256(json.dumps([repeated, job['request'], job.get('supplements'), reply.get('record_edit')], sort_keys=True).encode()).hexdigest()
                        if check in job['seen']:
                            self.stop(job, '重复提交同一证据下已拒绝的提案')
                    _registration_diagnostics.check('correction', {'response_schema': q['response_schema'], 'original_stage': job['stage']}, reply, {})
                    resolution = 'defer' if reply['resolution'] == 'blocked' else reply['resolution']
                    if not reply['reason'].strip():
                        reject('correction_reason', '本次纠错回复', reply['reason'], '非空的修复依据',
                               field='修复依据', reason='纠错回复没有说明修复依据。')
                    if resolution != 'revise' and reply['proposal'] is not None:
                        reject('correction_proposal', '本次纠错回复',
                               {'修复方式': resolution, '提交的提案': reply['proposal']},
                               '修复方式不是 revise 时 proposal 为 null', field='修复方式与提案',
                               reason='该修复方式不接受业务提案。')
                    if resolution == 'revise' and reply['proposal'] is None:
                        reject('correction_proposal', '本次纠错回复', reply['proposal'],
                               'revise 对应需要修正的业务提案', field='修订提案', reason='选择了修订提案，但 proposal 为空。')
                    if resolution == 'edit_record' and reply.get('record_edit') is None:
                        reject('correction_record_edit', '本次纠错回复', reply.get('record_edit'),
                               'edit_record 对应具体记录修订', field='记录修订', reason='选择了修订记录，但没有提交具体修订。')
                    if resolution not in ('revise', 'edit_record') and reply.get('record_edit') is not None:
                        reject('correction_record_edit', '本次纠错回复',
                               {'修复方式': resolution, '记录修订': reply.get('record_edit')},
                               '该修复方式的 record_edit 为 null', field='修复方式与记录修订',
                               reason='该修复方式不接受记录修订。')
                    if resolution == 'defer':
                        self.stop(job, reply['reason'])
                    if resolution == 'observe':
                        if job.get('suspended_recovery'):
                            self.stop(job, '历史补登记只能核对原动作证据；当前补观察不能替代历史后图')
                        if job['observations'] >= 1:
                            self.stop(job, '本次纠错已补观察，仍缺少依据')
                        job.update(status='observe', observation_question=reply['reason'])
                        self.save(job)
                        continue
                    if resolution == 'edit_record':
                        if job.get('suspended_recovery'):
                            self.stop(job, '历史补登记不能顺带改写当前身份或任务；保留原证据待核对')
                        if self.adapters.edit_proposal(self.run, job, reply.get('record_edit')):
                            self.save(job)
                            continue
                        self.adapters.edit_record(self.root, self.run, job, reply.get('record_edit'))
                        if job['request'].get('action_owner_review'):
                            job.update(status='complete', result={'record_edit': reply.get('record_edit'),
                                       'resolution': 'action_owner_corrected', 'new_gui_action': False})
                            self.save(job)
                            continue
                        if job['request'].get('done_task_review'):
                            job.update(status='complete', result={'record_edit': reply.get('record_edit'),
                                       'resolution': 'original_task_reopened', 'new_gui_action': False})
                            self.save(job)
                            continue
                        job['request'] = self.adapters.refresh(self.root, self.run, job)
                        job['error'] = {'errors': [{'code': 'record_updated',
                            'object': job['request'].get('focus_region_name') or '原步骤提案',
                            'actual': deepcopy(reply.get('record_edit')),
                            'expected': '依据已保存的新记录修订原步骤提案',
                            'reason': '记录修订已保存，需要按更新后的记录继续判断原提案。'}], 'unchecked': []}
                        job['status'] = 'repair'
                        self.save(job)
                        continue
                    job['record_edit'] = reply.get('record_edit')
                    from regrow.traversal.proposal_revision import merge
                    candidate = merge(q, reply['proposal'])
                    if job['stage'] == 'update':
                        from regrow.traversal.object_registration import revised_request
                        job['request'] = revised_request(job['request'], previous_call)
                else:
                    candidate = reply
                fingerprint = hashlib.sha256(json.dumps([candidate, job['request'], job.get('supplements'), job.get('record_edit')], sort_keys=True).encode()).hexdigest()
                if fingerprint in job['seen']:
                    self.stop(job, '重复提交同一证据下已拒绝的提案')
                job['seen'].append(fingerprint)
                if repairing and q.get('role') == 'step_correction':
                    atomic(self.run / 'calls' / ref / 'effective_request.json', job['request'])
                    atomic(self.run / 'calls' / ref / 'effective_candidate.json', candidate)
                job.pop('rejected_reply', None)
                job.update(candidate=candidate, status='accept')
                self.save(job)
            except (ValueError, jsonschema.ValidationError) as error:
                job.update(error=diagnostic(error), status='repair', rejected_reply=deepcopy(reply))
                job['history'].append({'call': ref, 'error': diagnostic(error)})
                self.save(job)
