"""Current package ownership and frozen-source entry checks; no model or GUI."""
import json
import os
from pathlib import Path
import subprocess
import sys
from regrow.paths import SOURCE_ROOT
from regrow.records import snapshots as io
from regrow.records import snapshots
from regrow.records import snapshots as knowledge_transaction
from regrow.traversal import discovery_step
from regrow.tools.debug_loop import freeze
from regrow.runtime.run_source import source_hash
from regrow.runtime.run_source import session_command

def test_record_implementations_have_one_owner():
    assert snapshots.load.__module__ == 'regrow.records.snapshots'
    assert snapshots.commit.__module__ == 'regrow.records.snapshots'
    assert not hasattr(discovery_step, 'load')
    assert not hasattr(discovery_step, 'publish')
    from regrow.records import calls
    assert calls.read is io.read

def test_reads_and_writes_share_the_same_transaction_pointer(tmp_path):
    pointer = tmp_path / 'knowledge_current.json'
    io.write_json(pointer, {'snapshot': 'before'})
    with knowledge_transaction.transaction(tmp_path):
        io.write_json(pointer, {'snapshot': 'after'})
        assert json.loads(pointer.read_text()) == {'snapshot': 'before'}
        assert io.read(pointer) == {'snapshot': 'after'}
    assert json.loads(pointer.read_text()) == {'snapshot': 'after'}
    try:
        with knowledge_transaction.transaction(tmp_path):
            io.write_json(pointer, {'snapshot': 'failed'})
            raise ValueError('abort this registration')
    except ValueError:
        pass
    assert io.read(pointer) == {'snapshot': 'after'}

def test_frozen_source_runs_its_own_package_and_prompt_resources(tmp_path):
    frozen = freeze(SOURCE_ROOT, tmp_path / 'source')
    assert source_hash(frozen) == source_hash(SOURCE_ROOT)
    script = "\nfrom pathlib import Path\nfrom regrow.paths import SOURCE_ROOT\nfrom regrow.records import snapshots\nfrom regrow.prompts.compose import catalog\nassert SOURCE_ROOT == Path.cwd()\nassert Path(snapshots.__file__).is_relative_to(Path.cwd())\nassert catalog()['calls']['action_selection']['question']\n"
    result = subprocess.run([sys.executable, '-c', script], cwd=frozen, env={**os.environ, 'PYTHONPATH': str(frozen), 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    run = tmp_path / 'run'
    run.mkdir()
    io.write_json(run / 'run_manifest.json', {'framework_source': str(frozen)})
    command = session_command(run, tmp_path / 'output', 'step')
    assert command[1:3] == [str(frozen), 'session']
    help_result = subprocess.run([sys.executable, str(frozen), 'step', '--help'], capture_output=True, text=True)
    assert help_result.returncode == 0, help_result.stderr

def test_invalid_source_is_rejected_before_any_device_observation(tmp_path):
    from types import SimpleNamespace
    import pytest
    from regrow.runtime.action_executor import ActionExecutor

    def no_device(*args, **kwargs):
        raise AssertionError('invalid source reached the device')
    transport = SimpleNamespace(run=tmp_path, account={'http_started': 0, 'max_http': 1}, screenshot=no_device)
    accepted = {'result': {'request': {}, 'call': 'missing', 'proposal': {'action': 'click'}, 'binding': {'status': 'matched', 'observation_ref': 'o1', 'region_ref': 'r1', 'control_ref': 'c1'}}}
    with pytest.raises(ValueError, match='source request is missing'):
        ActionExecutor(transport, tmp_path, None).execute(accepted, None, [])
    assert not (tmp_path / 'action_attempts').exists()
