#!/usr/bin/env bash
set -euo pipefail
launcher_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
launcher_python="/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python"
launcher_copy="$launcher_dir/framework_copies/region_stepwise_20260919_01/stepwise"
exec "$launcher_python" "$launcher_copy/launch_traversal.py"
