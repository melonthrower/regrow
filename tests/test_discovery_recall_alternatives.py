from tests.test_discovery_incremental import module


def test_exact_hint_does_not_hide_explicitly_named_alternative():
    records={'a':{'name':'图像工具'},'b':{'name':'页面铅笔工具'},'c':{'name':'页面工具'}}
    q={'previous_name':'图像工具','identity':'uncertain','identity_evidence':'尚不能排除页面铅笔工具','uncertainty':'右缘被裁切'}
    assert set(module().retrieve(records,[q]))=={'a','b'}


def test_english_mentions_require_whole_name_and_keep_duplicate_candidates():
    records={'a':{'name':'Insert image'},'b':{'name':'Page pencil'},'b2':{'name':'Page pencil'},'c':{'name':'Page pen'}}
    q={'previous_name':'Insert image','uncertainty':'Could instead be Page pencil.'}
    assert set(module().retrieve(records,[q]))=={'a','b','b2'}
    assert len(module().retrieve(records,[q],limit=2))==2


def test_short_name_inside_named_alternative_is_not_an_extra_candidate():
    records={'a':{'name':'图像工具'},'b':{'name':'笔刷工具'},'c':{'name':'笔刷'}}
    q={'previous_name':'图像工具','uncertainty':'也可能是笔刷工具'}
    assert set(module().retrieve(records,[q]))=={'a','b'}
    assert q['uncertainty']=='也可能是笔刷工具'


def test_supplement_keeps_original_local_candidates_for_omission_check(tmp_path):
    from tests.test_discovery_incremental import seed, ROOT
    m,run,q,reply=seed(tmp_path)
    q['discovery_context'].update(mode='local',control_names={'Other visible tool':'c2','Outside owner':'c9'})
    records={'r0001':{'name':'Toolbar','controls':{'c1':{'name':'Image tool'},'c2':{'name':'Other visible tool'}}},
             'r0002':{'name':'Other region','controls':{'c9':{'name':'Outside owner'}}}}
    frame=run/'frame.png'
    batch={'frame':str(frame.resolve()),'sha256':module().fingerprint(frame),'request':q,'regions':['r0001'],'controls':[],
           'pending':[{'item':'Image tool','proposal':{'name':'Image tool','identity':'uncertain','previous_name':'Image tool'}}]}
    result=module().supplement(ROOT,records,{'discovery_completion':batch},str(frame))
    assert set(result['discovery_context']['control_names'])=={'Image tool','Other visible tool'}
    assert 'Outside owner' not in result['user_prompt']
