from tests.test_recovery_discovery import mod


def test_low_confidence_images_remain_bounded_identity_candidates():
    records={f'r{i}':{'observations':[{'image':f'image{i}'}],'controls':{}} for i in range(20)}
    def locate(path,frame):return {'accepted':False,'score':int(path[5:])/20,'box':[0,0,10,10]}
    p=mod('visual_region_locator').plan(records,None,'frame',locate=locate)
    assert p['mode']=='relocate'
    assert [r['region'] for r in p['regions']]==['r19','r18','r17']
    assert all(not r['strong'] and not r['whole']['accepted'] for r in p['regions'])
    assert p['controls']==[]


def test_working_region_is_recalled_even_below_visual_shortlist():
    records={f'r{i}':{'observations':[{'image':f'image{i}'}],'controls':{}} for i in range(20)}
    def locate(path,frame):return {'accepted':False,'score':int(path[5:])/20,'box':[0,0,10,10]}
    p=mod('visual_region_locator').plan(records,'r0','frame',force_relocate=True,locate=locate)
    assert p['regions'][0]['region']=='r0'
    assert not p['regions'][0]['strong'] and p['mode']=='relocate'
    assert len(p['regions'])<=8
