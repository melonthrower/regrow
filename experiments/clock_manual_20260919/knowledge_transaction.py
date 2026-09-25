"""Keep intermediate snapshot pointers private until a combined repair succeeds."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import json, os, uuid
_active=ContextVar('stepwise_knowledge_transaction',default=None)


def pointer(path):
    path=Path(path);active=_active.get()
    if active and path.resolve()==active[0]:return active[1]
    return path


@contextmanager
def transaction(run):
    original=Path(run).resolve()/'knowledge_current.json'
    staged=original.with_name('.knowledge-'+uuid.uuid4().hex+'.json')
    staged.write_bytes(original.read_bytes())
    token=_active.set((original,staged))
    try:
        yield
        os.replace(staged,original)
    finally:
        _active.reset(token)
        staged.unlink(missing_ok=True)
