from copy import deepcopy
import pytest
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks


def test_multiple_controls_share_new_partition(tmp_path):
    run,q,d=setup(tmp_path);snapshot,records,state=d.load(run)
    controls=list(records['r1']['controls']);old_tasks=set(records['r1']['tasks'])
    ep={'source_region':'r1','assignments':{cid:{'region':'Shared tabs','description':'Common tab navigation','call':'review','frame':'frame.png','evidence':'visible tab'} for cid in controls},'conflicts':{}}
    moved=tasks().helper('ownership_review').repartition(records,state,ep,snapshot)
    assert len(set(moved.values()))==1
    dest=records[next(iter(moved.values()))]
    assert set(dest['controls'])==set(controls) and set(dest['tasks'])==old_tasks
    assert records['r1']['controls']=={}
    assert records['r1']['partition_children']==[dest['id']]


def test_unrelated_same_name_remains_rejected(tmp_path):
    run,q,d=setup(tmp_path);snapshot,records,state=d.load(run)
    records['r2']=deepcopy(records['r1']);records['r2'].update(id='r2',name='Shared tabs')
    ep={'source_region':'r1','assignments':{'c1':{'region':'Shared tabs'}},'conflicts':{}}
    with pytest.raises(ValueError,match='collides'):
        tasks().helper('ownership_review').repartition(records,state,ep,snapshot)
