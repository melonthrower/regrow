"""Control votes are evidence for identity recall, never an identity decision."""
from copy import deepcopy
import json
import pytest
from tests.test_recovery_discovery import ROOT, mod


@pytest.fixture(autouse=True)
def module_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))


def region(n):
    return {'name':'panel','observations':[], 'controls':{str(i):{'name':f'button {i}',
        'observations':[{'image':f'c{i}','image_quality':'clear','image_quality_reason':'verified'}]*2}
        for i in range(n)}}


def locate(path, scene=None):
    i=int(str(path)[1:]);return {'accepted':True,'score':.9,'box':[i*20,0,i*20+10,10]}


def test_nine_distinct_controls_outrank_eight_without_assigning_identity():
    m=mod('history_matching');rs={'r1':region(8),'r2':region(9)};before=deepcopy(rs)
    rows=[m.match_region(rid,r,locate,'frame') for rid,r in rs.items()]
    ordered=m.rank(rows)
    assert [(r['region'],r['matched_controls']) for r in ordered]==[('r2',9),('r1',8)]
    assert all(not r['strong'] for r in rows)
    assert rs==before


def test_duplicate_templates_and_same_current_position_contribute_one_vote():
    m=mod('history_matching');r=region(9)
    def same(path,scene=None):return {'accepted':True,'score':.8+int(str(path)[1:])/100,'box':[20,20,30,30]}
    row=m.match_region('r',r,same,'frame')
    assert row['matched_controls']==1 and row['eligible_controls']==9
    assert row['anchors'][0]['control']=='8'


def test_unreviewed_controls_never_vote():
    m=mod('history_matching');r=region(9)
    for c in r['controls'].values():
        for o in c['observations']:o.pop('image_quality',None)
    row=m.match_region('r',r,lambda *a:pytest.fail('unreviewed template used'),'frame')
    assert row['matched_controls']==row['eligible_controls']==0 and row['total_controls']==9


def test_history_append_preserves_current_frame_order_and_refuses_bad_crop(tmp_path):
    m=mod('history_matching');rs={'r1':region(1),'r2':region(1)}
    for rid,quality in [('r1','clear'),('r2','occluded')]:
        p=tmp_path/(rid+'.png');p.write_bytes(b'reference')
        rs[rid]['observations']=[{'image':str(p),'image_quality':quality,'image_quality_reason':'reviewed'}]
    rows=[m.match_region(rid,r,lambda path,*a:locate(path) if str(path).startswith('c') else {'accepted':False},'frame') for rid,r in rs.items()]
    q={'screenshots':['before.png','after.png'],'user_prompt':'{}'}
    result=m.attach(q,rs,rows,{'one':'r1','two':'r2'})
    assert result['screenshots']==q['screenshots']
    assert json.loads(result['user_prompt'])['历史匹配对照']['参考图']==[]
    assert q['screenshots']==['before.png','after.png']


def test_discovery_supplement_drops_references_when_rebuilding_images(tmp_path):
    from tests.test_discovery_incremental import seed, module, ROOT
    m,run,q,reply=seed(tmp_path)
    q['user_prompt']=json.dumps({'历史匹配对照':{'参考图':[{'图号':2,'候选':'stale'}]}})
    q['screenshots'].append('stale.png')
    frame=run/'frame.png'
    records={'r0001':{'name':'Toolbar','controls':{},'observations':[]}}
    batch={'frame':str(frame.resolve()),'sha256':module().fingerprint(frame),'request':q,'regions':[],'controls':[],
           'pending':[{'item':'Toolbar','proposal':{'name':'Toolbar','identity':'uncertain','previous_name':'Toolbar'}}]}
    result=module().supplement(ROOT,records,{'discovery_completion':batch},str(frame))
    assert result['screenshots']==[str(frame)]
    assert json.loads(result['user_prompt'])['历史匹配对照']['参考图']==[]
