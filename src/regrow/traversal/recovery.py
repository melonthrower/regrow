"""One recovery policy; action payload is shared with ordinary exploration."""
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_tasks
from copy import deepcopy
import json
import jsonschema
EXCEPTIONS = ['none', 'blocking_popup', 'system_error', 'unexpected_exit', 'external_app', 'unclassified']

def schema():
    from regrow.runtime import action_commands as _action_commands
    return {'type': 'object', 'properties': {'exception': {'type': 'string', 'enum': EXCEPTIONS}, 'decision': {'type': 'string', 'enum': ['act', 'resume_exploration', 'stop']}, 'action': {'anyOf': [_action_commands.execution_schema(), {'type': 'null'}]}, 'framework_tool': {'type': ['string', 'null'], 'enum': [None, 'restart_app']}, 'reason': {'type': 'string'}, 'handoff': {'type': 'string'}}, 'required': ['exception', 'decision', 'action', 'framework_tool', 'reason', 'handoff'], 'additionalProperties': False}

def action_defaults(reply):
    return deepcopy(reply)

def validate(reply, platform='android'):
    from regrow.runtime import action_commands as _action_commands
    reply = action_defaults(reply)
    jsonschema.validate(reply, schema())
    (action, tool) = (reply['action'], reply['framework_tool'])
    if action:
        action = _action_commands.normalize(action)
    if action:
        _action_commands.validate(action, platform)
        if action.get('task_update'):
            raise ValueError('恢复动作不修改普通探索任务')
    if reply['decision'] == 'act':
        if bool(action) == bool(tool):
            raise ValueError('choose one action or framework tool')
        if action and action['action'] == 'none':
            raise ValueError('act requires an actual action')
        if tool and reply['exception'] not in ('external_app', 'unexpected_exit'):
            raise ValueError('restart not appropriate for this exception')
    elif action or tool:
        raise ValueError('flow decision must not carry an action')
    if reply['decision'] == 'resume_exploration' and reply['exception'] not in ('none', 'blocking_popup'):
        raise ValueError('cannot resume outside the target app or with unclassified obstruction')

def resolve(reply, platform='android'):
    """A cleared exception ends recovery; normal app navigation is not recovery."""
    from regrow.runtime import action_commands as _action_commands
    reply = action_defaults(reply)
    jsonschema.validate(reply, schema())
    result = dict(reply)
    if result['exception'] == 'none':
        result.update(decision='resume_exploration', action=None, framework_tool=None, handoff=reply['handoff'] + '\n恢复观察：当前异常已消失；原探索问题尚未复核，建议中的后续动作尚未执行。')
    validate(result, platform)
    if result.get('action'):
        result['action'] = _action_commands.normalize(result['action'])
    return result

def interrupted_tasks(records, state):
    """Recover task ownership from the triggering attempt after active_task clears."""
    attempt = state.get('attempt')
    if not attempt:
        return []
    return [{'区块': region['name'], '任务': name, '任务依据与范围': task.get('reason', ''), '状态': task.get('status'), '结果依据': task_value(task, 'result_evidence', ''), '触发动作': attempt} for region in records.values() for (name, task) in owned_tasks(region).items() if attempt in task_value(task, 'attempts', [])]

def build_request(root, episode, app, region_name, trigger_result, screenshot):
    from regrow.prompts.compose import parts as rule_parts
    parts = rule_parts(root, 'recovery')
    text = '\n\n'.join((p['text'] for p in parts))
    dynamic = {'目标应用': app, '平台': 'Android触屏，不支持hover', '中断的工作区块': region_name, '触发异常的结果': trigger_result, '异常交接': episode.get('handoff', ''), '重启工具状态': '本次已使用；不要再次请求，结合截图和启动回执选择其他恢复动作' if any((a.get('framework_tool') == 'restart_app' for a in episode['actions'])) else '尚未使用；仅目标应用退出或应用外时可请求', '框架反馈': episode.get('framework_feedback', ''), '本次恢复历史': episode['actions']}
    if episode.get('interrupted_tasks'):
        dynamic['中断任务（原记录，不代表新增授权）'] = deepcopy(episode['interrupted_tasks'])
    request = {'role': 'recovery', 'stage': 'recovery_action', 'system_prompt': text, 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [screenshot], 'response_schema': schema(), 'fixed_parts': parts}
    from regrow.prompts.frame_context import label
    return label(request, screenshot, '本次恢复观察图，用于核对上一步结果')

def restart_commands(package, component):
    if not component or not component.startswith(package + '/'):
        raise ValueError('invalid restart component')
    return [['shell', 'am', 'force-stop', package], ['shell', 'am', 'start', '-W', '-n', component]]
