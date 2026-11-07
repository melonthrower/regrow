"""One format-retry loop for every model role, before business acceptance."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import subprocess
import jsonschema
from regrow.records.snapshots import read, write_json
from regrow.runtime.model_transport import BudgetExhausted
from regrow.records.diagnostics import DiagnosticUnavailable

_BUDGET = ContextVar('reply_correction_budget', default=None)


@contextmanager
def budget(remaining, consume):
    """A stage can lend its existing repair allowance without exposing it to Luna."""
    token = _BUDGET.set((remaining, consume))
    try:
        yield
    finally:
        _BUDGET.reset(token)


class Failed(ValueError):
    status = 'correction_blocked'
    def __init__(self, state):
        self.state = state
        self.reason = '格式修正次数已用完；原请求和失败回复已保存'
        super().__init__(self.reason)


class Pending(BudgetExhausted):
    def __init__(self, state, *, different_request=False):
        self.state = state
        self.different_request = different_request
        super().__init__('格式重答尚未完成，保留原调用继续；不能切换到其他请求')


def abandon(run, reason):
    """A business deferral ends this retry; keep its evidence at the failed call."""
    pointer = run / 'pending_format_reply.json'
    if pointer.exists():
        state = read(pointer)
        write_json(run / 'calls' / state['last_call'] / 'format_deferred.json',
                   {**state, 'deferral_reason': reason})
        pointer.unlink()


def request(root, original, rejected, report, first_call):
    from regrow.prompts.compose import load
    from regrow.prompts.correction_feedback import describe, organize
    from regrow.prompts.field_placeholders import fill_missing, without_full_format
    part = load(root, ['纠错/原格式重答.prompt'])[0]
    q = without_full_format(original)
    q = organize(root, q, part, describe(report, rejected, q),
                 fill_missing(root, rejected, report, original['response_schema']), report=report)
    q['_correction_context']['reply_is_wire'] = True
    q['format_original_call'] = first_call
    for key in ('_structured_user_prompt', '_presentation_digest'):
        q.pop(key, None)
    from regrow.prompts.correction_fields import prepare as marked_fields
    return marked_fields(root, q)


def call(transport, incoming):
    from regrow.runtime.model_transport import prepare_request
    from regrow.records.registration_diagnostics import reply_errors
    pointer = transport.run / 'pending_format_reply.json'
    if pointer.exists():
        state = read(pointer)
        if state.get('diagnostic_failure'):
            failure = state['diagnostic_failure']
            error = DiagnosticUnavailable(failure.get('diagnostic'), failure['missing'])
            error.detail.update(failure)
            raise error
        from regrow.recognition.named_references import internal_request
        same_internal = incoming == internal_request(state['original'])
        if not same_internal and all(incoming != state[key] for key in ('input', 'original', 'next')):
            raise Pending(state, different_request=True)
    else:
        prepared = prepare_request(transport.root, transport.run, incoming, getattr(transport, 'platform', 'android'))
        state = {'input': deepcopy(incoming), 'original': prepared, 'next': prepared,
                 'retries': 0, 'first_call': None, 'charged': False}
    while True:
        if transport.account['http_started'] >= transport.account['max_http']:
            if state['first_call'] is not None:
                write_json(pointer, state)
                raise Pending(state)
            raise BudgetExhausted('HTTP budget exhausted')
        if state['first_call'] is not None and not state['charged']:
            shared = _BUDGET.get()
            if state['retries'] >= 2 or shared and shared[0]() <= 0:
                write_json(transport.run / 'calls' / state['last_call'] / 'format_failure.json', state)
                pointer.unlink(missing_ok=True)
                raise Failed(state)
            if shared:
                shared[1]()
            state['retries'] += 1
            state['charged'] = True
            write_json(pointer, state)
        q = state['next']
        try:
            ref, reply = transport._call_once(q)
        except subprocess.CalledProcessError:
            ref = read(transport.run / 'run_manifest.json')['last_call']
            parse_error = transport.run / 'calls' / ref / 'parse_error.json'
            if not parse_error.exists():
                raise
            detail = read(parse_error)
            reply = detail.get('reply_texts', [])
            report = {'errors': detail.get('errors') or [{'code': 'parse', 'object': '整份回复', 'actual': reply,
                      'expected': '回复须为唯一JSON对象',
                      'reason': '回复无法解析为唯一JSON对象：' + detail['reason']}], 'unchecked': []}
        else:
            from regrow.recognition.named_references import normalize_reply
            from regrow.runtime.model_transport import expand_schema
            if q.get('name_contract'):
                reply = normalize_reply(expand_schema(q['response_schema']), reply)
            recovery = transport.run / 'calls' / ref / 'structure_recovery.json'
            errors = (read(recovery).get('errors', []) if recovery.exists() else [])
            errors += reply_errors(q, reply, defer_objects=True)
            if not errors:
                from regrow.recognition.named_references import decode, internal_request
                try:
                    derived = decode(q, reply)
                except ValueError as error:
                    details = getattr(error, 'report', None)
                    errors.extend(details['errors'] if isinstance(details, dict) and details.get('errors')
                                  else [{'code': 'object_reference', 'raw_error': str(error)}])
                else:
                    pointer.unlink(missing_ok=True)
                    if q.get('name_contract'):
                        write_json(transport.run / 'calls' / ref / 'interpreted_request.json', internal_request(state['original'], reply))
                        write_json(transport.run / 'calls' / ref / 'interpreted_response.json', derived)
                    return ref, derived
            report = {'errors': errors, 'unchecked': ['格式尚未通过，业务语义检查尚未执行。']}
        write_json(transport.run / 'calls' / ref / 'format_errors.json', report)
        state['first_call'] = state['first_call'] or ref
        state.update(last_call=ref, error=report, charged=False)
        raw = transport.run / 'calls' / ref / 'unfiltered_response.json'
        rejected = read(raw) if raw.exists() else reply
        try:
            state['next'] = request(transport.root, state['original'], rejected, report, state['first_call'])
        except DiagnosticUnavailable as error:
            error.detail['call'] = ref
            state['diagnostic_failure'] = error.detail
            write_json(pointer, state)
            raise
        write_json(pointer, state)
