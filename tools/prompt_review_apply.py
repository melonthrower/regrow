"""Apply exactly a frozen prompt job to its unchanged source; keep local history."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json


def _job(root, ident):
    if not ident or Path(ident).name != ident:
        raise ValueError('无效预览编号')
    return Path(root) / 'trace_jobs' / ident


def plan(root, ident):
    import prompt_review_trace as trace
    folder = _job(root, ident)
    status = trace.read(folder / 'status.json', {})
    texts = trace.read(folder / 'replacements.json', {})
    before = trace.read(folder / 'source-before.json', {})
    result = {'ready': False, 'paths': list(texts), 'source': str(trace.SOURCE)}
    if status.get('status') not in ('preview_ready', 'checked'):
        return {**result, 'reason': '先完成本版本的预览或保存帧检查。'}
    if not texts:
        return {**result, 'reason': '本次没有选中文案或组装配置。'}
    if set(before) != set(texts):
        return {**result, 'reason': '此历史版本缺少源码原文对照，请重新预览。'}
    if trace.read(folder / 'summary.json', {}).get('unused_modules'):
        return {**result, 'reason': '有选中内容未进入本次组装，请先调整选择。'}
    if not trace.source_matches(folder):
        return {**result, 'reason': '参与组装的源码已变化，请用当前版本重新预览。'}
    directory = (trace.SOURCE / 'regrow/prompts').resolve()
    for name, text in texts.items():
        target = directory / name
        if not target.resolve().is_relative_to(directory) or target.suffix not in ('.prompt', '.json'):
            return {**result, 'reason': '写回范围必须是当前提示目录中的文案或组装配置。'}
        if not target.is_file() or target.read_text() != before[name]:
            return {**result, 'reason': '源码已变化，请重新预览并对照：' + name}
        frozen = folder / 'source/regrow/prompts' / name
        if not frozen.is_file() or frozen.read_text() != text:
            return {**result, 'reason': '冻结稿件与预览记录不一致，请重新预览。'}
    return {**result, 'ready': True, 'reason': '仅写回本版本选中的稿件；保存备份，不部署。'}


def apply(root, ident):
    import prompt_review_trace as trace
    with trace.LOCK:
        if any(j.get('status') == 'running' for j in trace.jobs(root)):
            raise ValueError('请等当前预览或检查结束后写回。')
        info = plan(root, ident)
        if not info['ready']:
            raise ValueError(info['reason'])
        folder = _job(root, ident)
        texts = trace.read(folder / 'replacements.json')
        before = trace.read(folder / 'source-before.json')
        for name, text in texts.items():
            if name.endswith('.json'):
                json.loads(text)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8]
        archive = Path(root) / 'user_edits/applications' / stamp
        trace.write(archive / 'before.json', before)
        trace.write(archive / 'after.json', texts)
        changed = []
        try:
            for name, text in texts.items():
                target = trace.SOURCE / 'regrow/prompts' / name
                if target.read_text() != before[name]:
                    raise ValueError('写回前源码再次变化，请重新预览：' + name)
                target.write_text(text)
                changed.append(name)
        except (OSError, ValueError):
            for name in changed:
                target = trace.SOURCE / 'regrow/prompts' / name
                if target.read_text() == texts[name]:
                    target.write_text(before[name])
            trace.write(archive / 'result.json', {'status': 'rolled_back', 'job': ident})
            raise
        result = {'status': 'applied', 'job': ident, 'paths': list(texts),
                  'source': str(trace.SOURCE), 'backup': str(archive),
                  'note': '已写回本地源码；未自动认定语义通过、提交或部署。'}
        trace.write(archive / 'result.json', result)
        return result
