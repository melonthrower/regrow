from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
@pytest.fixture(autouse=True)
def path(monkeypatch):monkeypatch.syspath_prepend(str(ROOT))

def proposal(**kw):return dict(action='scroll',target='list',x=700,y=500,end_x=None,end_y=None,dx=0,dy=-2,text=None,reason='inspect below',skip_task=False,request_task_review=False)|kw

@pytest.mark.parametrize('dx,dy,code',[(0,-2,'vscroll(-2)'),(0,2,'vscroll(2)'),(-3,0,'hscroll(-3)'),(3,0,'hscroll(3)')])
def test_osworld_wheel_sign(dx,dy,code):
 import action_commands as a
 p=proposal(dx=dx,dy=dy);a.validate(p,'desktop')
 assert code in a.commands(p,'desktop')[0]

@pytest.mark.parametrize('fields',[{'dx':0,'dy':0},{'dx':True,'dy':2},{'dy':None},{'end_y':800}])
def test_reject_ambiguous_wheel(fields):
 import action_commands as a
 with pytest.raises((ValueError, __import__("jsonschema").ValidationError)):a.validate(proposal(**fields),'desktop')

def test_nested_recovery_schema_and_android_unchanged():
 import action_commands as a
 original=a.schema();q={'response_schema':{'properties':{'proposal':{'anyOf':[original,{'type':'null'}]}}}}
 sent=a.platform_request(q,'desktop');nested=sent['response_schema']['properties']['proposal']['anyOf'][0]
 assert {'dx','dy'}<=set(nested['required'])
 assert 'dx' not in original['properties']
 assert 'dx' not in a.platform_request({'response_schema':original},'android')['response_schema']['properties']
 android=proposal(end_x=700,end_y=200);android.pop('dx');android.pop('dy')
 assert a.commands(android,'android')[0][2]=='swipe'


def test_recovery_resolves_wire_scroll_and_non_scroll():
 import recovery
 for action in [proposal(),proposal(action='click',dx=None,dy=None)]:
  reply={'exception':'blocking_popup','decision':'act','action':action,'framework_tool':None,'reason':'inspect obstruction','handoff':''}
  result=recovery.resolve(reply,'desktop')
  assert result['action']==action


def test_origin_binding_desktop_and_navigation(tmp_path,monkeypatch):
 from PIL import Image
 import desktop_scroll,image_match
 image=tmp_path/'frame.png';Image.new('RGB',(1000,800)).save(image)
 q={'image_refs':[str(image)],'region_image':str(image),'region_image_assessment':{'image_quality':'clear','image_quality_reason':'visible'},'allow_scroll':True}
 monkeypatch.setattr(image_match,'locate',lambda *args:{'accepted':True,'box':[600,400,800,600]})
 assert desktop_scroll.bind(q,proposal())['status']=='matched'
 assert desktop_scroll.bind(q,proposal(x=100))['status']=='unresolved'
 assert desktop_scroll.bind({**q,'navigation_advice':True},proposal(x=100))['status']=='matched'
 assert desktop_scroll.bind({**q,'navigation_advice':True},proposal(x=1001))['status']=='unresolved'
