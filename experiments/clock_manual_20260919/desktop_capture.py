"""Read the local VM display without the guest screenshot service."""
from io import BytesIO
from pathlib import Path
import json
import re
import subprocess
import uuid
from datetime import datetime,timezone
from PIL import Image


def display_capture(container):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',container):raise ValueError('invalid VM container')
    remote='/tmp/rewalk-capture-'+uuid.uuid4().hex+'.ppm'
    command=f'exec 3<>/dev/tcp/127.0.0.1/7100; echo "screendump {remote}" >&3; sleep 1'
    try:
        subprocess.run(['docker','exec',container,'bash','-c',command],check=True,capture_output=True,timeout=5)
        result=subprocess.run(['docker','exec',container,'cat',remote],check=True,capture_output=True,timeout=8)
        with Image.open(BytesIO(result.stdout)) as frame:
            frame.load();output=BytesIO();frame.save(output,format='PNG');return output.getvalue()
    finally:
        subprocess.run(['docker','exec',container,'rm','-f',remote],capture_output=True,timeout=3)


def publish_frame(run,path,source):
    if run is None:return
    # Display-cache failure cannot invalidate a captured execution observation.
    try:
        run=Path(run);tmp=run/'live_frame.tmp';tmp.write_bytes(Path(path).read_bytes());tmp.replace(run/'live_frame.png')
        meta=run/'live_frame.json';temp=meta.with_suffix('.tmp')
        temp.write_text(json.dumps({'captured_at':datetime.now(timezone.utc).isoformat(),'source':source,'evidence':str(path)},ensure_ascii=False));temp.replace(meta)
    except OSError:pass
