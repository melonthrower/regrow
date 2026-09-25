"""Read-only screen/map timeline from committed snapshots and delivery receipts."""
from pathlib import Path
from urllib.parse import urlencode
import re
import region_graph


def asset(run, relative):
    run = Path(run).resolve()
    path = (run / relative).resolve()
    path.relative_to(run)
    if path.suffix.lower() != '.png' or path.relative_to(run).parts[0] not in ('screenshots', 'action_attempts', 'step_rounds'):
        raise ValueError('Not a traversal screenshot')
    return path


def project(run):
    run = Path(run).resolve()
    read = region_graph.read
    current = read(run / 'knowledge_current.json')['snapshot']
    chain = []
    version = current
    while version and version not in {v for v, _ in chain}:
        _, base, _ = region_graph.snapshot(run, version)
        source = read(base / 'source.json')
        chain.append((version, source))
        version = source.get('parent_snapshot')
    chain.reverse()
    events = []
    graphs = {}
    def frame(path):
        try:
            relative = str(Path(path).resolve().relative_to(run))
            if asset(run, relative).is_file():
                return '/replay-image?' + urlencode({'path':relative})
        except (ValueError, OSError):
            pass
        return None
    def number(value):
        match = re.search(r'\d+', str(value or '0'))
        return int(match[0]) if match else 0
    last_call = 0
    for order, (version, source) in enumerate(chain):
        call = source.get('call') or source.get('update_call')
        if not call:
            match = re.search(r'-(\d{4})-', Path(version).name)
            call = match[1] if match else None
        sort_call = max(last_call, number(call))
        last_call = sort_call
        graph = region_graph.project(run, version)
        graphs[version] = graph
        qpath = run / 'calls' / str(call) / 'request.json'
        request = read(qpath) if qpath.exists() else {}
        images = request.get('screenshots', [])
        screenshot = frame(run / images[-1]) if images else frame(run/'screenshots/initial.png') if order == 0 else None
        events.append({'id':version,'kind':'registered','order':[sort_call,3,order],
                       'label':'初始状态' if order == 0 else f'调用 {call} · 知识已登记' if call else '调度状态已登记',
                       'snapshot':version,'image':screenshot,'focus':None,'attempt':source.get('attempt')})
    proposals = []
    for folder in sorted((run / 'calls').glob('*')):
        if not (folder / 'request.json').exists():
            continue
        request = read(folder / 'request.json')
        if request.get('stage') != 'action_selection':
            continue
        reply = read(folder/'response.json') if (folder/'response.json').exists() else {}
        images = request.get('screenshots', [])
        if reply:proposals.append((folder.name, reply))
        events.append({'id':folder.name+'-proposal','kind':'proposal','order':[number(folder.name),0,0],
                       'label':f'调用 {folder.name} · 动作提案（不代表执行）' if reply else f'调用 {folder.name} · 正在选择动作',
                       'image':frame(run/images[-1]) if images else None,'focus':None,'action':reply})
    for folder in sorted((run / 'action_attempts').glob('*')):
        dispatch = folder / 'dispatch.json'
        if not dispatch.exists():
            if (folder/'proposal.json').exists() and (folder/'pre_dispatch.png').exists():
                proposal = read(folder/'proposal.json')
                matching = [call for call, reply in proposals if reply == proposal]
                if len(matching) == 1:
                    binding = read(folder/'binding.json') if (folder/'binding.json').exists() else {}
                    events.append({'id':folder.name+'-check','kind':'blocked','order':[number(matching[0]),2,0],
                                   'label':folder.name+' · 投递前复核（尚无执行回执）',
                                   'image':frame(folder/'pre_dispatch.png'),'focus':binding.get('region_ref')})
            continue
        d = read(dispatch)
        binding = read(folder / 'binding.json') if (folder / 'binding.json').exists() else {}
        action = d.get('action', {})
        call = number(d.get('source_call'))
        common = {'focus':binding.get('region_ref'),'attempt':folder.name,'action':action}
        events.append({**common,'id':folder.name+'-before','kind':'before','order':[call,1,0],
                       'label':f'{folder.name} · 准备执行 {action.get("action", "动作")} · {action.get("target", "")}',
                       'image':frame(folder/'before.png')})
        receipt = read(folder / 'receipt.json') if (folder / 'receipt.json').exists() else {}
        if receipt.get('executed_steps'):
            label = '已执行 · 等待结果登记' if receipt.get('exit_code') == 0 else '执行异常 · 结果未确认'
            events.append({**common,'id':folder.name+'-after','kind':'after','order':[call,2,0],
                           'label':label+' · '+folder.name,'image':frame(folder/'after.png')})
        elif receipt:
            events.append({**common,'id':folder.name+'-blocked','kind':'blocked','order':[call,2,0],
                           'label':'动作未执行 · '+folder.name,'image':frame(folder/'before.png')})
    events.sort(key=lambda e:e['order'])
    version = chain[0][0] if chain else current
    image = frame(run/'screenshots/initial.png')
    previous_interactive = set()
    for event in events:
        version = event.get('snapshot', version)
        event['snapshot'] = version
        if event['image']:
            image = event['image']
            event['reused_image'] = False
        else:
            event['image'] = image
            event['reused_image'] = True
        graph = graphs[version]
        interactive = [n['id'] for n in graph['nodes'] if n['current']]
        if not event['focus']:
            fresh = [rid for rid in interactive if rid not in previous_interactive]
            event['focus'] = (fresh[-1] if fresh else graph.get('working') if graph.get('working') in interactive else interactive[-1] if interactive else None)
        previous_interactive = set(interactive)
        del event['order']
    return {'app':read(run/'run_manifest.json').get('app',run.name),'events':events,'graphs':graphs}
