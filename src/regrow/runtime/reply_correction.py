"""One format-retry loop for every model role, before business acceptance."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import subprocess
import jsonschema
from regrow.records.snapshots import read, write_json
from regrow.runtime.model_transport import BudgetExhausted

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
    from regrow.prompts.correction_feedback import describe
    part = load(root, ['纠错/原格式重答.prompt'])[0]
    q = deepcopy(original)
    if not any(p['path'] == part['path'] for p in q.get('fixed_parts', [])):
        q['fixed_parts'] = [*q.get('fixed_parts', []), part]
        q['system_prompt'] += '\n\n' + part['text']
    feedback = {'本次格式问题': describe(report, rejected, q), '最新失败回复': rejected}
    q['user_prompt'] = original['user_prompt'] + '\n\n## 修正回复格式\n' + json.dumps(feedback, ensure_ascii=False, indent=2)
    q['dynamic_prompt'] = q['user_prompt']
    q['format_original_call'] = first_call
    for key in ('_structured_user_prompt', '_presentation_digest'):
        q.pop(key, None)
    return q


def call(transport, incoming):
    from regrow.runtime.model_transport import prepare_request
    from regrow.records.registration_diagnostics import schema_errors
    pointer = transport.run / 'pending_format_reply.json'
    if pointer.exists():
        state = read(pointer)
        if all(incoming != state[key] for key in ('input', 'original', 'next')):
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
            report = {'errors': [{'code': 'parse', 'expected': '回复无法解析为唯一JSON对象：' + detail['reason']}], 'unchecked': []}
        else:
            errors = []
            for failure in jsonschema.Draft202012Validator(q['response_schema']).iter_errors(reply):
                for row in schema_errors(failure):
                    if row not in errors:
                        errors.append(row)
            if not errors:
                pointer.unlink(missing_ok=True)
                return ref, reply
            report = {'errors': errors, 'unchecked': ['格式尚未通过，业务语义检查尚未执行。']}
        write_json(transport.run / 'calls' / ref / 'format_errors.json', report)
        state['first_call'] = state['first_call'] or ref
        state.update(last_call=ref, error=report, charged=False)
        state['next'] = request(transport.root, state['original'], reply, report, state['first_call'])
        write_json(pointer, state)
