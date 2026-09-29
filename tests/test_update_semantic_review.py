"""An external update audit gates publication without replaying the action."""
from copy import deepcopy
import json
import pytest
from tests.test_recovery_discovery import ROOT, mod

@pytest.fixture(autouse=True)
def path(monkeypatch):monkeypatch.syspath_prepend(str(ROOT))

def fixture(tmp_path):
    frame=tmp_path/'after.png';frame.write_bytes(b'original frame')
    (tmp_path/'knowledge_current.json').write_text('{"snapshot":"pre"}')
    return {'path':'repair_episodes/e/episode.json','stage':'update','call':'1','attempt':'a1',
            'request':{'screenshots':['after.png'],'source':{'region':'r1'}},
            'candidate':{'controls_complete':True},'history':[],'requires_update_review':True}

def verdict(ok):return {'accepted':ok,'reason':'Visible icon omitted' if not ok else 'Current proposal checked',
                        'evidence':['after.png: lower-left mode icon']}

def test_rejected_review_keeps_candidate_and_evidence(tmp_path):
    m=mod('update_semantic_review');job=fixture(tmp_path);before=deepcopy(job)
    with pytest.raises(m.Rejected,match='Visible icon omitted'):
        m.check(tmp_path,job,lambda evidence: verdict(False))
    assert job==before
    artifact=next((tmp_path/'repair_episodes/e/update_reviews').glob('*.json'))
    saved=json.loads(artifact.read_text());assert saved['verdict']==verdict(False)
    assert saved['evidence']['candidate']==job['candidate']
    assert (tmp_path/'knowledge_current.json').read_text()=='{"snapshot":"pre"}'

def test_approval_is_bound_to_proposal_frame_and_graph(tmp_path):
    m=mod('update_semantic_review');job=fixture(tmp_path);calls=[]
    def approve(evidence):calls.append(evidence);return verdict(True)
    m.check(tmp_path,job,approve);m.check(tmp_path,job,approve);assert len(calls)==1
    job['candidate']['controls_complete']=False;m.check(tmp_path,job,approve)
    (tmp_path/'after.png').write_bytes(b'new frame');m.check(tmp_path,job,approve)
    (tmp_path/'knowledge_current.json').write_text('{"snapshot":"later"}');m.check(tmp_path,job,approve)
    assert len(calls)==4

def test_pending_missing_or_invalid_review_never_approves(tmp_path):
    m=mod('update_semantic_review');job=fixture(tmp_path)
    for reviewer in [None,lambda evidence:None]:
        with pytest.raises(m.Pending):m.check(tmp_path,job,reviewer)
    with pytest.raises(RuntimeError):m.check(tmp_path,job,lambda evidence:{'accepted':'yes'})
    m.check(tmp_path,job,lambda evidence:verdict(True))
    saved=json.loads(next((tmp_path/'repair_episodes/e/update_reviews').glob('*.json')).read_text())
    assert saved['invalid_verdicts']==[{'accepted':'yes'}]

def test_actual_submission_change_invalidates_approval(tmp_path):
    m=mod('update_semantic_review');job=fixture(tmp_path);calls=[]
    folder=tmp_path/'calls/1';folder.mkdir(parents=True)
    (folder/'response.json').write_text('{"original":true}')
    def reviewer(evidence):calls.append(evidence);return verdict(True)
    m.check(tmp_path,job,reviewer)
    (folder/'response.json').write_text('{"changed":true}')
    m.check(tmp_path,job,reviewer)
    assert len(calls)==2

def test_episode_and_actual_submission_must_agree(tmp_path):
    m=mod('update_semantic_review');job=fixture(tmp_path)
    folder=tmp_path/'calls/1';folder.mkdir(parents=True)
    (folder/'request.json').write_text(json.dumps(job['request']))
    (folder/'response.json').write_text(json.dumps(job['candidate']))
    m.check(tmp_path,job,lambda evidence:verdict(True))
    (folder/'response.json').write_text('{"controls_complete":false}')
    with pytest.raises(m.Pending,match='不一致'):
        m.check(tmp_path,job,lambda evidence:pytest.fail('stale episode reviewed'))

def test_callback_cannot_mutate_submitted_candidate(tmp_path):
    m=mod('update_semantic_review');job=fixture(tmp_path)
    def reviewer(evidence):evidence['candidate'].clear();return verdict(True)
    m.check(tmp_path,job,reviewer)
    assert job['candidate']=={'controls_complete':True}

def test_evidence_change_during_review_cannot_publish(tmp_path):
    m=mod('update_semantic_review');job=fixture(tmp_path)
    def reviewer(evidence):
        (tmp_path/'after.png').write_bytes(b'changed during review')
        return verdict(True)
    with pytest.raises(m.Pending,match='发生变化'):m.check(tmp_path,job,reviewer)

def test_runner_rejects_before_accept_and_resume_keeps_review(tmp_path,monkeypatch):
    m=mod('step_repair');job=fixture(tmp_path)
    job.update(status='accept',seen=[],repairs=0,observations=0,supplements=[])
    m.atomic(tmp_path/job['path'],job);m.atomic(tmp_path/'pending_step.json',{'episode':job['path']})
    calls=[]
    runner=m.Runner(ROOT,tmp_path,lambda q:pytest.fail('budget is zero'),None,lambda:0,
                    review_update=lambda evidence:verdict(False))
    monkeypatch.setattr(runner.adapters,'accept',lambda *args:calls.append('published'))
    with pytest.raises(m.Paused,match='额度'):runner.perform('update')
    rejected=m.pending(tmp_path)
    assert rejected['status']=='repair' and rejected['blocked_by']=='review_required' and not calls
    # Model's corrected proposal is a new acceptance candidate; a resumed runner
    # without the required review provider cannot silently publish it.
    rejected.update(status='accept',candidate={'controls_complete':False},call='2')
    m.atomic(tmp_path/rejected['path'],rejected)
    resumed=m.Runner(ROOT,tmp_path,None,None,lambda:0)
    monkeypatch.setattr(resumed.adapters,'accept',lambda *args:calls.append('published'))
    with pytest.raises(m.Paused) as error:resumed.perform('update')
    assert error.value.status=='review_pending' and not calls
