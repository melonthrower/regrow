#!/usr/bin/env bash
set -euo pipefail
launcher_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
launcher_python="/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python"
exec "$launcher_python" "$launcher_dir/launch_traversal.py"
