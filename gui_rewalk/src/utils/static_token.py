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

def sum_tokens(data):
    prompt_sum = 0
    completion_sum = 0

    def traverse(obj):
        nonlocal prompt_sum, completion_sum
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "forward_prompt_token":
                    prompt_sum += value
                elif key == "reverse_prompt_token":
                    prompt_sum += value
                elif key == "prompt_token":
                    prompt_sum += value
                elif key == "forward_completion_token":
                    completion_sum += value
                elif key == "reverse_completion_token":
                    completion_sum += value
                elif key == "completion_token":
                    completion_sum += value
                else:
                    traverse(value)
        elif isinstance(obj, list):
            for item in obj:
                traverse(item)

    traverse(data)
    return {
        "prompt_token_sum": prompt_sum,
        "completion_token_sum": completion_sum
    }
