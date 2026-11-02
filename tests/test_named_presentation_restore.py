import json
from copy import deepcopy
from regrow.prompts.history_disclosure import project,structured_text
from regrow.recognition.named_references import render


def original():
    text=json.dumps({'控件':[{'ref':'c0001','name':'File'}],'任务':{'region':'r0001','control':'c0001'}},ensure_ascii=False)
    return {'role':'action_selection','user_prompt':text,'name_contract':{'names':{'r0001':'Menu bar','c0001':'File'},'paths':{}},'screenshots':['fresh.png']},text


def test_named_display_keeps_internal_material_and_current_frame():
    request,text=original();projected=project(request);before=deepcopy(projected)
    shown=render(projected)
    assert shown['user_prompt']!=before['user_prompt']
    assert json.loads(structured_text(shown))==json.loads(text)
    assert json.loads(structured_text(shown))['任务']['control']=='c0001'
    assert shown['screenshots']==['fresh.png'] and projected==before
    assert structured_text(render(shown))==structured_text(shown)


def test_user_edited_display_is_not_replaced_by_old_internal_material():
    request,text=original();projected=project(request);projected['user_prompt']+='\n用户明确更改了当前问题。'
    shown=render(projected)
    assert structured_text(shown)==shown['user_prompt']
    assert '用户明确更改' in structured_text(shown)
    assert structured_text(shown)!=text
