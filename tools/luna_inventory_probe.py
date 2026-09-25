"""Bounded saved-frame experiment, NOT an execution or verified-identity backend.

Run with --manifest JSON --output NEW_DIRECTORY. Manifest rows contain name,
group, screenshot (absolute path). No GUI environment or ledger is imported.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import time
from collections import defaultdict


def obj(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


TEXT = {'type': 'string'}
CONTROL = obj(dict(label=TEXT, function=TEXT, kind={
    'type': 'string', 'enum': ['button', 'toggle', 'input', 'choice', 'item']}, observation=TEXT))
REGION = obj(dict(source_ref=TEXT, parent_ref=TEXT, label=TEXT, function=TEXT,
                  controls={'type': 'array', 'items': CONTROL}))
SCHEMA = obj(dict(reuse={'type': 'array', 'items': TEXT},
                  regions={'type': 'array', 'items': REGION},
                  uncertain={'type': 'array', 'items': TEXT}, complete={'type': 'boolean'}))

PROMPT = """仅观察当前截图并输出区块/物理控件，不执行动作，不维护任务、操作能力或动作回执。
只登记当前接管输入的应用前景；模态窗口/菜单接管时排除背景、系统栏和键盘。
区块按功能对象和共同显示/隐藏、替换、滚动、编辑的范围划分，保留真正容器的父子关系。
持久导航/工具栏与被替换主体分开；重复数据成员不各建区块；内联展开的独立编辑上下文是来源容器的子区。
控件用实际label，没文字则label空、function写简短功能；区块同样优先真实标题，无标题用稳定功能说明。
具体独立按钮、选项、开关逐个列出，不用集合控件代替；同质数据条目可选代表。
纯说明放function，文字样式不证明不可交互；禁用控件保留并在observation说明，无法确定写uncertain。
输入previous是前图观察候选，并非当前可见或已验证身份。先核对当前完整截图：
- 完全未变且仍可见的区块（含控件取值和直接父区）只在reuse填原ref；程序复制其内容。
- 新增或变化区块在regions写完整的该区清单；同一功能组件变化时source_ref填原ref，真正新组件留空。
- 不可见区块不列入reuse/regions。省略只移出本帧视图，不删除历史。
- parent_ref填仍在本帧的旧ref，或new:0表示本回复regions第0行；根填空。可明确调整旧分区，不机械保留旧错误。
同一旧ref只能出现一次。程序分配新ID，模型不编造r编号。不因同位置/同父区就复用不同功能字段组。
不要重述未改区块。complete只指当前可见功能清点，截断或疑问记uncertain；不声称点击验证。
"""


def merge_observation(previous, response):
    """Atomically materialize a provisional view; never certify visual identity."""
    old = previous.get('regions', {})
    reuse, changed = response['reuse'], response['regions']
    sources = reuse + [r['source_ref'] for r in changed if r['source_ref']]
    if len(sources) != len(set(sources)) or any(ref not in old for ref in sources):
        raise ValueError('each source_ref/reuse must be a unique previous region ref')
    result = {ref: deepcopy(old[ref]) for ref in reuse}
    next_id = previous.get('next_id', 1)
    rows = []
    for region in changed:
        ref = region['source_ref']
        if not ref:
            ref = f'r{next_id}'
            next_id += 1
        rows.append(ref)
        result[ref] = {key: deepcopy(value) for key, value in region.items() if key != 'source_ref'}
    for ref in rows:
        parent = result[ref]['parent_ref']
        if parent.startswith('new:'):
            try:
                index = int(parent[4:])
                if index < 0:
                    raise ValueError()
                parent = rows[index]
            except (ValueError, IndexError):
                raise ValueError('parent_ref must reference a valid regions row') from None
            result[ref]['parent_ref'] = parent
    for ref in result:
        seen, cursor = set(), ref
        while cursor:
            if cursor not in result or cursor in seen:
                raise ValueError('parent_ref must be current and acyclic; include or reparent retained children')
            seen.add(cursor)
            cursor = result[cursor]['parent_ref']
    return dict(regions=result, next_id=next_id,
                complete=bool(response['complete'] and not response['uncertain']),
                uncertain=deepcopy(response['uncertain']), identity_verified=False)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def structural_hints(previous, current):
    """Cheap ambiguity signals, not visual truth or authorization to merge."""
    old, now = previous.get('regions', {}), current.get('regions', {})
    groups, hints = defaultdict(list), []
    for ref, region in now.items():
        signature = tuple(sorted((c['kind'], c['function']) for c in region['controls']))
        if signature:
            groups[(region['parent_ref'], signature)].append(ref)
        if ref in old and len(region['controls']) - len(old[ref]['controls']) >= 3:
            hints.append(dict(kind='control_group_growth', refs=[ref],
                question='新增控件是否构成共同显隐的独立编辑子区？若是，请拆分并保留来源容器。'))
        labels = sorted(c['label'] for c in region['controls'] if c['label'])
        for old_ref, candidate in old.items():
            if ref not in old and old_ref not in now and len(labels) >= 2 and labels == sorted(
                    c['label'] for c in candidate['controls'] if c['label']):
                hints.append(dict(kind='possible_recreated_region', refs=[ref, old_ref],
                    question='旧新控件标签相同，仅是复用候选，请核对功能与当前归属，不能按文字自动合并。'))
    for refs in groups.values():
        if len(refs) >= 2:
            hints.append(dict(kind='repeated_sibling_structure', refs=refs,
                question='同父区的控件结构重复：是同一列表的数据成员，还是独立功能组件？前者合为列表区，后者保留。'))
    return hints[:8]


def run(manifest_path, output, request_limit=10):
    # Import only the transport; this experiment cannot perform GUI actions.
    from gui_rewalk.src.core.explore import agent as transport
    from gui_rewalk.src.core.explore.api_config import load_explore_api_config, local_explore_api_config_path

    if not 1 <= request_limit <= 10:
        raise ValueError('request_limit must be 1..10')
    cases = json.loads(Path(manifest_path).read_text())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    frames = {c['name']: Path(c['screenshot']).read_bytes() for c in cases}
    manifest = [{**c, 'sha256': hashlib.sha256(frames[c['name']]).hexdigest()} for c in cases]
    save(output / 'manifest.json', manifest)
    (output / 'implementation.py').write_bytes(Path(__file__).read_bytes())
    cfg = load_explore_api_config(local_explore_api_config_path())
    agent = transport.OpenAIAPIExplorerAgent(base_url=cfg.base_url, api_key=cfg.api_key,
        model='gpt-5.6-luna', reasoning_effort='medium', output_root=str(output), timeout=cfg.timeout_seconds)
    http, results, cache = [], [], {}
    previous, group = {}, None
    active = ''
    original_post = transport.requests.post

    class BudgetStop(BaseException):
        pass

    def post(*args, **kwargs):
        if len(http) >= request_limit or (output / 'STOP').exists():
            raise BudgetStop('request budget or STOP')
        if any(row['call'] == active for row in http):
            raise BudgetStop('automatic transport retry disabled')
        payload = kwargs['json']
        if payload['model'] != 'gpt-5.6-luna':
            raise BudgetStop('only Luna authorized for this experiment')
        payload['max_output_tokens'] = 6500
        row = dict(call=active, model=payload['model'], started=time.time())
        http.append(row)
        save(output / 'http.json', http)
        try:
            response = original_post(*args, **kwargs)
            body = response.json()
            row.update(status=response.status_code, usage=body.get('usage'), effective_model=body.get('model'))
            return response
        finally:
            row['seconds'] = time.time() - row['started']
            save(output / 'http.json', http)

    transport.requests.post = post
    save(output / 'status.json', dict(status='running', http_limit=request_limit, model=agent.model,
        automatic_upgrade=False, new_gui_actions=0, boundary='provisional observation only; no ledger write'))
    try:
        for case in cases:
            if group != case['group']:
                previous = {}
            group = case['group']
            name, frame = case['name'], frames[case['name']]
            folder = output / name
            folder.mkdir()
            (folder / 'current.png').write_bytes(frame)
            comparison = {}
            if case.get('seed_observation'):
                previous = json.loads(Path(case['seed_observation']).read_text())
            if case.get('comparison_observation'):
                comparison = json.loads(Path(case['comparison_observation']).read_text())
                save(folder / 'comparison.json', comparison)
            save(folder / 'before.json', previous)
            # Cache exact same image only; no similarity or name-based automatic identity.
            key = (group, hashlib.sha256(frame).hexdigest())
            if key in cache:
                current = deepcopy(cache[key])
                current['next_id'] = max(current['next_id'], previous.get('next_id', 1))
                save(folder / 'cache.json', dict(exact_image=True, identity_verified=False))
            else:
                payload = dict(previous=previous.get('regions', {}))
                if case.get('seed_observation'):
                    payload['focused_correction'] = dict(
                        instruction='previous是本张截图已有的未验证候选。现在只修正分区疑点和明显漏项；保留正确内容。不要把控件类型或数量本身当区块边界。',
                        hints=structural_hints(comparison, previous))
                error = None
                for attempt in range(2):
                    active = f'{name}_{attempt + 1}'
                    prompt = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
                    if len(prompt.encode()) > 16000:
                        raise BudgetStop('context byte budget; no silent truncation')
                    save(folder / f'request_{attempt + 1}.json', dict(system_prompt=PROMPT, input=payload, schema=SCHEMA))
                    print('CALL', active, flush=True)
                    response = agent._call(role='luna_observation_probe', system_prompt=PROMPT,
                        user_prompt=prompt, screenshots=[frame], response_schema=SCHEMA)
                    save(folder / f'response_{attempt + 1}.json', response)
                    try:
                        current = merge_observation(previous, response)
                        error = None
                        break
                    except ValueError as exc:
                        error = str(exc)
                        payload['correction'] = dict(error=error, rejected=response)
                if error:
                    raise BudgetStop('structural correction failed')
                cache[key] = deepcopy(current)
            save(folder / 'after.json', current)
            results.append(dict(name=name, regions=len(current['regions']),
                controls=sum(len(r['controls']) for r in current['regions'].values()),
                complete=current['complete'], uncertain=current['uncertain']))
            save(output / 'results.json', results)
            previous = current
            print('FRAME', name, results[-1]['regions'], results[-1]['controls'], flush=True)
        unchanged = all(hashlib.sha256(Path(c['screenshot']).read_bytes()).hexdigest() == c['sha256'] for c in manifest)
        save(output / 'status.json', dict(status='finished', http_requests=len(http), new_gui_actions=0,
            source_unchanged=unchanged, automatic_upgrade=False, identity_verified=False))
    except BaseException as exc:
        save(output / 'status.json', dict(status='stopped', error_type=type(exc).__name__,
            http_requests=len(http), new_gui_actions=0, identity_verified=False))
        raise
    finally:
        transport.requests.post = original_post


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--request-limit', type=int, default=10)
    args = parser.parse_args()
    run(args.manifest, args.output, args.request_limit)
