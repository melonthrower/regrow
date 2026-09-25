# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from collections import Counter

def count_actions(json_file):
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    action_counter = Counter()

    for task in data:
        # 确保random_actions存在并且里面有trajectory
        if "random_actions" in task and "trajectory" in task["random_actions"]:
            for step in task["random_actions"]["trajectory"]:
                if "action" in step:
                    action_counter[step["action"]] += 1

    return action_counter

if __name__ == "__main__":
    json_path = "/Users/bytedance/Downloads/statistic_ubuntu_json/example_9.json"  # 替换成你的 JSON 文件路径
    action_counts = count_actions(json_path)
    
    print("不同 action 的数量统计：")
    for action, count in action_counts.items():
        print(f"{action}: {count}")
