import importlib.util
from pathlib import Path
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
def module(name):
 s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def fixture(tmp_path):
 template=Image.new('RGB',(90,40),'white');d=ImageDraw.Draw(template);d.text((5,10),'Search city',fill='black');d.line((3,3,80,30),fill='black',width=2)
 scene=Image.new('RGB',(240,220),'white');scene.paste(template,(20,20));scene.paste(template,(110,150))
 a=tmp_path/'template.png';b=tmp_path/'frame.png';template.save(a);scene.save(b)
 q={'source':{'region':'r','observation':'o'},'image_refs':[str(b)],'screenshots':[str(b)],'backend_candidates':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','id':'c','name':'Search city','icon_description':'top input','image':str(a)}]}
 return q,{'action':'click','target':'Search city','x':50,'y':40,'reason':'顶部输入框'}

def test_candidates_require_explicit_disclosure_and_bounded_choice(tmp_path):
 q,p=fixture(tmp_path);flow=module('stepwise_flow');m=module('visual_choices')
 assert flow.bind_action_target(q,p)['status']=='unresolved'
 prepared=m.prepare(q)
 assert len(prepared['visual_choices']['c'])==2
 binding=flow.bind_action_target(prepared,p)
 assert binding['status']=='matched' and binding['visual_choice']['box']==[20,20,110,60]
 assert flow.bind_action_target(prepared,{**p,'x':230,'y':100})['status']=='unresolved'
 assert flow.bind_action_target(prepared,{**p,'target':'another input'})['status']=='unresolved'
 # Moving the scene must invalidate a previously disclosed candidate.
 im=Image.open(q['image_refs'][0]);changed=Image.new('RGB',im.size,'white');changed.paste(im,(15,0));changed.save(q['image_refs'][0])
 assert flow.bind_action_target(prepared,p)['status']=='unresolved'


def test_correction_envelope_carries_candidates_without_mutating_original(tmp_path):
    q,p=fixture(tmp_path)
    q.update(system_prompt='动作规则',user_prompt='选择顶部输入框',response_schema={'type':'object'})
    repair=module('step_repair')
    corrected=repair.request(ROOT,{'stage':'action','request':q,'history':[],'error':'ambiguous'}, {})
    assert 'visual_choices' not in q
    assert '候选位置' in corrected['user_prompt']
    assert '不能靠同名文字推断功能' in corrected['system_prompt']
    assert len(corrected['original_request']['visual_choices']['c'])==2
