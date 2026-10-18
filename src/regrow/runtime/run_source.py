from regrow.paths import SOURCE_ROOT
'One source selection for browser and supervised traversal sessions.'
import hashlib
import json
from pathlib import Path
import sys

def source_hash(source):
    source = Path(source)
    files = [source / '__main__.py']
    files += [p for p in (source / 'regrow').rglob('*') if p.is_file() and '__pycache__' not in p.parts and (p.suffix != '.pyc')]
    files += [p for p in (source / 'scopes').rglob('*') if p.is_file()]
    rows = [(str(p.relative_to(source)), hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files)]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()

def resolve_source(run):
    manifest = Path(run) / 'run_manifest.json'
    metadata = json.loads(manifest.read_text()) if manifest.exists() else {}
    selected = metadata.get('framework_source')
    if 'framework_source' in metadata and (not isinstance(selected, str) or not selected.strip()):
        raise ValueError('framework_source must be a nonempty path when specified')
    source = Path(selected).expanduser() if selected is not None else SOURCE_ROOT
    if not source.is_absolute():
        raise ValueError('framework_source must be an absolute path')
    source = source.resolve()
    if not all(((source / name).is_file() for name in ('__main__.py', 'regrow/runtime/model_reply_parse.py'))):
        raise ValueError('framework_source must contain the session entry and reply parser: ' + str(source))
    return source

def session_command(run, output, mode):
    if mode not in ('step', 'auto'):
        raise ValueError('invalid run mode')
    source = resolve_source(run)
    manifest = Path(run) / 'run_manifest.json'
    metadata = json.loads(manifest.read_text()) if manifest.exists() else {}
    if metadata.get('framework_source') != str(source):
        from regrow.records.snapshots import write_json
        metadata['framework_source'] = str(source)
        write_json(manifest, metadata)
    return [sys.executable, str(source), 'session', str(Path(run).resolve()), str(Path(output).resolve()), mode]

def launcher_identity(root, runs):
    return {'service': 'stepwise_launcher', 'root': str(Path(runs).resolve()), 'entry': str(Path(root).resolve()), 'source_hash': source_hash(root)}
