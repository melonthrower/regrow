"""Read-only screenshot overlays from the original registration observations."""
import base64
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

from regrow.records.object_store import observation_history, owned_controls
from regrow.records.region_graph import snapshot
from regrow.records import object_store


def project(run, view='live'):
    if view not in ('live', 'registration'):
        raise ValueError('unknown frame view')
    run, base, version = snapshot(run)
    records = object_store.load(base)
    rows = []
    for rid, region in records.items():
        objects = [('region', rid, region)] + [
            ('control', cid, control) for cid, control in owned_controls(region).items()]
        for kind, ref, obj in objects:
            for row in observation_history(obj):
                box = row.get('appearance_bbox') or row.get('bbox')
                source = row.get('source_image')
                if not box or not source:
                    continue
                frame = (base / source).resolve()
                if not frame.is_file():
                    continue
                call = str(row.get('evidence', {}).get('source_call') or '')
                rows.append({'kind': kind, 'ref': ref, 'name': obj.get('name', ref),
                             'box': box, 'frame': frame, 'call': call})

    metadata = json.loads((run / 'live_frame.json').read_text()) if (run / 'live_frame.json').is_file() else {}
    frame = Path(metadata.get('evidence') or run / 'screenshots/initial.png').resolve()
    label = '最近框架取图'
    if view == 'registration' and rows:
        latest = max(rows, key=lambda r: (int(r['call']) if r['call'].isdigit() else -1,
                                         r['frame'].stat().st_mtime_ns))
        frame = latest['frame']
        label = '最近有登记框的画面 · 调用 ' + latest['call']
    elif not frame.is_file():
        frame = run / 'live_frame.png'

    boxes = {}
    for row in rows:
        if row['frame'] == frame:
            boxes[(row['kind'], row['ref'])] = {
                key: row[key] for key in ('kind', 'ref', 'name', 'box', 'call')}
    raw = frame.read_bytes()
    with Image.open(BytesIO(raw)) as image:
        width, height = image.size
        mime = Image.MIME.get(image.format, 'image/png')
    return {'snapshot': version, 'view': view, 'label': label,
            'width': width, 'height': height, 'boxes': list(boxes.values()),
            'image': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode(),
            'note': '仅叠加此图原登记的外观范围；控件框可能只覆盖登记的代表项。'
                    if boxes else '此画面尚无对应登记框，可切换“最近登记画面”查看原框。'}
