from copy import deepcopy
from PIL import Image,ImageDraw
from regrow.records.observations import frame_observation,save_region_images
from regrow.records.task_updates import observed_control

def test_semantic_tail_does_not_replace_visual_row_or_create_visibility(tmp_path):
    evidence={'source_call':'7','observation':'update:7'}
    region_box={'left':0,'top':0,'right':64,'bottom':64}
    control_box={'left':5,'top':5,'right':50,'bottom':50}
    visual={'bbox':control_box,'evidence':{**evidence,'source_field':'/controls/0'}}
    knowledge={'knowledge':'功能更新','evidence':{**evidence,'basis':'observation_only'}}
    region={'id':'r1','name':'Panel','observations':[{'bbox':region_box,'evidence':{**evidence,'source_field':'/regions/0'}}],
      'controls':{'c1':{'name':'Visible','observations':[visual,deepcopy(knowledge)]},'c2':{'name':'Not reported','observations':[deepcopy(knowledge)]}}}
    assert frame_observation(region['controls']['c1'],kind='controls',call='7') is visual
    assert not frame_observation(region['controls']['c2'],kind='controls',call='7')
    state={'interactive_regions':['r1'],'observation':{'id':'update:7'}}
    assert observed_control(region,{'control':'c1'},state)
    assert not observed_control(region,{'control':'c2'},state)
    im=Image.new('RGB',(64,64),'red');ImageDraw.Draw(im).rectangle((32,0,63,63),fill='blue');im.save(tmp_path/'screen.png')
    save_region_images({'r1':region},['r1'],{'regions':[{'bbox':region_box}],'controls':[{'bbox':control_box}]},'7',tmp_path,'screen.png',tmp_path/'snapshot',tmp_path/'staging',observation='update:7')
    assert (tmp_path/'staging'/visual['image']).is_file()
    assert 'image' not in region['controls']['c1']['observations'][-1]
    assert 'source_image' not in region['controls']['c2']['observations'][-1]


def test_visual_matching_and_old_frame_do_not_count_as_current_semantic_observation():
    record={'observations':[{'evidence':{'source_call':'1','observation':'old','source_field':'/controls/0'}},
        {'visual_only':True,'evidence':{'source_call':'2','observation':'current','source_field':'/controls/0'}}]}
    assert not frame_observation(record,observation='current')
    assert not frame_observation(record,call='2')
    assert frame_observation(record,call='1')
