"""Select a single final structured answer without consuming commentary as actions."""
import json


def final_response_body(body):
    if not isinstance(body,dict) or body.get('status') not in {None,'completed'}:
        raise ValueError('response is not completed')
    messages=[item for item in body.get('output',[]) if isinstance(item,dict)
              and item.get('type')=='message' and item.get('role','assistant')=='assistant']
    finals=[item for item in messages if item.get('phase')=='final_answer']
    if finals:
        if len(finals)!=1:raise ValueError('multiple final answers; no action selected')
        selected=finals[0]
    elif len(messages)==1 and messages[0].get('phase') is None:
        selected=messages[0]
    elif messages:
        raise ValueError('no unique final answer; no action selected')
    else:
        selected=None
    if selected is not None:
        if selected.get('status') not in {None,'completed'}:raise ValueError('incomplete final message')
        text=''.join(c.get('text','') for c in selected.get('content',[]) if c.get('type')=='output_text')
    else:
        text=body.get('output_text','')
    try:parsed=json.loads(text)
    except (ValueError,TypeError):raise ValueError('final answer is not one JSON object') from None
    if not isinstance(parsed,dict):raise ValueError('final answer must be a JSON object')
    return dict(body,output_text=text)
