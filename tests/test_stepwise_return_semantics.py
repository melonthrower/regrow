from copy import deepcopy
from tests.test_recovery_discovery import mod


def test_back_edges_are_observations_not_fixed_routes():
    m=mod('stepwise_flow')
    a={'operation':'back','control':None,'delivery':'executed_receipt_zero','result':{'exception':'none'}}
    records={'r':{'controls':{},'actions':{'a':a},'transitions':[{'attempt':'a','source_control':None,'target_region':'home'}]},
             'home':{'controls':{},'actions':{},'transitions':[]}}
    state={'interactive_regions':['r'],'observation':{'id':'o','control_refs':[]}}
    assert m.shortest_known_path(records,state,'home') is None
    assert '进入路径' in m.navigation_description(a)


def test_visible_return_and_regular_click_are_distinct():
    m=mod('stepwise_flow')
    assert m.contextual_return({'operation':'click','result':{'returns_to_previous':True}})
    assert not m.contextual_return({'operation':'click','result':{'description':'打开设置'}})




def test_registration_persists_return_description_without_changing_observed_result(tmp_path):
    import json
    from tests.test_region_registration import fixture,module,invoke,read_region
    run,graph,reply=fixture(tmp_path)
    reply['action_result']['returns_to_previous']=True
    (run/'calls/0001/response.json').write_text(json.dumps(reply))
    pointer=invoke(module(),run);region=read_region(run,pointer)
    action=region['actions']['a1']
    assert action['destination_behavior']=='history_dependent'
    assert '进入路径' in action['navigation_description']
    assert action['result']['description']==reply['action_result']['description']


def test_empty_observed_landing_requests_review_instead_of_inventing_target():
    from tests.test_recovery_discovery import ROOT
    from tests.test_region_registration import fixture
    # Routing only uses actually reported foreground Regions, not old return edges.
    update=mod('update_visibility')
    assert not update.has_interactive({'regions':[],'previous_regions':[]})
