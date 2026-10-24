#!/usr/bin/env python3
"""Build a portable, read-only run report: python3 tools/run_summary.py RUN_DIR."""
import argparse
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path


COLORS = {'action_selection': 'blue', 'observation': 'green', 'discovery': 'green',
          'control_identity_comparison': 'red', 'observation_update': 'gray',
          'object_registration': 'gray'}


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def esc(value):
    return escape(str(value), quote=True)


def local_path(root, reference):
    """Only follow evidence references within this run."""
    if not isinstance(reference, str) or not reference:
        return None
    path = (root / reference).resolve()
    return path if path.is_relative_to(root.resolve()) else None


def snapshot(root, reference):
    path = local_path(root, reference)
    return read_json(path / 'objects.json') if path else {}


def label(objects, target):
    if not isinstance(target, str):
        return '未绑定控件'
    parts = target.split('/')
    controls = objects.get('controls', {})
    regions = objects.get('regions', {})
    if len(parts) == 2 and isinstance(controls, dict) and isinstance(regions, dict):
        region = regions.get(parts[0], {})
        control = controls.get(parts[1], {})
        if isinstance(control, dict) and control.get('name'):
            return f"{region.get('name', parts[0])} / {control['name']}（{target}）"
    return target or '未绑定控件'


def picture(path, caption):
    try:
        data = base64.b64encode(path.read_bytes()).decode('ascii')
    except OSError:
        return f'<figure><div class="missing">截图缺失</div><figcaption>{caption}</figcaption></figure>'
    return (f'<figure><img loading="lazy" width="200" src="data:image/png;base64,{data}" '
            f'alt="{caption}"><figcaption>{caption}</figcaption></figure>')


def collect(root):
    calls = []
    selections = defaultdict(list)
    names = {}
    for folder in sorted((root / 'calls').glob('*')):
        if not folder.is_dir() or not folder.name.isdigit():
            continue
        request = read_json(folder / 'request.json')
        if not request:
            continue
        role = request.get('role') or request.get('stage') or 'unknown'
        source = request.get('source')
        source = source if isinstance(source, dict) else {}
        calls.append({'id': folder.name, 'role': str(role), 'stage': request.get('stage', ''),
                      'attempt': source.get('attempt')})
        if role != 'action_selection':
            continue
        proposal = read_json(folder / 'proposal.json') or read_json(folder / 'response.json')
        action = proposal.get('action')
        if isinstance(action, dict):
            proposal = action
            action = proposal.get('action')
        target = proposal.get('target')
        if not action or action in ('none', 'complete') or not isinstance(target, str) or not target:
            continue
        # Free-text targets have no stable identity; do not merge them as controls.
        if len(target.split('/')) != 2:
            continue
        selections[target].append(folder.name)
        names.setdefault(target, label(snapshot(root, source.get('snapshot')), target))
    attempts = []
    omitted = 0
    for folder in sorted((root / 'action_attempts').glob('a*')):
        if not folder.is_dir():
            continue
        receipt = read_json(folder / 'receipt.json')
        if not receipt or not receipt.get('executed_steps'):
            omitted += 1
            continue
        proposal = read_json(folder / 'proposal.json')
        dispatch = read_json(folder / 'dispatch.json')
        commit = read_json(folder / 'commit.json')
        related = {c['id'] for c in calls if c['attempt'] == folder.name}
        for value in (dispatch.get('source_call'), commit.get('update_call')):
            if isinstance(value, str) and value.isdigit():
                related.add(value)
        target = proposal.get('target', '')
        objects = snapshot(root, commit.get('snapshot'))
        attempts.append({'id': folder.name, 'folder': folder,
                         'label': label(objects, target), 'action': proposal.get('action', '未知操作'),
                         'calls': sorted(related, key=int), 'registered': bool(commit.get('snapshot')),
                         'exit_code': receipt.get('exit_code', '未知')})
    return calls, selections, names, attempts, omitted


