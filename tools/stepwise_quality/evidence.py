"""Freeze stepwise graph/call evidence without importing or executing a traversal."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


def read(path, default=None):
    path = Path(path)
    if not path.exists() and default is not None:
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def redact(value):
    """Portable exports retain structure but never publish transport configuration."""
    if isinstance(value, dict):
        return {k: '[redacted]' if re.search(r'api.?key|authorization|password|token|base_url|endpoint', k, re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'https?://[^\s\"<>]+', '[endpoint-redacted]', value)
        value = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[credential-redacted]', value)
    return value


def inside(root, path):
    path = Path(path).resolve()
    path.relative_to(Path(root).resolve())
    return path


def snapshot(run, name):
    base = inside(run / 'knowledge_snapshots', run / name)
    records = {p.parent.name: read(p) for p in sorted((base / 'regions').glob('*/region.json'))}
    return base, records


def check(item, code, reason, verdict='insufficient', refs=None):
    item['checks'].append({'code': code, 'reason': reason, 'verdict': verdict,
                           'evidence': refs or ['record']})


class Bundle:
    def __init__(self, run, out):
        self.run, self.out = run, out

    def item(self, key, kind, title, data):
        return {'id': key, 'kind': kind, 'title': title, 'data': redact(data),
                'images': [], 'checks': [], 'judgments': [], 'human': [],
                'evidence_ids': ['record']}

    def image(self, item, base, value, role, box=None, click_box=None):
        if not value:
            return
        try:
            path = inside(self.run, base / value)
            data = path.read_bytes()
            with Image.open(path) as im:
                size = list(im.size)
                im.verify()
            sha = digest(data)
            rel = 'assets/' + sha + path.suffix.lower()
            target = self.out / rel
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                target.write_bytes(data)
            eid = f'image:{len(item["images"])}'
            item['images'].append({'id': eid, 'role': role, 'path': rel, 'size': size,
                                   'sha256': sha, 'box': box, 'click_box': click_box,
                                   'source': str(path.relative_to(self.run))})
            item['evidence_ids'].append(eid)
            for code, bounds in [('invalid_box', box), ('invalid_click_box', click_box)]:
                if not bounds:
                    continue
                try:
                    l, t, r, b = [bounds[k] for k in ('left', 'top', 'right', 'bottom')]
                    valid = 0 <= l < r <= size[0] and 0 <= t < b <= size[1]
                except (KeyError, TypeError):
                    valid = False
                if not valid:
                    check(item, code, ('点击区域' if code == 'invalid_click_box' else '身份框') + '超出原图或不是有效矩形。', 'problem', [eid, 'record'])
        except (OSError, ValueError, TypeError):
            check(item, 'image_unavailable', f'{role} 图缺失、损坏或位于运行目录之外。')

    def observation(self, item, base, observations):
        obs = next((x for x in reversed(observations) if x.get('source_image') or x.get('image')), {})
        self.image(item, base, obs.get('source_image'), 'source', obs.get('bbox'), obs.get('click_bbox'))
        self.image(item, base, obs.get('image'), 'crop')
        # Identity appearance and clickable area are separate evidence.
        self.image(item, base, obs.get('click_image'), 'click_crop')
        if not any(x['role'] == 'source' for x in item['images']):
            check(item, 'missing_source', '缺少可读取的整屏原图，不能只凭裁图确认归属。')
        if not any(x['role'] == 'crop' for x in item['images']):
            check(item, 'missing_crop', '没有保存的身份裁图；不据此断言功能错误。')


def graph_items(bundle, base, records):
    items = []
    for rid, region in records.items():
        folder = base / 'regions' / rid
        view = {k: v for k, v in region.items() if k not in ('controls', 'actions', 'tasks', 'transitions', 'observations')}
        view['latest_observation'] = region.get('observations', [])[-1:]
        view['controls'] = {c: x.get('name') for c, x in region.get('controls', {}).items()}
        item = bundle.item(f'region:{rid}', 'region', region.get('name', rid), view)
        bundle.observation(item, folder, region.get('observations', []))
        parent = region.get('parent_region')
        if parent and parent not in records:
            check(item, 'missing_parent', '父区块引用不存在。', 'problem')
        items.append(item)
        for cid, control in region.get('controls', {}).items():
            item = bundle.item(f'control:{rid}:{cid}', 'control', control.get('name', cid),
                               {'owner': {'id': rid, 'name': region.get('name'), 'description': region.get('description')},
                                'control': {**control, 'observations': control.get('observations', [])[-1:]}})
            bundle.observation(item, folder, control.get('observations', []))
            items.append(item)
        for name, task in region.get('tasks', {}).items():
            item = bundle.item(f'task:{rid}:{name}', 'task', name, {'owner': rid, 'task': task,
                              'recorded_actions': {a: region.get('actions', {}).get(a) for a in task.get('attempts', [])}})
            cid = task.get('control')
            if cid and cid not in region.get('controls', {}):
                check(item, 'missing_control', '任务控件引用不存在。', 'problem')
            if task.get('status') == 'done' and not (task.get('result_evidence') or task.get('completion_basis')):
                check(item, 'completion_evidence_missing', '完成任务没有明确结果依据；仅作为待复核缺口。')
            bundle.observation(item, folder, region.get('controls', {}).get(cid, region).get('observations', []))
            for aid in task.get('attempts', []):
                action = region.get('actions', {}).get(aid, {})
                for side in ('before', 'after'):
                    bundle.image(item, folder, action.get('evidence', {}).get(side + '_image'), side)
            items.append(item)
        functions = region.get('functions', {})
        functions = functions.items() if isinstance(functions, dict) else ((v.get('name', str(i)), v) for i, v in enumerate(functions))
        for name, function in functions:
            item = bundle.item(f'function:{rid}:{name}', 'function', name,
                               {'owner': rid, 'function': function, 'tasks': region.get('tasks', {})})
            bundle.observation(item, folder, region.get('observations', []))
            items.append(item)
        for index, edge in enumerate(region.get('transitions', [])):
            action = region.get('actions', {}).get(edge.get('attempt'), {})
            item = bundle.item(f'edge:{rid}:{index}', 'edge', f'{rid} → {edge.get("target_region")}',
                               {'source': rid, 'edge': edge, 'action': action})
            if edge.get('target_region') not in records:
                check(item, 'missing_target', '跳转目标区块不存在。', 'problem')
            if not action:
                check(item, 'missing_action', '关系缺少对应动作记录；不能确认为执行跳转。')
            for side in ('before', 'after'):
                bundle.image(item, folder, action.get('evidence', {}).get(side + '_image'), side)
            if not item['images']:
                check(item, 'missing_edge_images', '缺少动作前后图。')
            items.append(item)
    return items


def changes(before, after):
    result = []
    for rid in sorted(before.keys() | after.keys()):
        if before.get(rid) != after.get(rid):
            result.append({'region': rid, 'before': before.get(rid), 'after': after.get(rid)})
    return result


def call_items(bundle, calls):
    """Only explicit snapshot parent/stage references; never substitute current graph."""
    indexed = {}
    for p in sorted((bundle.run / 'knowledge_snapshots').glob('*/source.json')):
        source = read(p)
        match = re.search(r'(?:^|-)(\d{4,})(?:-|$)', source.get('stage', ''))
        ref = source.get('call') or (match[1] if match else None)
        if ref:
            indexed.setdefault(str(ref), []).append((p.parent, source))
    items = []
    for call in calls:
        if not re.fullmatch(r'\d+', call):
            raise ValueError('call must be numeric')
        folder = bundle.run / 'calls' / call
        q = read(folder / 'request.json')
        data = {'call': call, 'request': q, 'reply': read(folder / 'response.json', {}), 'commits': []}
        for base, src in indexed.get(call, []):
            parent = src.get('parent_snapshot')
            _, after = snapshot(bundle.run, str(base.relative_to(bundle.run)))
            before = snapshot(bundle.run, parent)[1] if parent else {}
            execution = {}
            if src.get('attempt'):
                attempt = inside(bundle.run / 'action_attempts', bundle.run / 'action_attempts' / src['attempt'])
                execution = {name: read(attempt / (name + '.json'), {}) for name in ('proposal', 'binding', 'dispatch', 'receipt')}
            data['commits'].append({'snapshot': str(base.relative_to(bundle.run)), 'parent': parent,
                                    'parent_known': bool(parent), 'changes': changes(before, after),
                                    'execution': execution})
        data['correction_history'] = []
        for episode in sorted((bundle.run / 'repair_episodes').glob('*/episode.json')):
            job = read(episode)
            history = job.get('history', [])
            if not any(h.get('call') == call for h in history):
                continue
            # Final episode status/candidate may come from the future; retain history only.
            known_history = []
            for h in history:
                last = h.get('call')
                if last and last.isdigit() and int(last) <= int(call):
                    known_history.append(h)
            data['correction_history'].append({'stage': job.get('stage'), 'history': known_history})
        item = bundle.item('call:' + call, 'call', f'{call} · {q.get("stage", "unknown")}', data)
        if not data['commits']:
            check(item, 'no_linked_commit', '未找到明确关联快照；不能据此断言被拒绝或未登记。')
        for frame in q.get('screenshots', []):
            bundle.image(item, bundle.run, frame, 'sent_frame')
        items.append(item)
    return items


def build(run, output, calls=None):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output == run or run in output.parents:
        raise ValueError('quality output must be separate from source run')
    output.mkdir(parents=True, exist_ok=False)
    pointer = read(run / 'knowledge_current.json')
    base, records = snapshot(run, pointer['snapshot'])
    if not records:
        raise ValueError('No stepwise Region records in selected snapshot')
    bundle = Bundle(run, output)
    items = graph_items(bundle, base, records)
    if calls:
        items.extend(call_items(bundle, calls))
    hashes = {str(p.relative_to(run)): digest(p.read_bytes()) for p in sorted(base.glob('regions/*/region.json'))}
    report = {'schema': 'stepwise_quality.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'snapshot': pointer['snapshot'], 'source_hashes': hashes,
              'scope': '冻结逐步遍历图；只检查已记录对象，不证明应用覆盖完整。',
              'items': items}
    write(output / 'report.json', report)
    code = Path(__file__).resolve().parent
    inspector_hashes = {p.name: digest(p.read_bytes()) for p in sorted(code.iterdir())
                        if p.is_file() and p.suffix in ('.py', '.html')}
    write(output / 'manifest.json', {'schema': report['schema'], 'snapshot': report['snapshot'],
                                    'source_hashes': hashes, 'model_calls': 0,
                                    'inspector_source_hashes': inspector_hashes,
                                    'source_name': run.name, 'calls': calls or []})
    return report
