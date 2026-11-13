"""Parse complete model messages independently; never concatenate decisions."""
import json
import re

class ReplyParseError(ValueError):

    def __init__(self, reason, texts):
        self.detail = {'code': 'model_response_parse_error', 'reason': reason, 'reply_texts': texts}
        super().__init__(reason)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result and json.dumps(result[key], sort_keys=True) != json.dumps(value, sort_keys=True):
            error = ReplyParseError('同一对象的字段“' + key + '”出现不同取值', [])
            error.detail['errors'] = [{'code': 'duplicate_field', 'object': '字段“' + key + '”',
                'actual': [result[key], value], 'expected': '同一对象中的同名字段须无冲突'}]
            raise error
        result[key] = value
    return result


def _read(text):
    try:
        return json.loads(text, object_pairs_hook=_pairs)
    except json.JSONDecodeError:
        pass
    blocks = re.findall(r'```(?:json)?\s*\n([\s\S]*?)\n```', text, flags=re.I)
    if len(blocks) == 1:
        return json.loads(blocks[0], object_pairs_hook=_pairs)
    # Keep complete top-level JSON containers, never stitch a truncated reply.
    decoder = json.JSONDecoder(object_pairs_hook=_pairs)
    values, position = [], 0
    while position < len(text):
        if text[position] not in '{[':
            position += 1
            continue
        try:
            value, end = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            raise ValueError('invalid_json') from None
        values.append(value)
        position = end
    if len(values) > 1:
        raise ReplyParseError('conflicting_replies', [])
    if not values:
        raise ValueError('invalid_json')
    return values[0]

def reply_texts(body):
    texts = []
    if not isinstance(body, dict):
        return texts
    for item in body.get('output') or []:
        if item.get('type') != 'message':
            continue
        pieces = [block['text'] for block in item.get('content', []) if block.get('type') == 'output_text' and isinstance(block.get('text'), str)]
        if pieces:
            texts.append(''.join(pieces))
    if not texts and isinstance(body.get('output_text'), str):
        texts = [body['output_text']]
    return texts


def parse(body):
    if not isinstance(body, dict):
        raise ReplyParseError('invalid_response_object', [])
    texts = reply_texts(body)
    if body.get('status') in ('incomplete', 'failed', 'cancelled') or body.get('error'):
        raise ReplyParseError('incomplete_reply', texts)
    if not texts or not any((t.strip() for t in texts)):
        raise ReplyParseError('empty_reply', texts)
    values = {}
    for text in texts:
        try:
            value = _read(text)
        except ReplyParseError as error:
            error.detail['reply_texts'] = texts
            raise
        except (ValueError, TypeError):
            raise ReplyParseError('invalid_json', texts) from None
        if not isinstance(value, (dict, list)):
            raise ReplyParseError('non_object_reply', texts)
        values[json.dumps(value, sort_keys=True, ensure_ascii=False)] = value
    if len(values) != 1:
        raise ReplyParseError('conflicting_replies', texts)
    return next(iter(values.values()))