def build_html(root):
    calls, selections, names, attempts, omitted = collect(root)
    pointer = read_json(root / 'knowledge_current.json')
    current = local_path(root, pointer.get('snapshot'))
    tasks = read_json(current / 'tasks.json') if current else {}
    counts = Counter(t.get('status', 'unknown') for t in tasks.values() if isinstance(t, dict))
    task_text = (' / '.join(f'{s}: {counts[s]}' for s in ('pending', 'done', 'blocked'))
                 if current and (current / 'tasks.json').is_file() else '任务记录不可用')
    progress = read_json(root / 'progress_current.json')
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>运行摘要</title><style>',
             'body{font:15px/1.6 system-ui,sans-serif;margin:24px;color:#202735;background:#f6f8fb}'
             'section{background:white;padding:20px;margin:20px 0;border-radius:10px}'
             '.strip{display:flex;overflow-x:auto;padding:12px 0;gap:3px}'
             '.cell{flex:0 0 34px;height:75px;text-align:center;color:white;text-decoration:none;font-size:11px}'
             '.blue{background:#2563eb}.green{background:#15803d}.red{background:#dc2626}'
             '.gray{background:#64748b}.orange{background:#c65b0c}'
             '.legend span{display:inline-block;padding:3px 8px;color:white;margin:3px}'
             'article{border-top:1px solid #ddd;padding:16px 0}.frames{display:flex;gap:12px;flex-wrap:wrap}'
             'figure{margin:0}img{width:200px;max-width:220px;height:auto}.missing{width:200px;padding:20px 0;background:#eee}'
             'figcaption,small{color:#586174}table{border-collapse:collapse;width:100%}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}'
             '.alert{color:#b91c1c;font-weight:bold}a{color:#1d4ed8}h1,h2,h3{line-height:1.3}'
             '</style><body><h1>运行摘要</h1>',
             f'<p>{esc(root.name)} · 有效调用 {len(calls)} · 有执行回执动作 {len(attempts)} · '
             f'已登记 {sum(a["registered"] for a in attempts)} · 状态 {esc(progress.get("status", "未知"))}<br>{esc(task_text)}</p>',
             '<section><h2>1. 调用分布</h2><div class="legend">']
    for color, title in [('blue', '动作选择'), ('green', '观察 / 发现'), ('red', '身份复核'),
                         ('gray', '结果更新 / 对象登记'), ('orange', '其他 / 纠错')]:
        parts.append(f'<span class="{color}">{title}</span>')
    parts.append('</div><p>横向滚动查看全部调用，悬停查看角色与阶段。红色聚集是循环排查线索。</p><div class="strip">')
    for call in calls:
        color = COLORS.get(call['role'], 'orange')
        title = esc(f"调用{call['id']} · {call['role']} · {call['stage']}")
        parts.append(f'<span id="call-{esc(call["id"])}" class="cell {color}" title="{title}">{esc(call["id"])}</span>')
    parts.append('</div><p>蓝色之后缺少灰色值得检查；是否登记以动作的 commit 记录为准，颜色本身不证明登记失败。</p></section>')
    parts.append('<section><h2>2. 动作时间线</h2><p>前后图为历史执行原图，供人工判断变化；执行回执不等于动作达成目标。</p>')
    if omitted:
        parts.append(f'<p>另有 {omitted} 个尝试无已执行步骤回执，未列为真实动作。</p>')
    for attempt in attempts:
        ids = attempt['calls']
        span = f'调用{ids[0]}–{ids[-1]}' if ids else '调用范围未知'
        status = '已登记' if attempt['registered'] else '未见登记记录'
        parts.append(f'<article><h3>{esc(attempt["id"])} · {esc(attempt["label"])} · {esc(attempt["action"])}</h3>'
                     f'<p>{esc(span)}（跨度内可能含其他工作） · {status} · 执行退出码 {esc(attempt["exit_code"])}</p>'
                     '<div class="frames">')
        parts.append(picture(attempt['folder'] / 'before.png', '动作前'))
        parts.append(picture(attempt['folder'] / 'after.png', '动作后'))
        parts.append('</div></article>')
    if not attempts:
        parts.append('<p>暂无可确认执行的动作记录。</p>')
    parts.append('</section><section><h2>3. 重复控件警报</h2>'
                 '<p>按控件引用统计动作选择，不合并同名对象；排除 complete / none。选择不等于执行。'
                 '≥3 次标红，≥5 次提示可能卡住，需结合任务及截图判断。</p><table><tr><th>控件</th><th>选择次数</th><th>调用编号</th></tr>')
    for target, ids in sorted(selections.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(ids) < 3:
            continue
        links = '、'.join(f'<a href="#call-{esc(i)}">{esc(i)}</a>' for i in ids)
        warning = ' · 可能卡住' if len(ids) >= 5 else ''
        parts.append(f'<tr class="alert"><td>{esc(names.get(target, target))}</td><td>{len(ids)}{warning}</td><td>{links}</td></tr>')
    parts.append('</table>')
    if not any(len(ids) >= 3 for ids in selections.values()):
        parts.append('<p>未发现同一控件被选择 ≥3 次。</p>')
    parts.append('</section><footer>缺失或无法解析的调用文件已跳过；缺图显示占位。'
                 '统计来自本报告生成时可读取的记录，不自动判断动作成功。</footer></body></html>')
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    args = parser.parse_args()
    root = args.run_dir.resolve()
    if not root.is_dir():
        parser.error('run_dir 必须是已有运行目录')
    html = build_html(root)
    output = root / 'summary.html'
    if output.exists():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output.rename(root / f'summary.{stamp}.html')
    output.write_text(html, encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
