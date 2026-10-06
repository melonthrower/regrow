from tests.test_stepwise_region_tasks import tasks


def test_update_context_keeps_local_route_and_visual_candidates_not_whole_graph():
    m=tasks().helper('result_updater')
    records={k:{'name':k,'description':k,'controls':{},'actions':{}} for k in ['source','work','visible','prior','destination','matched','unrelated']}
    records['source']['actions']['a']={'interactive_regions':['destination']}
    records['source']['actions']['other']={'control':'other_control','interactive_regions':['unrelated']}
    state={'interactive_regions':['visible'],'region_path':['unrelated','prior']}
    result=m.known_regions(records,state,{'region_ref':'source','working_region':'work'},[{'name':'matched'}])
    assert {r['name'] for r in result}=={'source','work','visible','prior','destination','matched'}
    assert 'unrelated' in records
