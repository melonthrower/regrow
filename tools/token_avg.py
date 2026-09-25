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

def compute_avg_token_cost(json_file):
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    completion_costs = []
    prompt_costs = []

    for task in data:
        if "completion_token_cost" in task:
            completion_costs.append(task["completion_token_cost"])
        if "prompt_token_cost" in task:
            prompt_costs.append(task["prompt_token_cost"])

    avg_completion = sum(completion_costs) / len(completion_costs) if completion_costs else 0
    avg_prompt = sum(prompt_costs) / len(prompt_costs) if prompt_costs else 0

    return avg_completion, avg_prompt


if __name__ == "__main__":
    json_path = "/Users/bytedance/Downloads/statistic_ubuntu_json/example_3.json"  # 替换成你的 JSON 文件路径
    avg_completion, avg_prompt = compute_avg_token_cost(json_path)
    print(f"平均 completion_token_cost: {avg_completion:.2f}")
    print(f"平均 prompt_token_cost: {avg_prompt:.2f}")
