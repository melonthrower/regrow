import json
import pytest
from copy import deepcopy
from types import SimpleNamespace
from tests.test_recovery_discovery import ROOT,mod


@pytest.mark.parametrize('nested',[False,True])
def test_resumed_request_gets_strict_fields_without_rewriting_original(tmp_path,monkeypatch,nested):
    monkeypatch.syspath_prepend(str(ROOT));m=mod('recover_external')
    (tmp_path/'calls').mkdir();(tmp_path/'run_manifest.json').write_text(json.dumps({'device':'fake','app':'Clock','actual_model_calls':0}))
    runner=m.RecoveryRun(ROOT,tmp_path)
    request=mod('update_step').build_update_request(ROOT,{},[])
    if nested:request['response_schema']={'properties':{'proposal':{'anyOf':[request['response_schema'],{'type':'null'}]}}}
    original=deepcopy(request)
    def transport(argv,**kwargs):
        folder=tmp_path/'calls'/argv[-1];sent=json.loads((folder/'request.json').read_text())['response_schema']['properties']
        if nested:sent=sent['proposal']['anyOf'][0]['properties']
        assert 'controls_complete' in sent['regions']['items']['required']
        assert 'returns_to_previous' in sent['action_result']['required']
        (folder/'response.json').write_text('{}')
        return SimpleNamespace(stdout=b'',stderr=b'',check_returncode=lambda:None)
    monkeypatch.setattr(m.subprocess,'run',transport)
    runner.call(request)
    assert request==original and runner.account['http_started']==1
