from copy import deepcopy
import pytest
from tests.test_control_ownership_revision import case, tasks


def duplicate_case(tmp_path):
    run,d,job,move=case(tmp_path)
    def seed(records,state,*args):
        control=deepcopy(records['r1']['controls']['c1'])
        control['id']='existing';control['action_refs']=[];control['task_refs']=[]
        records['r2']['controls']['existing']=control
    d.publish(run,'duplicate-before-move',seed)
    merge={'region':'Content','control':'Policy','field':'merge_into','before':'Policy','after':'Policy','evidence':'Same recorded control in old and new owners'}
    return run,d,job,move,merge


@pytest.mark.parametrize('merge_first',[False,True])
def test_explicit_move_and_merge_is_atomic_and_order_independent(tmp_path,merge_first):
    run,d,job,move,merge=duplicate_case(tmp_path)
    before=deepcopy(d.load(run)[1]['r1']['tasks']['Policy'])
    tasks().helper('repair_stages').edit_record(None,run,job,[merge,move] if merge_first else [move,merge])
    _,records,_=d.load(run)
    assert 'c1' not in records['r1']['controls']
    assert list(records['r2']['controls'])==['existing']
    task=records['r2']['tasks']['Policy']
    assert task=={**before,'control':'existing'}
    assert any(x['id']=='c1' for x in records['r2']['controls']['existing']['merged_records'])


def test_moving_duplicate_without_explicit_merge_keeps_old_graph(tmp_path):
    run,d,job,move,merge=duplicate_case(tmp_path)
    before=(run/'knowledge_current.json').read_bytes()
    with pytest.raises(ValueError,match='同名控件'):
        tasks().helper('repair_stages').edit_record(None,run,job,move)
    assert (run/'knowledge_current.json').read_bytes()==before


def test_later_proposal_rejection_rolls_back_move_and_merge(tmp_path,monkeypatch):
    run,d,job,move,merge=duplicate_case(tmp_path)
    before=(run/'knowledge_current.json').read_bytes()
    stage=tasks().helper('repair_stages')
    def reject(*args):
        raise ValueError('proposal remains inconsistent')
    monkeypatch.setattr(stage,'accept_candidate',reject)
    with pytest.raises(ValueError,match='proposal remains inconsistent'):
        stage.accept(None,run,{**job,'record_edit':[move,merge]})
    assert (run/'knowledge_current.json').read_bytes()==before
    assert 'c1' in d.load(run)[1]['r1']['controls']


def test_region_merge_updates_scope_for_later_control_move(tmp_path):
    run,d,job,move=case(tmp_path)
    def seed(records,state,*args):
        records['r3']=tasks().helper('stepwise_flow').new_region('r3',records['r1']['name'],'duplicate region')
    d.publish(run,'duplicate-region',seed)
    name=d.load(run)[1]['r1']['name']
    job['request']['region_names']['duplicate source']='r3'
    merge={'region':name,'control':'','field':'merge_into','before':name,'after':name,'evidence':'Same source region'}
    tasks().helper('repair_stages').edit_record(None,run,job,[merge,move])
    _,records,_=d.load(run)
    assert 'r3' not in records
    assert 'c1' in records['r2']['controls']


def test_update_keeps_disclosed_labels_bound_after_region_merge(tmp_path,monkeypatch):
    run,d,job,move=case(tmp_path)
    def seed(records,state,*args):
        records['r3']=tasks().helper('stepwise_flow').new_region('r3',records['r1']['name'],'duplicate region')
    d.publish(run,'duplicate-labels',seed)
    name=d.load(run)[1]['r1']['name'];job['request']['region_names']['duplicate source']='r3'
    original=deepcopy(job['request'])
    merge={'region':name,'control':'','field':'merge_into','before':name,'after':name,'evidence':'Same source'}
    stage=tasks().helper('repair_stages')
    def accepted(root,run,updated):
        assert updated['request']['region_names']['duplicate source']=='r1'
        assert updated['request']['screenshots']==original['screenshots']
        return {'accepted':True}
    monkeypatch.setattr(stage,'accept_candidate',accepted)
    assert stage.accept(None,run,{**job,'record_edit':[merge,move]})=={'accepted':True}
    assert job['request']==original
