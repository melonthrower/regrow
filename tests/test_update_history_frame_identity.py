from pathlib import Path
import json
import numpy as np
import pytest
from PIL import Image
from tests.test_recovery_discovery import seeded_run,mod,ROOT


@pytest.mark.parametrize('current_matches',[True,False])
def test_update_with_history_identifies_and_crops_current_after_frame(tmp_path,current_matches):
    run=seeded_run(tmp_path);m=mod('register_update');snapshot,records,_=mod('discovery_step').load(run)
    old=run/'returned.png'
    different=run/'different.png';Image.fromarray(np.random.default_rng(71).integers(0,256,(80,50,3),dtype=np.uint8)).save(different)
    after=old if current_matches else different;history=different if current_matches else old
    folder=run/'action_attempts/a2';folder.mkdir()
    for name,data in [('binding.json',{'status':'matched','region_ref':'r1','control_ref':'c1','observation_ref':'o1'}),('dispatch.json',{'source_region':'r1','source_control':'c1','source_call':'choice'}),('receipt.json',{'exit_code':0})]:
        (folder/name).write_text(json.dumps(data))
    call=run/'calls/0002';call.mkdir()
    q={'pipeline_step':'update','screenshots':[str(old),str(after),str(history)]}
    reply=json.loads((run/'calls/0001/response.json').read_text());reply['action_result']['exception']='none'
    reply['previous_regions']=[]
    reply['regions']=[{'name':'Observed panel','previous_name':'','parent_index':None,'description':'panel','reason':'visible','bbox':{'left':0,'top':0,'right':50,'bottom':80}}]
    reply['controls']=[]
    (call/'request.json').write_text(json.dumps(q));(call/'response.json').write_text(json.dumps(reply))
    pointer=m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a2')
    path=run/pointer['snapshot'];state=json.loads((path/'runtime_state.json').read_text());target=state['interactive_regions'][0]
    assert (target=='r1') is current_matches
    assert Path(state['observation']['image'])==after
    dest=json.loads((path/'regions'/target/'region.json').read_text())
    image=(path/'regions'/target/dest['observations'][-1]['image']).resolve()
    assert np.array_equal(np.asarray(Image.open(image)),np.asarray(Image.open(after)))
    assert json.loads((call/'response.json').read_text())==reply


def test_update_missing_after_frame_is_not_replaced_by_before(tmp_path):
    run=seeded_run(tmp_path)
    with pytest.raises(ValueError,match='前后'):
        mod('region_identity').for_request(run,{'pipeline_step':'update','screenshots':['returned.png']},{'regions':[],'controls':[]})
