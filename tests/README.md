# Tests

Maintained tests live here and keep their original `test_*.py` basenames.
Run script-style checks from the repository root, for example:

```powershell
python -B tests/test_architecture_boundaries.py
```

Utilities and operational probes remain under `tools/`. For focused pytest
runs, disable its cache and place temporary output under `artifacts/scratch/`.
