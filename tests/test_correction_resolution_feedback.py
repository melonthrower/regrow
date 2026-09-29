"""Protocol feedback identifies the correction fields that actually conflicted."""
from copy import deepcopy
from tests.test_stepwise_task_correction import saved, repair, Calls, answer, ROOT


def test_observe_with_proposal_reports_null_requirement_in_next_real_request(tmp_path):
    run,q,good=saved(tmp_path);bad=deepcopy(good);bad['operations'][0]['control']='unknown'
    calls=Calls(run,[bad,answer('observe',good),answer('revise',good)])
    result=repair().Runner(ROOT,run,calls,None,lambda:6).perform('task_proposal',q)
    assert result['status']=='complete'
    diagnostic=calls.requests[2]['user_prompt']
    assert 'resolution=observe' in diagnostic and 'proposal=null' in diagnostic
    assert '保留' in diagnostic
