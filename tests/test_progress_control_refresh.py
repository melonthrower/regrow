"""A stale page token must refresh before a single accepted control request."""
from pathlib import Path
import json
import re
import subprocess
import threading
import urllib.request
from regrow.tools.progress_window import server


def test_stale_page_recovers_pause_without_duplicate_operation():
    class Runner:
        output = None
        def __init__(self): self.pauses = 0
        def status(self): return {'running': False}
        def pause(self):
            self.pauses += 1
            return {'pause_requested': True}
    old = server(None, 'http://127.0.0.1:1', runner=Runner())
    current_runner = Runner()
    current = server(None, 'http://127.0.0.1:1', runner=current_runner)
    for app in (old, current): threading.Thread(target=app.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{old.server_port}/') as r:
            html = r.read().decode()
        token = re.search(r'name="run-token" content="([^"]+)"', html).group(1)
        source = Path(__file__).resolve().parents[1] / 'src/regrow/tools/progress_window.html'
        text = source.read_text()
        helper = text[text.index('async function postControl'):text.index('async function submit')]
        script = '''
const fs=require('fs');const input=JSON.parse(fs.readFileSync(0,'utf8'));
const meta={content:input.token};global.document={querySelector:()=>meta};
global.DOMParser=class{parseFromString(s){return {querySelector:()=>({content:s.match(/name="run-token" content="([^"]+)"/)[1]})}}};
const nativeFetch=global.fetch;const calls=[];
global.fetch=(path,options)=>{calls.push({path,method:options?.method});return nativeFetch(input.base+path,options)};
''' + helper + '''
(async()=>{const response=await postControl('/pause');if(response.status!==202)throw Error('pause not accepted');
if(calls.filter(c=>c.method==='POST').length!==2||calls.filter(c=>c.path==='/').length!==1)throw Error('unexpected retry');
console.log('stale request rejected; refreshed request accepted once');})().catch(e=>{console.error(e.message);process.exit(1)});
'''
        result = subprocess.run(['node', '-e', script], input=json.dumps({'token':token,'base':f'http://127.0.0.1:{current.server_port}'}), text=True, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert current_runner.pauses == 1
    finally:
        for app in (old, current): app.shutdown(); app.server_close()
