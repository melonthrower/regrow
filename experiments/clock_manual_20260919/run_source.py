"""One source selection for browser and supervised traversal sessions."""
import hashlib
import json
from pathlib import Path
import sys


def source_hash(source):
    source=Path(source)
    files=[p for p in source.iterdir() if p.is_file() and p.suffix in ('.py','.md','.html')]
    files += [p for p in (source/'遍历prompt').rglob('*') if p.is_file()]
    rows=[(str(p.relative_to(source)),hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files)]
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()


def resolve_source(run):
    manifest=Path(run)/'run_manifest.json'
    metadata=json.loads(manifest.read_text()) if manifest.exists() else {}
    selected=metadata.get('framework_source')
    if 'framework_source' in metadata and (not isinstance(selected,str) or not selected.strip()):
        raise ValueError('framework_source must be a nonempty path when specified')
    source=Path(selected).expanduser() if selected is not None else Path(__file__).resolve().parent
    if not source.is_absolute():
        raise ValueError('framework_source must be an absolute path')
    source=source.resolve()
    if not all((source/name).is_file() for name in ('run_progress_session.py','model_reply_parse.py')):
        raise ValueError('framework_source must contain the session entry and reply parser: '+str(source))
    return source


def session_command(run, output, mode):
    if mode not in ('step','auto'):raise ValueError('invalid run mode')
    source=resolve_source(run)
    # The run-local transport reads this same field when importing its parser.
    # Materialize defaults and expanded paths before any child starts.
    manifest=Path(run)/'run_manifest.json'
    metadata=json.loads(manifest.read_text()) if manifest.exists() else {}
    if metadata.get('framework_source')!=str(source):
        from register_update import write_json
        metadata['framework_source']=str(source)
        write_json(manifest,metadata)
    return [sys.executable,str(source/'run_progress_session.py'),str(Path(run).resolve()),str(Path(output).resolve()),mode]


def launcher_identity(root, runs):
    return {'service':'stepwise_launcher','root':str(Path(runs).resolve()),
            'entry':str(Path(root).resolve()/'launch_traversal.py'),'source_hash':source_hash(root)}
