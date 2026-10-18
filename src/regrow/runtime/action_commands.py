from regrow.paths import SOURCE_ROOT
'Shared Android action contract for exploration and recovery.\n\nNames follow the original traversal contract; ADB performs platform translation.\nOld tap evidence is readable, but new requests advertise click.\n'
import json
from pathlib import Path
import shlex
import time
ANDROID_ACTIONS = ('click', 'double_click', 'long_press', 'input_text', 'scroll', 'back', 'wait', 'none', 'key_press')
ACTIONS = ANDROID_ACTIONS + ('hotkey', 'hover', 'right_click', 'drag')

def schema():
    from regrow.records.task_updates import schema as update_schema
    from regrow.records.task_updates import object_schema
    result = json.loads((SOURCE_ROOT / 'regrow/prompts/输出格式/选择探索入口.schema').read_text())
    result['properties']['operation']['anyOf'].append(object_schema({'action': {'type': 'string', 'enum': ['none']}, 'task_update': update_schema()}))
    return result

def selection_schema(value):
    """Luna selects action fields directly; normalize owns execution defaults."""
    from copy import deepcopy
    from regrow.runtime.model_transport import expand_schema
    expanded = expand_schema(value)
    result = deepcopy(expanded.get('properties', {}).get('operation', expanded))
    result.setdefault('type', 'object')
    for branch in result.get('anyOf', []):
        actions = branch.get('properties', {}).get('action', {}).get('enum', [])
        if actions and set(actions) <= {'back', 'wait', 'key_press', 'hotkey'}:
            branch['required'] = [field for field in branch.get('required', []) if field != 'target']
    if not any(('complete' in b.get('properties', {}).get('action', {}).get('enum', []) for b in result.get('anyOf', []))):
        for branch in result.get('anyOf', []):
            update = branch.get('properties', {}).get('task_update')
            if not update:
                continue
            choices = update['properties']['decision']['enum']
            if 'answered' not in choices:
                continue
            products = {name: deepcopy(value) for (name, value) in update['properties'].items() if name in ('knowledge', 'findings', 'entry')}
            result['anyOf'].append({'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['complete']}, 'reason': deepcopy(update['properties']['reason']), **products}, 'required': ['action', 'reason'] + [name for name in products if name in update.get('required', [])], 'additionalProperties': False})
            update['properties']['decision']['enum'] = [c for c in choices if c != 'answered']
            break
    # Keep partial answers and explicit deferral in the same flat reply.
    completion = next((b['properties'] for b in result.get('anyOf', []) if 'complete' in b.get('properties', {}).get('action', {}).get('enum', [])), None)
    if completion is not None:
        for branch in result['anyOf']:
            props = branch.get('properties', {})
            if 'none' in props.get('action', {}).get('enum', []) and 'reason' in props:
                props.update({k: deepcopy(v) for k, v in completion.items() if k in ('knowledge', 'findings', 'entry')})
                props['retry_when'] = {'type':'string','minLength':1}
    result['anyOf'] = [branch for branch in result.get('anyOf', []) if 'task_update' not in branch.get('properties', {})]
    return result

def for_request(proposal, request):
    """Map a validated public reply to the existing settlement path, without editing it."""
    completed = proposal.get('action') == 'complete'
    partial = proposal.get('action') == 'none' and any(k in proposal for k in ('knowledge','findings','entry','retry_when'))
    if not completed and not partial:
        return proposal
    from copy import deepcopy
    source = request.get('source', {})
    owner = source.get('task_region')
    name = source.get('task_name')
    if not owner or not name:
        raise ValueError('答案或暂挂判断需要本次请求绑定的原探索任务')
    update = {'task': owner + '/' + name, 'decision': 'answered' if completed else 'defer' if proposal.get('retry_when') else 'continue', 'reason': proposal['reason']}
    if not completed:
        update['remaining_question'] = proposal['reason']
    if proposal.get('retry_when'):
        update['retry_when'] = proposal['retry_when']
    update.update({key: deepcopy(proposal[key]) for key in ('knowledge', 'findings', 'entry') if key in proposal})
    return {'action': 'none', 'task_update': update}

def execution_schema():
    """Recovery and ownership review can propose actions, not task settlement."""
    result = schema()
    result['properties']['operation']['anyOf'] = [b for b in result['properties']['operation']['anyOf'] if 'none' not in b['properties']['action']['enum']]
    return result

def platform_request(request, platform):
    from copy import deepcopy
    q = deepcopy(request)
    q['platform'] = platform

    def restrict(node):
        if isinstance(node, dict):
            if platform == 'android':
                allowed = set(ANDROID_ACTIONS) | {'complete'}
                action = node.get('properties', {}).get('action', {})
                if 'enum' in action:
                    action['enum'] = [v for v in action['enum'] if v in allowed]
                if 'anyOf' in node:
                    node['anyOf'] = [b for b in node['anyOf'] if not ('enum' in b.get('properties', {}).get('action', {}) and (not set(b['properties']['action']['enum']).intersection(allowed)))]
            for child in node.values():
                restrict(child)
        elif isinstance(node, list):
            for child in node:
                restrict(child)
    restrict(q.get('response_schema', {}))
    return q

def normalize(proposal):
    proposal = proposal.get('operation', proposal)
    p = {**proposal, 'action': {'tap': 'click'}.get(proposal['action'], proposal['action'])}
    if p.get('task_update'):
        p.setdefault('reason', p['task_update']['reason'])
        p.setdefault('target', p['task_update']['task'])
    p.setdefault('target', '当前工作')
    if p['action'] == 'back':
        p['target'] = '系统返回'
    if p['action'] not in ('input_text', 'key_press', 'hotkey'):
        p['text'] = None
    if p['action'] not in ('scroll', 'drag'):
        p.update(end_x=None, end_y=None)
    if p['action'] in ('back', 'wait', 'none', 'key_press', 'hotkey'):
        p.update(x=None, y=None)
    return p

def validate(proposal, platform='android'):
    import jsonschema
    if proposal.get('request_task_review'):
        raise ValueError('使用共同task_update提交明确判断')
    if 'operation' in proposal:
        jsonschema.validate(proposal, schema())
    normalized = normalize(proposal)
    if normalized.get('task_update') and normalized['action'] != 'none':
        raise ValueError('任务判断不能冒充已执行动作')
    commands(normalized, platform)

def commands(proposal, platform='android'):
    proposal = normalize(proposal)
    if platform == 'desktop':
        from regrow.runtime.desktop_transport import commands as desktop_commands
        return desktop_commands(proposal)
    p = normalize(proposal)
    kind = p['action']
    if kind not in ANDROID_ACTIONS:
        raise ValueError('unsupported Android action: ' + kind)
    if kind == 'key_press':
        keys = {'ENTER': '66', 'TAB': '61', 'ESC': '111', 'BACKSPACE': '67'}
        if p.get('text') not in keys:
            raise ValueError('key_press text must be ENTER, TAB, ESC or BACKSPACE')
        return [['shell', 'input', 'keyevent', keys[p['text']]]]
    if kind == 'back':
        return [['shell', 'input', 'keyevent', '4']]
    if kind in ('wait', 'none'):
        return []
    (x, y) = (p.get('x'), p.get('y'))
    if type(x) is not int or type(y) is not int or min(x, y) < 0:
        raise ValueError('action needs valid coordinates')
    tap = ['shell', 'input', 'tap', str(x), str(y)]
    if kind == 'click':
        return [tap]
    if kind == 'double_click':
        return [tap, tap]
    if kind == 'long_press':
        return [['shell', 'input', 'swipe', str(x), str(y), str(x), str(y), '800']]
    if kind == 'scroll':
        (ex, ey) = (p.get('end_x'), p.get('end_y'))
        if type(ex) is not int or type(ey) is not int or min(ex, ey) < 0 or ((x, y) == (ex, ey)):
            raise ValueError('invalid scroll endpoints')
        return [['shell', 'input', 'swipe', str(x), str(y), str(ex), str(ey), '500']]
    text = p.get('text')
    if not isinstance(text, str) or any((ord(c) > 127 or ord(c) < 32 for c in text)):
        raise ValueError('Android adapter supports printable ASCII input only; do not deliver partial text')
    replacement = ['shell', 'input', 'text', shlex.quote(text.replace(' ', '%s'))] if text else ['shell', 'input', 'keyevent', '67']
    return [tap, ['shell', 'input', 'keycombination', '113', '29'], replacement]

def execute(transport, proposal, folder, *, input_context=None):
    """Shared receipts and command accounting; delivery is never semantic success."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    platform = getattr(transport, 'platform', 'android')
    argv = commands(proposal, platform)
    from regrow.runtime.model_transport import BudgetExhausted
    if transport.account['gui_started'] + len(argv) > transport.account['max_gui_commands']:
        raise BudgetExhausted('GUI command budget exhausted')

    def save(name, data):
        (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    save('dispatch.json', {'action': proposal, 'commands': argv, 'status': 'dispatching'})
    if input_context is not None:
        save('input_context.json', input_context)
    receipts = []
    steps = []
    target = None

    def send(command, step):
        if transport.account['gui_started'] >= transport.account['max_gui_commands']:
            raise BudgetExhausted('GUI command budget exhausted')
        transport.account['gui_started'] += 1
        transport.save()
        save('pending_command.json', {'command': command, 'step': step})
        try:
            result = transport.send_command(command) if platform == 'desktop' else transport.adb(command)
            receipt = {'exit_code': result.returncode, 'stdout': result.stdout.decode(), 'stderr': result.stderr.decode()}
        except BaseException:
            save('receipt.json', {'exit_code': None, 'semantic_result': 'unverified', 'executed_steps': steps})
            raise
        receipts.append(receipt)
        save('command_receipts.json', receipts)
        if receipt['exit_code'] == 0:
            steps.append(step)
        save('executed_steps.json', steps)
        return receipt

    def finish(delivered=None, description=''):
        receipt = {**(receipts[-1] if receipts else {'exit_code': 0}), 'semantic_result': 'unverified', 'executed_steps': steps}
        if delivered is not None:
            receipt['text_delivered'] = delivered
            receipt['input_mode'] = 'replace'
            if not delivered and receipt['exit_code'] == 0:
                receipt.update(semantic_result='focus_changed_surface', description=description)
        if target:
            receipt['input_target'] = target
        save('receipt.json', receipt)
        return receipt
    if proposal['action'] != 'input_text':
        if proposal['action'] == 'wait':
            time.sleep(2)
            steps.append({'action': 'wait', 'seconds': 2})
            save('executed_steps.json', steps)
        for command in argv:
            if send(command, dict(proposal))['exit_code'] != 0:
                break
        return finish()
    transport.screenshot(folder / 'before_focus.png')
    if send(argv[0], {'action': 'click', 'x': proposal['x'], 'y': proposal['y']})['exit_code'] != 0:
        return finish(False)
    time.sleep(2)
    transport.screenshot(folder / 'after_focus.png')
    if input_context is None:
        from regrow.recognition.visual_backtrack import same_surface
        decision = {'status': 'same_surface' if same_surface(folder / 'before_focus.png', folder / 'after_focus.png') else 'unresolved', 'reason': '无区块控件证据，采用整图保守核验'}
    else:
        from regrow.runtime.input_target import resolve
        decision = resolve(input_context, folder / 'before_focus.png', folder / 'after_focus.png')
    save('focus_check.json', decision)
    if decision['status'] not in ('same_target', 'same_surface'):
        return finish(False, '实际点击已保存；输入对象未可靠确认，尚未发送文字，交回发现与更新流程')
    target = decision.get('target', target)
    if send(argv[1], {'action': 'select_all', 'method': 'CTRL+A'})['exit_code'] != 0:
        return finish(False, '全选命令失败，未发送文字')
    result = send(argv[2], {'action': 'input_text', 'text': proposal['text'], **(target or {})})
    return finish(result['exit_code'] == 0)
