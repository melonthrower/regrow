from copy import deepcopy
from tests.test_recovery_discovery import mod


def test_changed_representative_keeps_named_role_not_current_data_identity():
    rs={'r':{'name':'Sounds','controls':{'c':{'name':'Sound option','list_group':''}}}}
    p={'regions':[{'previous_name':'Sounds'}],'controls':[{'region_index':0,'name':'Sound option','text':'Carbon','list_group':'device sounds','previous_name':''}]}
    old=deepcopy(p);audit=mod('region_identity').reuse_list_roles(rs,p)
    assert p['controls'][0]['previous_name']=='Sound option' and p['controls'][0]['text']=='Carbon'
    assert audit[0]['control']=='c'
    old['controls'][0]['list_group']=''
    assert mod('region_identity').reuse_list_roles(rs,old)==[]
    assert old['controls'][0]['previous_name']==''
