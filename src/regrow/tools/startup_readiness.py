"""Record an operator's visual startup check before a batch's first model call.

Window metadata is evidence, not an automatic readiness decision. This module
does not call a model, operate the UI, or approve its own screenshots.
"""
from datetime import datetime, timezone
from pathlib import Path
import uuid

from regrow.records.snapshots import publish, read, write_json


def identity(manifest):
    return {key: manifest.get(key) for key in ('platform', 'app', 'device')} | {
        'container': manifest.get('desktop', {}).get('container'),
    }


def capture(run):
    """Keep a fresh screenshot and its target together; retain earlier checks."""
    from regrow.tools.batch_environment import adapter
    run = Path(run)
    manifest = read(run / 'run_manifest.json')
    if manifest['actual_model_calls'] != 0:
        raise ValueError('Startup review is only for runs with no model calls')
    folder = run / 'startup_reviews' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    frame = folder / 'frame.png'
    device = adapter(manifest)
    if manifest['platform'] == 'desktop':
        device.screenshot(frame, max_attempts=2)
    else:
        device.screenshot(frame)
    review = {'identity': identity(manifest), 'frame': str(frame.relative_to(run)),
              'captured_utc': datetime.now(timezone.utc).isoformat()}
    write_json(folder / 'review.json', review)
    write_json(run / 'startup_review.json', {'review': str(folder.relative_to(run))})
    return folder


def confirmed(run):
    run = Path(run)
    pointer = run / 'startup_review.json'
    if not pointer.exists():
        return False
    folder = run / read(pointer)['review']
    if not (folder / 'decision.json').exists():
        return False
    review, decision = read(folder / 'review.json'), read(folder / 'decision.json')
    return (decision.get('ready') is True
            and review['identity'] == identity(read(run / 'run_manifest.json'))
            and (run / review['frame']).is_file())


def confirm(run, reason):
    """Use only after inspecting this run's latest captured startup image."""
    run = Path(run)
    manifest = read(run / 'run_manifest.json')
    if manifest['actual_model_calls'] != 0 or (run / 'execution_pending.json').exists():
        raise ValueError('Cannot replace startup evidence after traversal began')
    if not reason.strip():
        raise ValueError('Describe the visible application and its readiness')
    folder = run / read(run / 'startup_review.json')['review']
    review = read(folder / 'review.json')
    frame = run / review['frame']
    if review['identity'] != identity(manifest) or not frame.is_file():
        raise ValueError('Startup evidence does not match this application/device')
    if (folder / 'decision.json').exists():
        raise ValueError('This startup check already has a decision')
    if (run / 'pending_step.json').exists():
        raise ValueError('Preserve the pending request before replacing its frame')

    def ready(records, state, *_):
        state.update(next_action_mode='discover', phase='awaiting_discovery',
                     pending_frame=str(frame.resolve()), observation=None,
                     interactive_regions=[], reason='startup_confirmed')

    pointer = publish(run, 'startup-ready-' + folder.name, ready)
    write_json(folder / 'decision.json', {
        'ready': True, 'reason': reason, 'reviewer': 'operator',
        'confirmed_utc': datetime.now(timezone.utc).isoformat(), 'knowledge': pointer,
    })
    return pointer
