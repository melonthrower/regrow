"""Qwen3-VL GUI tool arguments, shared by request preparation and execution."""
from copy import deepcopy
import math
import re
import shlex

POINT = {'type': 'array', 'items': {'type': 'integer', 'minimum': 0}, 'minItems': 2, 'maxItems': 2}
FIELDS = {
    'coordinate': POINT, 'coordinate2': POINT,
    'text': {'type': 'string'}, 'pixels': {'type': 'integer'},
    'keys': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}, 'minItems': 1},
    'button': {'enum': ['Back', 'Home', 'Menu', 'Enter']},
    'time': {'type': 'number', 'minimum': 0},
    'status': {'enum': ['success', 'failure']},
}
# Device operations only. answer/terminate are tool-level task outcomes.
DESKTOP = {
    'left_click': ('coordinate',), 'right_click': ('coordinate',), 'middle_click': ('coordinate',),
    'double_click': ('coordinate',), 'triple_click': ('coordinate',),
    'mouse_move': ('coordinate',), 'left_click_drag': ('coordinate',),
    'scroll': ('pixels',), 'hscroll': ('pixels',), 'key': ('keys',),
    'type': ('text',), 'wait': ('time',),
}
MOBILE = {
    'click': ('coordinate',), 'long_press': ('coordinate', 'time'),
    'swipe': ('coordinate', 'coordinate2'), 'type': ('text',), 'key': ('text',),
    'system_button': ('button',), 'open': ('text',), 'wait': ('time',),
}


CLICK_ACTIONS = {'left_click', 'right_click', 'middle_click', 'double_click', 'triple_click'}


def space(platform):
    return {'desktop': DESKTOP, 'android': MOBILE}[platform]


def specialize(branches, platform):
    """Replace the shared template's GUI branches while keeping workflow decisions."""
    template = next((b for b in branches if b.get('properties', {}).get('action', {}).get('enum') == ['click']
                     and 'x' in b['properties']), None)
    if template is None:
        return branches
    fields = template['properties']
    common = {key: value for key, value in fields.items() if key not in ('x', 'y', 'action')}
    result = []
    for branch in argument_schema(platform)['anyOf']:
        name = branch['properties']['action']['enum'][0]
        props = {**deepcopy(common), **branch['properties']}
        required = [k for k in template['required'] if k in common]
        if name in ('key', 'system_button', 'wait', 'open') and 'target' in required:
            required.remove('target')
        branch.update(properties=props, required=required + branch['required'])
        result.append(branch)
    result.extend(b for b in branches if not b.get('properties', {}).get('action', {}).get('enum')
                  or set(b['properties']['action']['enum']) & {'none', 'complete'})
    return result


def argument_schema(platform, *, outcomes=False):
    entries = dict(space(platform))
    if outcomes:
        entries['terminate'] = ('status',)
        if platform == 'desktop':
            entries['answer'] = ('text',)
    branches = []
    for name, args in entries.items():
        props = {'action': {'type': 'string', 'enum': [name]}, **{k: deepcopy(FIELDS[k]) for k in args}}
        required = [] if platform == 'desktop' and isinstance(name, str) and name in CLICK_ACTIONS else list(args)
        branches.append({'type': 'object', 'properties': props,
                         'required': ['action', *required], 'additionalProperties': False})
    return {'anyOf': branches}


def native(action, platform):
    name = action.get('action')
    if platform == 'desktop' and isinstance(name, str) and name in CLICK_ACTIONS and not any(action.get(k) is not None for k in ('x', 'y')):
        return True
    return isinstance(name, str) and name in space(platform) and all(k in action for k in space(platform)[name])


def tool_call(action, platform):
    name = action['action']
    args = {'action': name, **{k: action[k] for k in space(platform)[name] if k in action}}
    return {'name': 'computer_use' if platform == 'desktop' else 'mobile_use', 'arguments': args}


def validate(action, platform):
    import jsonschema
    args = tool_call(action, platform)['arguments']
    if not native(action, platform):
        raise ValueError('Missing Qwen tool arguments')
    for k, v in args.items():
        if k != 'action':
            jsonschema.validate(v, FIELDS[k])
    if 'time' in args and not math.isfinite(args['time']):
        raise ValueError('time must be finite')


def desktop_commands(action):
    validate(action, 'desktop')
    name = action['action']
    if name in CLICK_ACTIONS or name in ('mouse_move', 'left_click_drag'):
        point = ','.join(map(str, action.get('coordinate', [])))
        calls = {'mouse_move': 'moveTo', 'left_click_drag': 'dragTo', 'left_click': 'click',
                 'middle_click': 'middleClick', 'right_click': 'rightClick',
                 'double_click': 'doubleClick', 'triple_click': 'tripleClick'}
        extra = ',duration=0.5' if name == 'left_click_drag' else ''
        return [f'pyautogui.{calls[name]}({point}{extra})']
    if name in ('scroll', 'hscroll'):
        return [f"pyautogui.{name}({action['pixels']})"]
    if name == 'type':
        if not action['text'].isascii() and action['text']:
            raise ValueError('Desktop keyboard backend cannot deliver non-ASCII text')
        parts = [f'pyautogui.write({line!r},interval=0.03)' for line in action['text'].split('\n')]
        return ["; pyautogui.press('enter'); ".join(parts)]
    if name == 'key':
        keys = action['keys']
        code = 'press' if len(keys) == 1 else 'hotkey'
        names = [k.lower() for k in keys]
        check = f'assert all(k in pyautogui.KEYBOARD_KEYS for k in {names!r}), "Unsupported keyboard key"'
        return [check + f"; pyautogui.{code}({', '.join(repr(k) for k in names)})"]
    return []  # wait is recorded and timed by execute()


def mobile_commands(action):
    validate(action, 'android')
    name = action['action']
    if name in ('click', 'long_press', 'swipe'):
        x, y = map(str, action['coordinate'])
        if name == 'click':
            return [['shell', 'input', 'tap', x, y]]
        end = action.get('coordinate2', action['coordinate'])
        ms = round(action['time'] * 1000) if name == 'long_press' else 500
        return [['shell', 'input', 'swipe', x, y, *map(str, end), str(ms)]]
    if name == 'system_button':
        code = {'Back': '4', 'Home': '3', 'Menu': '187', 'Enter': '66'}[action['button']]
        return [['shell', 'input', 'keyevent', code]]
    if name == 'key':
        key = action['text'].upper()
        if not re.fullmatch(r'(?:KEYCODE_)?[A-Z0-9_]+', key):
            raise ValueError('Invalid Android key name')
        return [['shell', 'input', 'keyevent', key if key.isdigit() else 'KEYCODE_' + key.removeprefix('KEYCODE_')]]
    if name == 'type':
        if any(not 32 <= ord(c) <= 126 for c in action['text']) or '%s' in action['text']:
            raise ValueError('Android input text cannot deliver this string verbatim')
        return [['shell', 'input', 'text', shlex.quote(action['text'].replace(' ', '%s'))]]
    if name == 'open':
        package = action['text']
        if not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+', package):
            import sys
            from regrow.runtime.app_launcher import repository
            root = str(repository())
            if root not in sys.path:
                sys.path.insert(0, root)
            from gui_rewalk.src.config.config import get_android_package
            package = get_android_package(package)
            if not package:
                raise ValueError('Unknown Android app; provide its installed package name')
        return [['shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1']]
    return []
