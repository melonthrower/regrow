"""Evidence-bound supervisor decisions before an update is published.

The caller supplies the reviewer; this module never calls a model or a device.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


class Pending(RuntimeError):
    pass


class Rejected(ValueError):
    blocked_by = 'review_required'


def submission_files(run, call):
    folder=Path(run)/'calls'/str(call)
    return {name:hashlib.sha256((folder/name).read_bytes()).hexdigest() if (folder/name).exists() else None
            for name in ('request.json','response.json','effective_request.json','effective_candidate.json')}


def check(run, job, reviewer):
    run = Path(run)
    folder=run/'calls'/str(job.get('call'))
    if (folder/'request.json').exists() and (folder/'response.json').exists():
        from step_repair import submission
        submitted_request,submitted_candidate=submission(run,job['call'])
        if submitted_request != job['request'] or submitted_candidate != job['candidate']:
            raise Pending('实际提交文件与待审核提案不一致，不能沿用审核或发布')
    frames = []
    refs=list(job['request'].get('screenshots', []))+[item['image'] for item in job.get('supplements', [])]
    for ref in dict.fromkeys(refs):
        path = run / ref
        frames.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    evidence = {key: deepcopy(job.get(key)) for key in ('request', 'candidate', 'attempt', 'call', 'record_edit', 'supplements')}
    evidence.update(knowledge_current=json.loads((run/'knowledge_current.json').read_text()), frames=frames,
                    submission_files=submission_files(run,job.get('call')))
    digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    folder = (run/job['path']).parent/'update_reviews'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(digest+'.json')
    saved = json.loads(path.read_text()) if path.exists() else {'digest': digest, 'evidence': evidence}
    verdict = saved.get('verdict')
    if verdict is None:
        verdict = reviewer(deepcopy(evidence)) if reviewer else None
        saved['verdict'] = verdict
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(saved, ensure_ascii=False, indent=2)+'\n')
        temp.replace(path)
    if verdict is None:
        raise Pending('更新提案等待监督审核；原回复与证据已保存')
    if (json.loads((run/'knowledge_current.json').read_text()) != evidence['knowledge_current']
            or submission_files(run,job.get('call')) != evidence['submission_files']
            or any(hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest() != frame['sha256'] for frame in frames)):
        raise Pending('审核期间图记录或截图发生变化，需要重新审核')
    if (not isinstance(verdict, dict) or type(verdict.get('accepted')) is not bool
            or not isinstance(verdict.get('reason'), str) or not verdict['reason'].strip()
            or not isinstance(verdict.get('evidence'), list) or not verdict['evidence']
            or any(not isinstance(item, str) or not item.strip() for item in verdict['evidence'])):
        saved.setdefault('invalid_verdicts',[]).append(verdict)
        saved['verdict']=None
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(saved,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
        raise RuntimeError('更新审核结果格式不完整，不能发布或当作模型回复错误')
    if not verdict['accepted']:
        raise Rejected('监督审核拒绝：'+verdict['reason']+'；依据：'+'；'.join(verdict['evidence']))
