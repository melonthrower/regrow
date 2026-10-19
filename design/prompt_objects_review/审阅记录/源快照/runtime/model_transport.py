"""Shared final request preparation, evidence persistence, budget and model send.

Used by both normal steps and recovery, on Android and desktop.
"""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from regrow.records.snapshots import read
from regrow.records.snapshots import write_json
from regrow.runtime import progress as progress

class BudgetExhausted(ValueError):
    """A normal stop at the caller's accounting boundary, without new delivery."""

def read_service_error(folder):
    """Read the sender's original HTTP or no-response transport evidence."""
    for name in ('http_error.json', 'transport_error.json'):
        path = Path(folder) / name
        if path.exists():
            return read(path)
    return None

def with_environment_scope(root, request):
    """The traversal environment restriction applies to both GUI platforms."""
    if request.get('original_request', {}).get('stage') == 'shared_control_review':
        return request
    request = deepcopy(request)
    from regrow.prompts.compose import contains
    from regrow.prompts.compose import catalog
    path = catalog(root)['platforms']['environment']['path']
    if not contains(request['fixed_parts'], path):
        from regrow.prompts.output import environment_part
        part = environment_part(root, request)
        request['fixed_parts'].append(part)
        request['system_prompt'] += '\n\n' + part['text']
    return request

def with_run_scope(request, run):
    manifest = Path(run) / 'run_manifest.json'
    scope = read(manifest).get('exploration_scope') if manifest.exists() else None
    if not scope:
        return request
    if request.get('role') == 'action_selection':
        from regrow.prompts.prompt_material import assign
        request = deepcopy(request)
        assign(request, {'本轮允许范围': scope})
        return request
    block = '\n\n本轮遍历允许范围（运行发起者提供，不由任务生成扩大）：\n' + scope
    if block in request['user_prompt']:
        return request
    request = deepcopy(request)
    request['user_prompt'] += block
    return request

def with_frame_context(request, run):
    """Disclose source dimensions; never infer them from model image rendering."""
    from PIL import Image
    from regrow.prompts.frame_context import purpose
    request = deepcopy(request)
    lines = []
    for (index, frame) in enumerate(request.get('screenshots', []), 1):
        with Image.open(Path(run) / frame) as image:
            (width, height) = image.size
        name = '本图' if len(request['screenshots']) == 1 else f'图{index}'
        lines.append(f'{name}：{purpose(request, frame)}；原图 {width}×{height} 像素。')
    if lines:
        block = '\n\n' + '\n'.join(lines)
        if block not in request['user_prompt']:
            request['user_prompt'] += block
    return request

def expand_schema(schema):
    """Make a saved root schema safe to embed inside a correction proposal."""

    def expand(node):
        if isinstance(node, list):
            return [expand(v) for v in node]
        if not isinstance(node, dict):
            return node
        ref = node.get('$ref')
        if ref and ref.startswith('#/$defs/'):
            return expand(schema['$defs'][ref.removeprefix('#/$defs/')])
        return {k: expand(v) for (k, v) in node.items() if k != '$defs'}
    return expand(schema)

def compact_schema(schema):
    """Factor repeated schema definitions while preserving every response branch."""
    import json
    from collections import Counter
    counts = Counter()

    def key(node):
        return json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(',', ':'))

    def count(node):
        if isinstance(node, dict):
            if (isinstance(node.get('type'), (str, list)) or isinstance(node.get('anyOf'), list)) and len(key(node)) > 100:
                counts[key(node)] += 1
            for value in node.values():
                count(value)
        elif isinstance(node, list):
            for value in node:
                count(value)
    count(schema)
    definitions = {}
    names = {}

    def fold(node, root=False):
        if isinstance(node, list):
            return [fold(x) for x in node]
        if not isinstance(node, dict):
            return node
        token = key(node)
        if not root and counts[token] > 1:
            if token not in names:
                name = 'shared_' + str(len(names) + 1)
                names[token] = name
                definitions[name] = {k: fold(v) for (k, v) in node.items()}
            return {'$ref': '#/$defs/' + names[token]}
        return {k: fold(v) for (k, v) in node.items()}
    result = fold(schema, True)
    if definitions:
        result['$defs'] = {**result.get('$defs', {}), **definitions}
    return result

class ModelTransport:
    """Run adapters supply root, run, account, ledger and save()."""

    def call(self, request):
        from regrow.prompts.history_disclosure import restore
        request = restore(request)
        from regrow.runtime.action_commands import platform_request
        request = platform_request(request, getattr(self, 'platform', 'android'))
        if request['platform'] == 'android':
            from regrow.prompts.output import android_part
            part = android_part(self.root, request)
            from regrow.prompts.compose import contains
            if part and (not contains(request['fixed_parts'], part['path'])):
                request['fixed_parts'].append(part)
                request['system_prompt'] += '\n\n' + part['text']
        from regrow.traversal.task_prerequisites import augment
        request = augment(self.root, self.run, request)
        request = with_environment_scope(self.root, request)
        request = with_run_scope(request, self.run)
        from regrow.prompts.frame_context import validate
        validate(request)
        request = with_frame_context(request, self.run)

        def strict_fields(schema):
            if isinstance(schema, list):
                for child in schema:
                    strict_fields(child)
            elif isinstance(schema, dict):
                for key in ('returns_to_previous',):
                    conditional = {field for branch in schema.get('allOf', []) for field in branch.get('then', {}).get('required', [])}
                    if key in schema.get('properties', {}) and key not in schema.get('required', []) and (key not in conditional):
                        schema.setdefault('required', []).append(key)
                for child in schema.values():
                    strict_fields(child)
        strict_fields(request['response_schema'])
        from regrow.recognition import control_indexes
        request = control_indexes.prepare(request)
        request['response_schema'] = compact_schema(request['response_schema'])
        from regrow.prompts.output import prepare
        request = prepare(request, self.root)
        output_instruction = '请按上述字段与输出要求返回一个JSON对象。'
        if not request['user_prompt'].endswith(output_instruction):
            request['user_prompt'] += '\n\n' + output_instruction
        from regrow.prompts.history_disclosure import project
        request = project(request)
        request = control_indexes.display(request)
        progress.request(request)
        if self.account['http_started'] >= self.account['max_http']:
            raise BudgetExhausted('HTTP budget exhausted')
        number = max([int(p.name) for p in (self.run / 'calls').iterdir() if p.name.isdigit()] + [0]) + 1
        call = f'{number:04d}'
        folder = self.run / 'calls' / call
        folder.mkdir()
        write_json(folder / 'request.json', request)
        write_json(folder / 'response.schema.json', request['response_schema'])
        (folder / 'system.prompt').write_text(request['system_prompt'])
        (folder / 'user.prompt').write_text(request['user_prompt'])
        for part in request['fixed_parts']:
            path = folder / 'fixed' / part['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(part['text'])
        self.account['http_started'] += 1
        self.save()
        manifest = read(self.run / 'run_manifest.json')
        manifest['actual_model_calls'] += 1
        manifest['last_call'] = call
        write_json(self.run / 'run_manifest.json', manifest)
        from regrow.traversal.exploration_summary import record
        record(self.run, folder, request, self.ledger.parent)
        result = subprocess.run([sys.executable, str(self.run / 'call_once.py'), call], capture_output=True)
        (folder / 'transport.log').write_bytes(result.stdout + result.stderr)
        result.check_returncode()
        progress.detail('回复已收到，框架校验与登记中')
        return (call, read(folder / 'response.json'))
