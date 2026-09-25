"""Transport evidence and transient-failure classification; no hidden requests."""
import json
import time
from pathlib import Path
import requests


def retryable(failure):
    return failure.get('retryable') is True or failure.get('status') in (429,500,502,503,504)


def send_once(send, folder):
    started=time.monotonic()
    try:return send()
    except requests.RequestException as error:
        # Exception messages may contain credentials or private endpoints.
        evidence={'type':type(error).__name__,'seconds':time.monotonic()-started,
                  'retryable':isinstance(error,(requests.Timeout,requests.ConnectionError))
                              and not isinstance(error,requests.exceptions.SSLError)}
        with (Path(folder)/'transport_error.json').open('x') as stream:
            json.dump(evidence,stream,indent=2)
        # Do not let the SDK catch RequestException and silently send again.
        raise RuntimeError('Model transport failed: '+evidence['type']) from None
