from copy import deepcopy
import pytest
from gui_rewalk.src.core.evidence_explore.response import final_response_body


def msg(text,phase=None):
    item=dict(type='message',role='assistant',status='completed',content=[dict(type='output_text',text=text)])
    if phase:item['phase']=phase
    return item


def test_selects_explicit_final_without_merging_commentary():
    body=dict(status='completed',usage={'input_tokens':10},output=[msg('{"action":"scroll"}','commentary'),msg('{"action":"click"}','final_answer')])
    original=deepcopy(body);result=final_response_body(body)
    assert result['output_text']=='{"action":"click"}' and result['usage']==body['usage']
    assert body==original


@pytest.mark.parametrize('body',[
    dict(output=[msg('{}'),msg('{}')]),
    dict(output=[msg('{}','final_answer'),msg('{}','final_answer')]),
    dict(output=[msg('{}','commentary')]),
    dict(status='incomplete',output=[msg('{}','final_answer')]),
    dict(output=[msg('{}{}','final_answer')]),
])
def test_ambiguous_incomplete_or_invalid_answers_are_rejected(body):
    with pytest.raises(ValueError):final_response_body(body)


def test_single_unphased_response_remains_supported():
    assert final_response_body(dict(output=[msg('{}')]))['output_text']=='{}'
    assert final_response_body(dict(output_text='{}'))['output_text']=='{}'
