"""Build a repair candidate; the caller alone may perform the GUI trial."""
from pathlib import Path
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from debug_loop import read,write,source_hash,freeze

REL=Path('experiments/clock_manual_20260919')
PROMPTS=Path(__file__).resolve().parent/'遍历prompt/监督'


def object_schema(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}

VERDICT=object_schema({'accepted':{'type':'boolean'},'reason':{'type':'string'}})
PROPOSAL=object_schema({'summary':{'type':'string'},'tests':{'type':'array','items':{'type':'string'}},'replay_request':{'type':'string'}})


def repo_root(path):
    for p in [Path(path),*Path(path).parents]:
        if (p/'gui_rewalk').is_dir() and (p/'tests').is_dir():return p
    raise ValueError('cannot find repository for candidate dependencies')


def workspace(repo,source,dest):
    """Copy code dependencies, never historical runs, credentials or symlink trees."""
    dest.mkdir(parents=True)
    for top in ('gui_rewalk','tests'):
        for p in (repo/top).rglob('*'):
            if p.is_symlink() or not p.is_file() or '__pycache__' in p.parts:continue
            if p.suffix not in ('.py','.json','.txt','.yaml','.yml','.md'):continue
            if any(part in ('artifacts','results','.git','configs','config','local') for part in p.relative_to(repo/top).parts[:-1]):continue
            out=dest/p.relative_to(repo);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out)
    freeze(source,dest/REL)
    for name in ('pytest.ini','pyproject.toml','conftest.py'):
        if (repo/name).is_file():shutil.copy2(repo/name,dest/name)
    return dest/REL


def codex(cwd,out,prompt,schema,write_access=False,images=()):
    out.mkdir(parents=True,exist_ok=False);(out/'prompt.txt').write_text(prompt);write(out/'schema.json',schema)
    command=['codex','exec','--skip-git-repo-check','--ephemeral','--sandbox','workspace-write' if write_access else 'read-only','--output-schema',str(out/'schema.json'),'-o',str(out/'response.json'),'-C',str(cwd),'--json']
    for image in images:command+=['--image',str(image)]
    command+=['-']
    write(out/'invocation.json',{'argv':command,'started_at':time.time()})
    with (out/'events.jsonl').open('w') as log:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,text=True,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        timed_out=False
        try:proc.communicate(prompt,timeout=900)
        except subprocess.TimeoutExpired:
            timed_out=True;os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        finally:write(out/'receipt.json',{'exit_code':proc.returncode,'timed_out':timed_out,'finished_at':time.time()})
    if timed_out or proc.returncode:raise RuntimeError('development/review agent failed; see '+str(out))
    reply=read(out/'response.json');import jsonschema;jsonschema.validate(reply,schema);return reply


def tree_files(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts}


def reader_paths(changed):
    return [p for p in changed if p.startswith(str(REL)+'/') or p.startswith('tests/test_debug_regression_') or p in ('replay/build.py','replay/request.json')]


def assert_scope(before,after):
    changed={p for p in set(before)|set(after) if before.get(p)!=after.get(p)}
    for p in changed:
        if p in (str(REL/'debug_loop.py'),str(REL/'debug_candidate.py')):
            raise ValueError('supervisor changes require explicit restart; repair graph progress in debug_progress.py')
        allowed=(p.startswith(str(REL)+'/') and Path(p).suffix in ('.py','.md','.prompt','.schema','.json')) or (p.startswith('tests/test_debug_regression_') and p.endswith('.py') and p not in before) or p.startswith('replay/')
        if not allowed:raise ValueError('candidate changed outside repair scope: '+p)
        if p in before and p not in after:raise ValueError('candidate deleted existing file: '+p)
    if not any(p.startswith(str(REL)+'/') for p in changed):raise ValueError('no framework change')
    return sorted(changed)


