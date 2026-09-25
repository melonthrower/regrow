from pathlib import Path
import importlib.util
import json
import struct
import zlib
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'

def module():
    spec = importlib.util.spec_from_file_location('assembly', ROOT / 'assemble.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def png(path, width, height):
    def chunk(t, v):
        return struct.pack('>I', len(v)) + t + v + struct.pack('>I', zlib.crc32(t+v))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width,height,8,2,0,0,0)) + chunk(b'IDAT',zlib.compress((b'\0'+b'\0'*(3*width))*height)) + chunk(b'IEND',b''))

@pytest.mark.parametrize('label,size', [('Clock',(108,234)),('Timer',(108,234)),('Writer',(160,90))])
def test_app_independent_context_does_not_invent_state(tmp_path,label,size):
    shot=tmp_path/(label+'.png'); png(shot,*size)
    result=module().assemble(ROOT,shot,'saved_frame',None,None)
    d=json.loads(result['user_prompt'])
    assert d['frame']['width']==size[0] and d['frame']['height']==size[1]
    assert d['frame']['source']=='saved_frame'
    assert d['history']['status']=='not_provided'
    assert d['execution']['status']=='not_provided'
    assert label not in result['system_prompt']
    assert '默认' not in result['user_prompt'] and '清除' not in result['user_prompt']
    assert 'current_page' not in d

def test_empty_history_is_scoped_and_not_no_previous_actions(tmp_path):
    shot=tmp_path/'frame.png'; png(shot,10,20)
    r=module().assemble(ROOT,shot,'live_capture',[],None)
    d=json.loads(r['user_prompt'])
    assert d['history']=={'status':'provided','items':[]}
    assert d['execution']['status']=='not_provided'

def test_explicit_receipt_is_not_a_visual_default_claim(tmp_path):
    shot=tmp_path/'frame.png'; png(shot,10,20)
    events=[{'ref':'prepare-1','operation':'clear_app_data','receipt':'Success','visual_result':'unverified'}]
    r=module().assemble(ROOT,shot,'live_capture',[],events)
    d=json.loads(r['user_prompt'])
    assert d['execution']['items']==events
    assert 'default_page' not in d and 'current_page' not in d

def test_fixed_parts_independent_of_dynamic_history(tmp_path):
    shot=tmp_path/'frame.png'; png(shot,10,20)
    a=module().assemble(ROOT,shot,'saved_frame',None,None)
    b=module().assemble(ROOT,shot,'live_capture',[{'ref':'old','status':'proposal'}],[])
    assert a['system_prompt']==b['system_prompt']
    assert a['parts']==b['parts']

def test_edit_one_part_changes_only_that_part(tmp_path):
    import shutil
    root=tmp_path/'experiment'; shutil.copytree(ROOT/'遍历prompt',root/'遍历prompt')
    shot=tmp_path/'frame.png'; png(shot,10,20)
    a=module().assemble(root,shot,'saved_frame',None,None)
    target='区块识别/区块控件识别.prompt'
    p=root/'遍历prompt'/target; p.write_text(p.read_text()+'\n补充：辨别图标朝向。\n')
    b=module().assemble(root,shot,'saved_frame',None,None)
    assert [k for k in a['parts'] if a['parts'][k]!=b['parts'][k]]==[target]
    assert a['user_prompt']==b['user_prompt']

def test_invalid_source_rejected(tmp_path):
    shot=tmp_path/'frame.png'; png(shot,10,20)
    with pytest.raises(ValueError): module().assemble(ROOT,shot,'default_page',None,None)
