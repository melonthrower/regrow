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

def read(path):
    return json.loads(Path(path).read_text())

def diagnostic(error):
    if hasattr(error, 'report'):
        return error.report
    if isinstance(error, jsonschema.ValidationError):
        message = error.message
        if error.validator == 'maxItems':
            message = '数组最多允许' + str(error.validator_value) + '项，实际提交' + str(len(error.instance)) + '项；这是条目数量限制，不是文字长度限制。'
        return {'errors': [{'code': 'schema', 'path': '/' + '/'.join(map(str, error.absolute_path)),
                            'object': 'reply', 'actual': error.instance, 'expected': message,
                            'repair': '按字段格式修订，不改变真实证据。'}],
                'unchecked': ['结构尚未通过，后续语义检查未执行。']}
    return str(error)


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
    if not (job.get('control_identity_pair') or job.get('control_identity_candidates') or any((row.get('role') in ('control_identity_selection', 'control_identity_comparison') for row in history))):
        return False
    rebuilt = [i for (i, row) in enumerate(history) if row.get('framework') == 'rebuilt_stage_image_contract']
    if not rebuilt or any((row.get('framework') == 'refresh_incompatible_retained_candidate' for row in history[rebuilt[-1]:])):
        return False
    try:
        jsonschema.validate(job.get('candidate'), job['request']['response_schema'])
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
    if sent.get('role') != 'step_correction' or reply.get('resolution') != 'revise' or reply.get('blocked_by') != 'none':
        return False
    frames = sent.get('screenshots', [])
    current = evidence['current']
    return frames == [current] and job['request'].get('screenshots') == [current] and (sent.get('original_request', {}).get('screenshots') == [current]) and (reply.get('proposal') == job.get('candidate'))

def reopen_blocked(run, frame):
    """A new run may reobserve an unexecuted blocked proposal, keeping its audit."""
    from regrow.traversal import discovery_step as _discovery_step
    job = pending(run)
    if not job or job['status'] != 'blocked' or job.get('attempt'):
        return False
    if job.get('service_failure') and content_rejection(job['service_failure']['error']):
        return False
    if job['stage'] not in ('action', 'discovery', 'task_proposal', 'function_registration', 'task_result_review'):
        return False
    if any(((Path(run) / p).exists() for p in ('execution_pending.json', 'visual_navigation_pending.json'))):
        return False
    _discovery_step.await_discovery(run, str(Path(frame).resolve()), 'blocked-' + Path(job['path']).parent.name)
    job.update(status='superseded_by_observation', resume_frame=str(Path(frame).resolve()))
    atomic(Path(run) / job['path'], job)
    (Path(run) / 'pending_step.json').unlink()
    return True

def task_review_images(value):
    """A review and its saved correction retain the same validated evidence pair."""
    original = value.get('original_request', value)
    if original.get('role') not in ('task_result_review', 'observation_update'):
        return False
    from regrow.prompts.frame_context import validate
    validate(value)
    return True