def pytest_run(repo,source,tests,out):
    env={**os.environ,'PYTHONPATH':str(source)+os.pathsep+str(repo),'GUI_REWALK_TEST_SOURCE':str(source),'PYTHONDONTWRITEBYTECODE':'1'}
    command=[sys.executable,'-m','pytest',*tests,'-q','-p','no:cacheprovider','--basetemp',str(out/'tmp')]
    out.mkdir(parents=True);write(out/'invocation.json',{'argv':command,'source':str(source)})
    with (out/'output.log').open('w') as log:proc=subprocess.run(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    write(out/'receipt.json',{'exit_code':proc.returncode});return proc.returncode


def retry_http(send,before_attempt,pause=time.sleep):
    """Retry transient HTTP responses only; preserve the exact request."""
    for number in range(1,4):
        before_attempt(number)
        response=send()
        if response.status_code not in (408,429,500,502,503,504) or number==3:return response
        pause(5)


def luna(request,out,before_request=None):
    """Real saved-frame model call, no action tool and no GUI dispatch."""
    repository=str(repo_root(Path(__file__).resolve()))
    if repository not in sys.path:sys.path.insert(0,repository)
    from gui_rewalk.src.core.explore import agent as transport
    from gui_rewalk.src.core.explore.api_config import load_explore_api_config,local_explore_api_config_path
    from model_reply_parse import parse
    out.mkdir(parents=True);write(out/'request.json',request)
    cfg=load_explore_api_config(local_explore_api_config_path())
    agent=transport.OpenAIAPIExplorerAgent(base_url=cfg.base_url,api_key=cfg.api_key,model=cfg.model,reasoning_effort='medium',output_root=str(out),timeout=180)
    original=transport.requests.post;count=0
    def post(*args,**kwargs):
        nonlocal count
        if count:raise RuntimeError('saved-frame call already submitted')
        def charge(number):
            nonlocal count
            if before_request:before_request()
            count+=1;write(out/'accounting.json',{'http_started':count,'model':cfg.model,'gui_started':0})
        def send():
            response=original(*args,**kwargs)
            write(out/'attempts'/f'{count:04d}.json',{'status':response.status_code})
            return response
        response=retry_http(send,charge)
        write(out/'http.json',{'status':response.status_code})
        if response.ok:
            body=response.json();write(out/'raw_response.json',body);value=parse(body)
            normalized={**body,'output_text':json.dumps(value,ensure_ascii=False)};response.json=lambda:normalized
        return response
    transport.requests.post=post
    try:
        value=agent._call(role=request['role'],system_prompt=request['system_prompt'],user_prompt=request['user_prompt'],screenshots=[Path(p).read_bytes() for p in request['screenshots']],response_schema=request['response_schema'])
        import jsonschema;jsonschema.validate(value,request['response_schema'])
        write(out/'response.json',value);write(out/'usage.json',agent._last_api_usage);return value
    finally:transport.requests.post=original


def validate_replay_evidence(incident, request):
    """Preserve original images, or the original text-only function evidence."""
    incident = Path(incident)
    frames = request.get('screenshots')
    if frames:
        hashes = {hashlib.sha256(p.read_bytes()).digest()
                  for p in (incident / 'calls').glob('*/frame-*.png')}
        if any(hashlib.sha256(Path(p).read_bytes()).digest() not in hashes for p in frames):
            raise ValueError('replay must use incident screenshots')
        return
    try:
        refs = read(incident / 'references.json')
        run = Path(refs['run'])
        rid = request['source']['region']
        region = read(run / refs['snapshot']['snapshot'] / 'regions' / rid / 'region.json')
        episode = region['registration_gaps']['function_registration']['episode']
        original = read(run / episode)['request']
        for value in (original, request):
            if not (value.get('stage') == value.get('role') == 'function_registration'
                    and value.get('screenshots') == [] and value.get('image_refs') == []
                    and value.get('action_ready') is False and value['source']['region'] == rid):
                raise ValueError('not an original text-only function request')
        if json.loads(original['user_prompt']) != json.loads(request['user_prompt']):
            raise ValueError('replay changed historical function evidence')
    except (OSError, TypeError, KeyError, ValueError) as exc:
        raise ValueError('missing or changed original text-only evidence: ' + str(exc)) from exc


def repair_candidate(source,incident,before_luna=None,stopped=lambda:False):
    source=Path(source);incident=Path(incident);repo=repo_root(Path(__file__).resolve())
    candidate=incident/'candidate';new_source=workspace(repo,source,candidate);before=tree_files(candidate)
    context={'incident':str(incident),'source':str(new_source),'baseline':str(source),'python':sys.executable,'previous_feedback':read(incident/'previous_feedback.json',{})}
    result={'accepted':False}
    try:
        if stopped():raise RuntimeError('paused before candidate development')
        plan=codex(candidate,incident/'developer',(PROMPTS/'修复候选.prompt').read_text()+'\n'+json.dumps(context,ensure_ascii=False),PROPOSAL,True)
        changed=assert_scope(before,tree_files(candidate));write(incident/'changed_files.json',changed)
        tests=plan['tests']
        if not tests or any(not t.startswith('tests/test_debug_regression_') or '..' in t or t.split('::')[0] in before for t in tests):raise ValueError('need new focused regression tests')
        baseline=pytest_run(candidate,source,tests,incident/'baseline_test')
        baseline_log=(incident/'baseline_test/output.log').read_text()
        if baseline==0 or 'ERROR collecting' in baseline_log or ' failed' not in baseline_log:raise ValueError('baseline must reproduce the behavior failure, not an import failure')
        if pytest_run(candidate,new_source,tests,incident/'candidate_test'):raise ValueError('candidate regression failed')
        digest=source_hash(new_source)
        images=sorted((incident/'calls').glob('*/frame-*.png'))[-2:]
        # First reader is not told the developer's explanation or intended answer.
        if stopped():raise RuntimeError('paused before independent review')
        write(incident/'reader_files.json',reader_paths(changed))
        independent=codex(candidate,incident/'reader',(PROMPTS/'陌生读者.prompt').read_text()+'\n审查源码:'+str(new_source)+'\n修改清单:'+str(incident/'reader_files.json'),object_schema({'reading':{'type':'string'},'issues':{'type':'array','items':{'type':'string'}}}),images=images)
        if stopped():raise RuntimeError('paused before intent comparison')
        comparison=codex(candidate,incident/'comparison',(PROMPTS/'意图对照.prompt').read_text()+'\n'+json.dumps({'incident':str(incident/'issue.json'),'developer':plan,'independent':independent},ensure_ascii=False),VERDICT,images=images)
        if not comparison['accepted']:raise ValueError('unfamiliar reader rejected candidate: '+comparison['reason'])
        request_path=(candidate/plan['replay_request']).resolve()
        if not request_path.is_relative_to(candidate/'replay'):raise ValueError('replay request must be in candidate/replay')
        build=candidate/'replay/build.py'
        if not build.is_file():raise ValueError('candidate must provide a replay builder')
        expected=read(request_path);request_path.unlink()
        command=[sys.executable,str(build)]
        with (incident/'replay_build.log').open('w') as log:
            proc=subprocess.run(command,cwd=candidate,env={**os.environ,'PYTHONPATH':str(new_source)+os.pathsep+str(candidate)},stdout=log,stderr=subprocess.STDOUT,timeout=60)
        write(incident/'replay_build_receipt.json',{'argv':command,'exit_code':proc.returncode})
        if proc.returncode:raise ValueError('candidate replay builder failed')
        q=read(request_path)
        if q!=expected:raise ValueError('replay request was not reproducible')
        # Use evidence frames; do not accept a fabricated demonstration image.
        validate_replay_evidence(incident,q)
        if stopped():raise RuntimeError('paused before saved-frame validation')
        response=luna(q,incident/'luna',before_luna)
        if stopped():raise RuntimeError('paused before semantic review')
        verdict=codex(candidate,incident/'luna_review',(PROMPTS/'模型回复验收.prompt').read_text()+'\n'+json.dumps({'issue':read(incident/'issue.json'),'source':str(new_source),'request':str(request_path),'response':response},ensure_ascii=False),VERDICT,images=q['screenshots'])
        if not verdict['accepted']:raise ValueError('saved-frame semantic validation failed: '+verdict['reason'])
        if source_hash(new_source)!=digest:raise ValueError('source changed during validation')
        result={'accepted':True,'source':str(new_source),'source_hash':digest,'changed':changed,'gui_executed':False}
    except Exception as error:
        result['reason']=f'{type(error).__name__}: {error}'
        status=read(incident/'luna/http.json',{}).get('status')
        if status in (401,402,403,408,429,500,502,503,504):result.update(kind='service_blocked',http_status=status)
    write(incident/'candidate_result.json',result);return result
