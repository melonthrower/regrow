"""Parse complete model messages independently; never concatenate decisions."""
import json


class ReplyParseError(ValueError):
    def __init__(self,reason,texts):
        self.detail={'code':'model_response_parse_error','reason':reason,'reply_texts':texts}
        super().__init__(reason)


def parse(body):
    texts=[]
    if not isinstance(body,dict):raise ReplyParseError('invalid_response_object',texts)
    for item in body.get('output') or []:
        if item.get('type')!='message':continue
        pieces=[block['text'] for block in item.get('content',[]) if block.get('type')=='output_text' and isinstance(block.get('text'),str)]
        if pieces:texts.append(''.join(pieces))
    if not texts and isinstance(body.get('output_text'),str):texts=[body['output_text']]
    if body.get('status') in ('incomplete','failed','cancelled') or body.get('error'):
        raise ReplyParseError('incomplete_reply',texts)
    if not texts or not any(t.strip() for t in texts):raise ReplyParseError('empty_reply',texts)
    values={}
    for text in texts:
        try:value=json.loads(text)
        except (ValueError,TypeError):raise ReplyParseError('invalid_json',texts) from None
        if not isinstance(value,dict):raise ReplyParseError('non_object_reply',texts)
        values[json.dumps(value,sort_keys=True,ensure_ascii=False)]=value
    if len(values)!=1:raise ReplyParseError('conflicting_replies',texts)
    return next(iter(values.values()))
