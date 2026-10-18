from pathlib import Path
import json
import sys
import time
RUN = Path(__file__).resolve().parent
ROOT = next((p for p in RUN.parents if (p / 'gui_rewalk').is_dir()))
sys.path.insert(0, str(ROOT))
from gui_rewalk.src.core.explore import agent as transport
from gui_rewalk.src.core.explore.api_config import load_explore_api_config, local_explore_api_config_path
manifest = json.loads((RUN / 'run_manifest.json').read_text())
source = Path(manifest['framework_source'])
sys.path.insert(0, str(source))
from regrow.runtime.model_reply_parse import parse
from regrow.runtime.model_reply_parse import ReplyParseError
call = RUN / 'calls' / sys.argv[1]
request = json.loads((call / 'request.json').read_text())

def save(p, v):
    with p.open('x') as f:
        json.dump(v, f, ensure_ascii=False, indent=2)
cfg = load_explore_api_config(local_explore_api_config_path())
agent = transport.OpenAIAPIExplorerAgent(base_url=cfg.base_url, api_key=cfg.api_key, model=cfg.model, reasoning_effort='medium', output_root=str(call), timeout=cfg.timeout_seconds)
original = transport.requests.post
count = 0

class NoRetry(BaseException):
    pass

def post(*args, **kwargs):
    global count
    if count:
        raise NoRetry('one request only')
    count += 1
    kwargs['json']['max_output_tokens'] = 10000
    kwargs['json']['text']['format'] = {'type': 'json_object'}
    save(call / 'wire_format.json', kwargs['json']['text']['format'])
    with (RUN / 'events.jsonl').open('a') as f:
        f.write(json.dumps({'type': 'model_request_started', 'call': call.name, 'model': cfg.model}) + '\n')
    start = time.time()
    try:
        response = original(*args, **kwargs)
    except transport.requests.RequestException as error:
        save(call / 'transport_error.json', {'exception_type': type(error).__name__, 'seconds': time.time() - start, 'response_returned': False, 'request_attempts': count})
        raise NoRetry('first request failed; see transport_error.json') from None
    save(call / 'http.json', {'status': response.status_code, 'seconds': time.time() - start})
    if response.ok:
        body = response.json()
        save(call / 'raw_response.json', body)
        try:
            result = parse(body)
        except ReplyParseError as error:
            save(call / 'parse_error.json', error.detail)
            raise
        normalized = {**body, 'output_text': json.dumps(result, ensure_ascii=False)}
        response.json = lambda : normalized
    else:
        save(call / 'http_error.json', {'status': response.status_code, 'body': response.text.replace(cfg.api_key, '[credential]').replace(cfg.base_url, '[endpoint]')})
    return response
transport.requests.post = post
try:
    result = agent._call(role=request['role'], system_prompt=request['system_prompt'], user_prompt=request['user_prompt'], screenshots=[(RUN / p).read_bytes() for p in request['screenshots']], response_schema=request['response_schema'])
    save(call / 'response.json', result)
    save(call / 'usage.json', agent._last_api_usage)
    print(json.dumps(result, ensure_ascii=False))
finally:
    transport.requests.post = original
