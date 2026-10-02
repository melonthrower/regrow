"""Read-only visual grounding for collection; never updates traversal knowledge."""
from __future__ import annotations

import json
from pathlib import Path

from ..explore.actions import _pixel_point


class CollectionVisualGuard:
    """Compare proposed points with current matches from a pinned visual matcher.

    Controls are immutable snapshot observations indexed by region.control.
    Unmatched/new targets require a fresh visual confirmation, not a nearest-box
    fallback. An allowed point is grounding evidence, never action success.
    """

    def __init__(self, controls, match_control, output_root):
        self.controls = controls
        self.match_control = match_control
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        if any(self.output_root.iterdir()):
            raise ValueError('Visual guard output must be a fresh directory')
        self.checks = []
        self.model_calls = 0

    def catalog(self):
        return [{'ref': ref, 'name': c['name']} for ref, c in self.controls.items()]

    def check(self, action, decision, screenshot, agent):
        if action.kind in {'back', 'wait'}:
            return {'allowed': True, 'verdict': 'non_point_action'}
        folder = self.output_root / f'{len(self.checks) + 1:04d}'
        folder.mkdir()
        frame = folder / 'current.png'
        frame.write_bytes(screenshot)
        point = _pixel_point(screenshot, action.point_1000)
        ref = decision.get('visual_target_ref')
        control = self.controls.get(ref)
        result = {'target_ref': ref, 'target': action.target, 'point_pixels': list(point),
                  'point_1000': list(action.point_1000), 'frame': str(frame),
                  'allowed': False, 'verdict': 'unresolved'}
        if control is not None:
            hit = self.match_control(control, str(frame))
            result['match'] = hit
            box = hit.get('box')
            if hit.get('accepted') and box:
                x, y = point
                inside = box[0] <= x < box[2] and box[1] <= y < box[3]
                result.update(allowed=inside, verdict='agree' if inside else 'mismatch')
                if inside and action.target.strip().casefold() != control['name'].strip().casefold():
                    result.update(allowed=False, verdict='unresolved',
                                  identity_check_reason='target label differs from selected control')
        if result['verdict'] == 'unresolved':
            # The same budgeted transport records this independent grounding call.
            self.model_calls += 1
            verdict = agent._call(
                role='collection_grounding', screenshots=[screenshot],
                response_schema={'type':'object', 'properties': {
                    'confirmed': {'type':'boolean'}, 'reason': {'type':'string'}},
                    'required':['confirmed','reason'], 'additionalProperties':False},
                system_prompt=('只核验当前截图中的动作定位，不执行动作，也不判断业务成功。'
                               'point_pixels是实际投递像素，point_1000为整屏归一化坐标。'
                               '结合文字、形状、所在行和当前接管输入的前景，判断坐标是否落在'
                               'target所指控件的可操作部分；不能仅凭附近存在同名文字确认。'
                               '已选known_control若与target及action_intent指向不同对象，必须false；'
                               '同一对象的不同自然称呼可确认，不能把延迟菜单与开关当成同一控件。'
                               '历史外观未可靠匹配或控件未登记，均不等于坐标错误。'
                               '只有当前图明确支持身份、可操作性和点位三者一致才confirmed=true；'
                               '遮挡、歧义、坐标落在相邻控件、无法确认时false并说明。'),
                user_prompt=json.dumps({'target': action.target, 'kind': action.kind,
                                        'known_control': control.get('name') if control else None,
                                        'known_ref': ref,
                                        'action_intent': decision.get('action_intent', ''),
                                        'point_pixels': list(point),
                                        'point_1000': list(action.point_1000)}, ensure_ascii=False))
            result['visual_confirmation'] = verdict
            result['allowed'] = verdict.get('confirmed') is True
            if result['allowed']:
                result['verdict'] = 'visually_confirmed'
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        self.checks.append(result)
        return result


def snapshot_controls(snapshot):
    """Load the latest usable dual-box observation without changing the graph."""
    controls = {}
    for path in sorted(Path(snapshot).glob('regions/*/region.json')):
        region = json.loads(path.read_text())
        for ref, control in region.get('controls', {}).items():
            observations = [o for o in control.get('observations', [])
                            if o.get('image') and o.get('bbox') and o.get('click_bbox')]
            if not observations:
                continue
            observation = observations[-1]
            image = (path.parent / observation['image']).resolve()
            if not image.is_file():
                raise ValueError(f'Collection identity image is missing: {image}')
            controls[f'{path.parent.name}.{ref}'] = {
                **observation, 'name': control['name'], 'image': str(image)}
    return controls


def build_visual_guard(graph, output_root):
    """Pin the existing matcher for this collection, leaving traversal untouched."""
    from .collection_graph import StepwiseCollectionGraph, load_collection_graph
    if not isinstance(graph, StepwiseCollectionGraph):
        return None
    from copy import deepcopy
    import hashlib
    import importlib.util
    import shutil
    import sys
    if load_collection_graph(graph.source)[1] != graph.digest:
        raise ValueError('Collection graph changed after instruction validation')
    assets = Path(output_root) / 'graph_images'
    assets.mkdir(parents=True, exist_ok=False)
    controls = deepcopy(graph.controls)
    copied = {}
    for control in controls.values():
        path = Path(control['image'])
        relative = str(path.relative_to(graph.source.parent))
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if graph.dependencies[relative] != digest:
            raise ValueError('Collection image changed during freezing')
        destination = assets / (digest + path.suffix)
        destination.write_bytes(data)
        control['image'] = str(destination)
        copied[relative] = {'sha256': digest, 'copy': str(destination.relative_to(output_root))}
    (assets / 'source.json').write_text(json.dumps(copied, indent=2)+'\n')
    source = Path(__file__).resolve().parents[4] / 'experiments/clock_manual_20260919'
    frozen = Path(output_root) / 'matcher'
    frozen.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in ('identity_templates.py', 'image_match.py', 'visual_choices.py'):
        shutil.copyfile(source / name, frozen / name)
        hashes[name] = hashlib.sha256((frozen / name).read_bytes()).hexdigest()
    (frozen / 'source.json').write_text(json.dumps({'source': str(source), 'files': hashes}, indent=2)+'\n')
    def load(name):
        spec = importlib.util.spec_from_file_location('collection_'+name, frozen / (name+'.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    # visual_choices imports this module once; keep its object pinned without
    # leaving a traversal module replacement in the process import table.
    prior = sys.modules.get('identity_templates')
    try:
        sys.modules['identity_templates'] = load('identity_templates')
        matcher = load('visual_choices')
    finally:
        if prior is None:
            sys.modules.pop('identity_templates', None)
        else:
            sys.modules['identity_templates'] = prior
    return CollectionVisualGuard(controls, matcher.match_control, Path(output_root) / 'grounding')