def request(root, job, context):
    from regrow.records import shared_control_review as _shared_control_review
    from regrow.prompts import frame_context as _frame_context
    from regrow.runtime import model_transport as _model_transport
    from regrow.prompts import target_observation as _target_observation
    from regrow.records import action_owner_correction as _action_owner_correction
    from regrow.recognition import control_observation_repair as _control_observation_repair
    from regrow.traversal import correction_prompts as _correction_prompts
    from regrow.records import page_context as _page_context
    from regrow.recognition import matching as _visual_choices
    from regrow.recognition import control_identity_review as _control_identity_review
    if job['stage'] == 'shared_control_review':
        return _shared_control_review.correction_request(root, job)
    original = deepcopy(job['request'])
    if not task_review_images(original):
        _frame_context.select(original, _frame_context.primary(original))
    original['response_schema'] = _model_transport.expand_schema(original['response_schema'])
    if job['stage'] == 'action' and (not original.get('needs_task_inspection')):
        original = _target_observation.refresh(original)
    edit = {'type': 'object', 'properties': {n: {'type': 'string'} for n in ('region', 'control', 'field', 'before', 'after', 'evidence')}, 'required': ['region', 'control', 'field', 'before', 'after', 'evidence'], 'additionalProperties': False}
    task_edit = {'type': 'object', 'properties': {n: {'type': 'string'} for n in ('region', 'task', 'field', 'before', 'after', 'evidence')}, 'required': ['region', 'task', 'field', 'before', 'after', 'evidence'], 'additionalProperties': False}
    task_edit['properties']['field'] = {'type': 'string', 'enum': ['task_control', 'suspend_task', 'reopen_task']}
    edits = [edit] if original.get('screenshots') else []
    if edits and job['stage'] in ('discovery', 'task_proposal'):
        edits.append(task_edit)
    if edits and job['stage'] != 'action':
        if original.get('action_owner_candidates') and (not job.get('attempt')):
            edits.append(_action_owner_correction.schema())
        if original.get('control_observation_candidates'):
            edits.append(_control_observation_repair.schema())
    edit = {'anyOf': edits} if edits else {'type': 'null'}
    fields = {'blocked_by': {'type': 'string', 'enum': ['none', 'blocking_popup', 'system_error', 'unexpected_exit', 'external_app', 'control_not_visible', 'binding_conflict', 'region_ownership_review', 'shared_control_conflict', 'model_response_parse_error', 'review_required']}, 'reason': {'type': 'string'}, 'resolution': {'type': 'string', 'enum': ['revise', 'observe', 'edit_record', 'defer', 'blocked']}, 'proposal': {'anyOf': [deepcopy(original['response_schema']), {'type': 'null'}]}, 'record_edit': {'anyOf': [edit, {'type': 'array', 'items': edit}, {'type': 'null'}]}}
    if not edits:
        fields['record_edit'] = {'type': 'null'}
        fields['resolution']['enum'].remove('edit_record')
    if job['stage'] == 'object_registration':
        fields['resolution']['enum'] = ['revise', 'defer', 'blocked']
        fields['record_edit'] = {'type':'null'}
    if job['stage'] == 'update':
        proposal = fields['proposal']['anyOf'][0]['properties']
        for (obj, key) in [(proposal.get('action_result', {}), 'returns_to_previous')]:
            if obj.get('properties', {}).get(key, {}).get('type') == 'boolean':
                obj['required'] = list(dict.fromkeys(obj.get('required', []) + [key]))
    if job['stage'] == 'task_proposal':
        fields['proposal']['anyOf'][0]['properties']['operations']['items']['properties']['control'].pop('enum', None)
    schema = {'type': 'object', 'properties': fields, 'required': [name for name in fields if name != 'record_edit'], 'additionalProperties': False,
              'allOf': [{'if': {'properties': {'resolution': {'const': 'edit_record'}}, 'required':['resolution']},
                         'then': {'required':['record_edit'], 'properties':{'record_edit':{'not':{'type':'null'}}}}}]}
    dynamic = {'失败步骤': job['stage'], '原动态上下文': original['user_prompt'], '相关记录与可用能力': context, '被拒绝回复': job.get('candidate'), '上次失败或停止诊断（保留原文，非当前能力清单）': job.get('error'), '框架错误分类': job.get('blocked_by', 'none'), '执行状态': '原动作已执行；本次纠错只登记其结果，不再次投递原动作。next_action描述后续尚未执行的步骤，仍按原问题与动作后图判断；无需因本次是纠错而清空。' if job.get('attempt') else '本步骤未执行动作', '本次修复历史': job['history'], '补充观察': job.get('supplements', []), '图片说明': '前面的图片仍为原请求证据；追加图片仅用于稍后的补充观察，不能代替原动作后图。'}
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
    correction['frame_context'] = {str(frame): role['用途'] for (frame, role) in zip(frames, image_roles)}
    return _control_identity_review.attach(root, job, correction)

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

    def save(self, job):
        atomic(self.run / job['path'], job)

    def sent_request(self, job, q, ref, repairing):
        path = self.run / 'calls' / str(ref) / 'request.json'
        if path.exists():
            q = read(path)
            if not repairing:
                job['request'] = deepcopy(q)
        return q

    def repair_parse_failure(self, job):
        manifest = self.run / 'run_manifest.json'
        failed = read(manifest).get('last_call') if manifest.exists() else None
        path = self.run / 'calls' / str(failed) / 'parse_error.json'
        if not path.exists():
            return False
        detail = read(path)
        job.update(status='repair', candidate=None, blocked_by='model_response_parse_error', parse_failure={'call': failed, **detail}, error='模型回复解析错误：' + detail['reason'])
        job['history'].append({'call': failed, 'error': job['error']})
        self.save(job)
        return True

    def stop(self, job, reason):
        from regrow.traversal import task_deferral as _task_deferral
        if not isinstance(reason, str):
            reason = json.dumps(reason, ensure_ascii=False)
        decision = _task_deferral.defer(self.run, job, reason)
        if decision is not None:
            job.update(status='deferred', deferral=decision, error=reason)
            self.save(job)
            (self.run / self.pointer_name).unlink(missing_ok=True)
            raise Paused('task_deferred' if decision['next'] else 'task_blocked', reason)
        job.update(status='blocked', error=reason)
        self.save(job)
        raise Paused('correction_blocked', reason)

    def repair_unlocated(self, q, reason):
        if pending(self.run, self.pointer_name):
            raise Paused('correction_blocked', '先处理已有待修复步骤')
        key = uuid.uuid4().hex
        job = {'path': f'repair_episodes/{key}/episode.json', 'stage': 'action', 'request': deepcopy(q), 'attempt': None, 'status': 'repair', 'repairs': 0, 'observations': 0, 'history': [{'framework': reason}], 'seen': [], 'supplements': [], 'error': reason}
        self.save(job)
        atomic(self.run / self.pointer_name, {'episode': job['path']})
        return self.perform('action')

    def reject_action(self, q, candidate, ref, reason, pre_dispatch_review=None):
        if pending(self.run, self.pointer_name):
            raise Paused('correction_blocked', '已有步骤待修复')
        key = uuid.uuid4().hex
        job = {'path': f'repair_episodes/{key}/episode.json', 'stage': 'action', 'request': deepcopy(q), 'attempt': None, 'status': 'repair', 'repairs': 0, 'observations': 0, 'history': [{'call': ref, 'error': reason}], 'seen': [], 'supplements': [], 'candidate': candidate, 'call': ref, 'error': reason, 'requires_observation': True}
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
                job['status'] = 'repair' if role in ('step_correction', 'control_identity_selection', 'control_identity_comparison') else 'initial'
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
            if job['stage'] in ('action', 'task_proposal', 'function_registration', 'task_result_review'):
                self.stop(job, reason)
        if self.available() < 1:
            raise Paused('repair_pending', '本轮调用额度已用完；下一轮继续原纠错请求')
        decision = _branch_switch.correct(self, job)
        if decision:
            raise Paused('ready_next_round' if decision.get('resumed') else 'task_deferred', '纠错已解决本次循环判断；重新发现后按新办法继续' if decision.get('resumed') else '纠错已暂挂当前分支；重新发现后继续独立区块')
        raise Paused('correction_blocked', '当前分支未切换；保留未完成记录')

    def perform(self, stage, q=None, attempt=None):
        from regrow.records import shared_control_review as _shared_control_review
        from regrow.prompts import history_disclosure as _history_disclosure
        from regrow.traversal import result_updater as _result_updater
        from regrow.traversal import correction_crop_feedback as _correction_crop_feedback
        from regrow.traversal import region_functions as _region_functions
        from regrow.records import update_semantic_review as _update_semantic_review
        from regrow.recognition import ownership_review as _ownership_review
        from regrow.runtime import model_transport as _model_transport
        from regrow.recognition import control_identity_review as _control_identity_review
        from regrow.records import registration_diagnostics as _registration_diagnostics
        job = pending(self.run, self.pointer_name)
        if job is None:
            if stage in ('action', 'task_proposal', 'function_registration', 'task_result_review'):
                _shared_control_review.run_pending(self)
            key = uuid.uuid4().hex
            job = {'path': f'repair_episodes/{key}/episode.json', 'stage': stage, 'request': deepcopy(q), 'attempt': attempt, 'status': 'initial', 'repairs': 0, 'observations': 0, 'history': [], 'seen': [], 'supplements': []}
            if stage == 'shared_control_review':
                job.update(status='repair', blocked_by='shared_control_conflict', error='共享关系有实际结果冲突，请核对共享范围')
            self.save(job)
            atomic(self.run / self.pointer_name, {'episode': job['path']})
        elif stage != job['stage']:
            raise Paused('correction_blocked', '必须先处理尚未完成的步骤：' + job['stage'])
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
                rebuilt = request(self.root, job, self.adapters.context(self.run, job)) if job['status'] == 'repair' else deepcopy(fresh)
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
        if job['stage'] == 'function_registration' and support_review_eligible(job.get('error')) and job.get('status') in ('repair', 'blocked') and (not job.get('attempt')) and (not (self.run / 'execution_pending.json').exists()) and (not (job.get('service_failure') or job.get('service_retry_request'))):
            rid = job['request'].get('source', {}).get('region')
            if _region_functions.request_support_review(self.run, rid, job.get('call')):
                job.update(status='superseded_by_support_review')
                self.save(job)
                (self.run / self.pointer_name).unlink(missing_ok=True)
                raise Paused('ready_next_round', '功能缺少任务依据，返回任务提出步骤补充仅观察记录；未新增GUI动作')
        if job.get('service_failure') and (not content_rejection(job['service_failure']['error'])):
            self.switch_branch(job)
        if job.get('service_failure') and job['stage'] == 'function_registration':
            self.stop(job, '模型服务失败，仅暂挂本区块的功能整理；其他探索可继续，原请求与错误保留')
        if job.get('service_failure') or job.get('switch_trigger'):
            self.switch_branch(job)
        if job['status'] == 'blocked':
            if job.get('suspended_recovery'):
                raise Paused('historical_update_conflict', job['error'])
            last = read(self.run / 'calls' / job['call'] / 'response.json') if job.get('call') else {}
            if last.get('resolution') == 'edit_record' and self.adapters.edit_proposal(self.run, job, last.get('record_edit')):
                self.save(job)
            else:
                self.stop(job, job['error'])
        if job['status'] == 'deferred':
            (self.run / self.pointer_name).unlink(missing_ok=True)
            raise Paused('task_deferred' if job['deferral']['next'] else 'task_blocked', job['error'])
        while True:
            if job['status'] == 'complete':
                (self.run / self.pointer_name).unlink(missing_ok=True)
                return job
            if job['status'] == 'observe':
                if self.available() < 1:
                    raise Paused('repair_pending', '等待下一轮额度补观察')
                try:
                    self.adapters.observe(self, job)
                    if job['stage'] == 'action' and job['request'].get('action_ready'):
                        job['status'] = 'initial'
                        self.save(job)
                        continue
                except subprocess.CalledProcessError:
                    if not self.repair_parse_failure(job):
                        raise
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
                    from regrow.traversal.object_registration import complete as complete_objects
                    complete_objects(self, job)
                    result = self.adapters.accept(self.root, self.run, job)
                except (ValueError, jsonschema.ValidationError) as error:
                    if job['stage'] == 'action' and getattr(error, 'refresh_request', False):
                        try:
                            refreshed = self.adapters.refresh(self.root, self.run, job)
                        except (ValueError, jsonschema.ValidationError) as refresh_error:
                            error = refresh_error
                        else:
                            job['history'].append({'call': job['call'], 'error': diagnostic(error), 'resolution': 'refresh_original_task'})
                            job.update(request=refreshed, status='initial', candidate=None, record_edit=None)
                            self.save(job)
                            continue
                    if job['stage'] == 'function_registration' and support_review_eligible(error) and (not job.get('attempt')) and _region_functions.request_support_review(self.run, job['request'].get('source', {}).get('region'), job.get('call')):
                        job.update(status='superseded_by_support_review', error=diagnostic(error))
                        self.save(job)
                        (self.run / self.pointer_name).unlink(missing_ok=True)
                        raise Paused('ready_next_round', '功能缺少任务依据，返回任务提出步骤补充仅观察记录')
                    if _ownership_review.begin(self.run, job, diagnostic(error)):
                        raise Paused('repair_pending', '区块归属需实地复查；原记录与提案已保存')
                    if getattr(error, 'defer_task', False):
                        self.stop(job, str(error))
                    if getattr(error, 'blocked_by', None):
                        job['blocked_by'] = error.blocked_by
                    if getattr(error, 'control_identity_pair', None):
                        job['control_identity_pair'] = error.control_identity_pair
                    if getattr(error, 'control_identity_candidates', None):
                        job['control_identity_candidates'] = error.control_identity_candidates
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
                q = request(self.root, job, self.adapters.context(self.run, job))
                _correction_crop_feedback.attach(self.run, job, q)
                job['repairs'] += 1
                self.save(job)
            else:
                q = job['request']
            try:
                (ref, reply) = self.call(q)
            except subprocess.CalledProcessError:
                manifest = Path(self.run) / 'run_manifest.json'
                failed = read(manifest).get('last_call') if manifest.exists() else None
                folder = Path(self.run) / 'calls' / str(failed)
                q = self.sent_request(job, q, failed, repairing)
                if self.repair_parse_failure(job):
                    continue
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
                if job['stage'] == 'function_registration':
                    self.stop(job, '模型服务失败，仅暂挂功能整理，其他探索继续')
                self.switch_branch(job)
            q = self.sent_request(job, q, ref, repairing)
            if q.get('role') not in ('control_identity_comparison', 'control_identity_selection'):
                job.pop('registration_submission', None)
            job['call'] = ref
            job['history'].append({'call': ref, 'role': q.get('role')})
            try:
                if repairing:
                    if q.get('role') == 'control_identity_selection':
                        pair = _control_identity_review.selected_pair(q, reply)
                        if pair is None:
                            self.stop(job, '当前场景无法选定历史控件：' + reply['reason'])
                        job['control_identity_pair'] = pair
                        job.pop('control_identity_candidates', None)
                        job['history'].append({'call': ref, 'identity_candidate': reply['candidate'], 'reason': reply['reason']})
                        job['repairs'] = max(0, job['repairs'] - 1)
                        job.update(status='repair', error='已按场景选定一个候选；现在仅核对这一对原场景，不直接登记身份')
                        self.save(job)
                        continue
                    if q.get('role') == 'control_identity_comparison':
                        (reviewed, candidate) = _control_identity_review.compared_candidate(q, reply)
                        if candidate is None:
                            self.stop(job, '身份比较仍未确认：' + reply['reason'])
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
                            job.update(status='repair', error='该旧控件复用已被否定。请修正本次对象登记及相关任务知识、jump_to和下一步：旧对象未出现则撤回引用；当前为新对象则不填index并补充资料；不要把新对象作用继续写到旧控件。依据：' + reply['reason'])
                        self.save(job)
                        continue
                    repeated = reply.get('proposal') if isinstance(reply, dict) else None
                    if repeated is not None and (not q.get('control_identity_pair')):
                        check = hashlib.sha256(json.dumps([repeated, job['request'], job.get('supplements'), reply.get('record_edit')], sort_keys=True).encode()).hexdigest()
                        if check in job['seen']:
                            self.stop(job, '重复提交同一证据下已拒绝的提案')
                    if job['stage'] == 'shared_control_review':
                        job['last_shared_reply'] = deepcopy(reply)
                    _registration_diagnostics.check('correction', {'response_schema': q['response_schema'], 'original_stage': job['stage']}, reply, {})
                    resolution = reply['resolution']
                    job['blocked_by'] = reply['blocked_by']
                    if not reply['reason'].strip():
                        raise ValueError('需要说明修复依据')
                    if resolution != 'revise' and reply['proposal'] is not None:
                        raise ValueError(f'resolution={resolution}要求proposal=null；保留你的修复方式，将proposal改为null，观察对象或原因写在reason。动作none也属于提案，不能代替null。')
                    if resolution == 'revise' and reply['proposal'] is None:
                        raise ValueError('resolution=revise需要完整proposal；若需要补观察应选择observe并保持proposal=null。')
                    if resolution == 'edit_record' and reply.get('record_edit') is None:
                        raise ValueError('resolution=edit_record需要record_edit说明具体修订。')
                    if resolution not in ('revise', 'edit_record') and reply.get('record_edit') is not None:
                        raise ValueError(f'resolution={resolution}要求record_edit=null；保留修复方式，不混入记录修订。')
                    if resolution in ('blocked', 'defer'):
                        job['blocked_by'] = reply['blocked_by']
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
                        if job['stage'] == 'shared_control_review':
                            job.update(status='complete', result={'record_edit': reply.get('record_edit'), 'resolution': 'shared_relation_reviewed'})
                            self.save(job)
                            continue
                        job['request'] = self.adapters.refresh(self.root, self.run, job)
                        job['error'] = '记录修订已保存；请依据新记录修正原步骤提案'
                        job['status'] = 'repair'
                        self.save(job)
                        continue
                    job['record_edit'] = reply.get('record_edit')
                    candidate = reply['proposal']
                else:
                    candidate = reply
                fingerprint = hashlib.sha256(json.dumps([candidate, job['request'], job.get('supplements'), job.get('record_edit')], sort_keys=True).encode()).hexdigest()
                if fingerprint in job['seen']:
                    self.stop(job, '重复提交同一证据下已拒绝的提案')
                job['seen'].append(fingerprint)
                job.update(candidate=candidate, status='accept')
                self.save(job)
            except (ValueError, jsonschema.ValidationError) as error:
                job.update(error=diagnostic(error), status='repair')
                self.save(job)
