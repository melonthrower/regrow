"""Facts produced by validators and required before asking for a corrected reply."""
from copy import deepcopy
import json


class Rejected(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__(json.dumps(report, ensure_ascii=False))


def reject(code, subject, actual, expected, *, path='', field=None, reason=None, repair=None):
    item = {'code': code, 'object': subject, 'path': path,
            'actual': actual, 'expected': expected}
    for key, value in [('field', field), ('reason', reason), ('repair', repair)]:
        if value:
            item[key] = value
    raise Rejected({'errors': [item], 'unchecked': []})


def diagnostic(error):
    """Keep unexplained exceptions in local records, never turn them into advice."""
    if hasattr(error, 'report'):
        return deepcopy(error.report)
    import jsonschema
    if isinstance(error, jsonschema.ValidationError):
        from regrow.records.registration_diagnostics import schema_errors
        return {'errors': schema_errors(error),
                'unchecked': ['结构尚未通过，后续语义检查未执行。']}
    return str(error)


class DiagnosticUnavailable(RuntimeError):
    status = 'framework_diagnostic_missing'

    def __init__(self, value, missing):
        self.reason = ('框架校验未提供完整纠错依据：' + '、'.join(dict.fromkeys(missing))
                       + '。停止自动重答，保留原请求、回复和已执行动作的结果。')
        self.detail = {'missing': list(dict.fromkeys(missing)),
                       'diagnostic': diagnostic(value) if isinstance(value, BaseException) else deepcopy(value)}
        super().__init__(self.reason)


_MISSING = object()


def _value_at(reply, path):
    value = reply
    for token in path.strip('/').split('/') if path else []:
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            return _MISSING
    return value


def require_report(value, reply=None):
    """Admit explicit failed facts; never infer business causes from a string."""
    report = diagnostic(value) if isinstance(value, BaseException) else deepcopy(value)
    if not isinstance(report, dict) or not isinstance(report.get('errors'), list) or not report['errors']:
        raise DiagnosticUnavailable(value, ['具体对象或字段', '实际内容', '未满足的条件'])
    missing = []
    for item in report['errors']:
        if not isinstance(item, dict):
            missing.append('结构化失败事实')
            continue
        if not item.get('code'):
            missing.append('失败类型')
        if ('expected' not in item or item['expected'] == '') and not item.get('reason'):
            missing.append('未满足的条件')
        path = item.get('path')
        whole_reply = item.get('code') == 'parse' or item.get('validator') and path in ('', '/')
        if not item.get('object') and not path and not whole_reply:
            missing.append('具体对象或字段')
        if 'actual' not in item:
            actual = _value_at(reply, path) if path else _MISSING
            if actual is _MISSING and isinstance(reply, dict) and isinstance(reply.get('proposal'), dict) and path:
                actual = _value_at(reply['proposal'], path)
            if actual is _MISSING and whole_reply:
                actual = reply
            if actual is _MISSING:
                missing.append('实际内容')
            else:
                item['actual'] = deepcopy(actual)
        if whole_reply:
            item.setdefault('object', '整份回复')
    if missing:
        raise DiagnosticUnavailable(value, missing)
    return report
