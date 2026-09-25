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

"""
工具函数模块，包含图像处理、状态获取和UI元素转换等功能。
"""

from io import BytesIO
import json
import re
from typing import Dict, Any
import os
import numpy as np
from PIL import Image

def save_image(image, directory, i=0, stats="before"):
    """
    保存图像到文件并返回文件名
    
    参数:
        image: 要保存的图像对象(PIL.Image或numpy数组)
        directory: 保存目录
        
    返回:
        str: 生成的图像文件名
    """
    if stats == "before":
        unique_id = f'{i}_{stats}'
    elif stats == "after":
        unique_id = f'{i}_{stats}'
    else:
        raise ValueError(f"stats must be 'before' or 'after', but got {stats}")
    image_name = f"{unique_id}.png"
    image_path = os.path.join(directory, image_name)
    # Empty/None input (e.g. the VM died mid-run → blank screenshot bytes): do
    # NOT crash the whole collection subprocess. Return "" so the caller records
    # an empty frame and the episode/chunk can end gracefully.
    if image is None or (isinstance(image, (bytes, bytearray)) and len(image) == 0):
        return ""
    try:
        if isinstance(image, np.ndarray):
            image = Image.fromarray(np.uint8(image))
        elif isinstance(image, (bytes, bytearray)):
            image = Image.open(BytesIO(image))
        elif isinstance(image, str):
            image = Image.open(image)
        image.save(image_path)
        return image_path
    except Exception:
        return ""

def extract_action_from_json(action_json: str) -> Dict[str, Any]:
    """
    从JSON字符串中提取动作信息

    参数:
        action_json: 包含动作信息的JSON字符串

    返回:
        Dict: 包含动作类型和相关参数的字典
    """
    try:
        # 提取动作类型
        action_type = action_json.get("action_type", "").upper()

        # 根据动作类型提取额外参数
        if action_type == "INPUT_TEXT":
            return {"type": action_type, "text": action_json.get("text", "")}
        elif action_type == "SCROLL":
            direction = ""
            if "scroll_direction" in action_json:
                direction = action_json["scroll_direction"]
            elif "direction" in action_json:
                direction = action_json["direction"]
            return {"type": action_type, "direction": direction}
        else:
            return {"type": action_type}

    except (json.JSONDecodeError, TypeError) as e:
        # 如果JSON解析失败，或者action_json不是字符串，尝试使用正则表达式提取
        if isinstance(action_json, str):
            click_match = re.search(
                r'"action_type":\s*"click"', action_json, re.IGNORECASE
            )
            if click_match:
                return {"type": "CLICK"}

            type_match = re.search(
                r'"action_type":\s*"type".*"input_text":\s*"([^"]*)"',
                action_json,
                re.IGNORECASE,
            )
            if type_match:
                return {"type": "INPUT_TEXT", "text": type_match.group(1)}

            scroll_match = re.search(
                r'"action_type":\s*"scroll".*"(scroll_direction|direction)":\s*"([^"]*)"',
                action_json,
                re.IGNORECASE,
            )
            if scroll_match:
                return {"type": "SCROLL", "direction": scroll_match.group(2)}

            back_match = re.search(
                r'"action_type":\s*"press_back"', action_json, re.IGNORECASE
            )
            if back_match:
                return {"type": "PRESS_BACK"}

            long_press_match = re.search(
                r'"action_type":\s*"long_press"', action_json, re.IGNORECASE
            )
            if long_press_match:
                return {"type": "LONG_PRESS"}

    # 默认返回UNKNOWN
    return {"type": "UNKNOWN"}


def format_action_for_prompt(action: Dict[str, Any]) -> str:
    """
    将动作信息格式化为提示中使用的字符串

    参数:
        action: 包含动作类型和相关参数的字典

    返回:
        str: 格式化后的动作描述字符串
    """
    action_type = action.get("type", "UNKNOWN")

    if action_type == "INPUT_TEXT":
        return f"{action_type} '{action.get('text', '')}'"
    elif action_type == "SCROLL":
        return f"{action_type} {action.get('direction', 'UNKNOWN_DIRECTION')}"
    else:
        return action_type

def load_image_as_ndarray(img) -> np.ndarray:
    """
    将图像路径 / PIL.Image / ndarray 输入统一转换为 RGB 的 numpy 数组。
    """
    if isinstance(img, np.ndarray):
        return img
    elif isinstance(img, Image.Image):
        return np.array(img.convert("RGB"))
    elif isinstance(img, str):
        if not os.path.exists(img):
            raise FileNotFoundError(f"图片路径不存在: {img}")
        img_pil = Image.open(img).convert("RGB")
        return np.array(img_pil)
    else:
        raise TypeError(f"不支持的图像类型: {type(img)}")
    
def parse_json(llm_output, fields=None):
    """
    从 LLM 输出中提取 JSON，并可选择只保留特定字段（如 task 和 app）。
    自动处理被 escape 的 JSON 字符串。
    """

    if isinstance(llm_output, tuple):
        llm_output = llm_output[0]

    # 优先匹配 markdown 块
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", llm_output, re.DOTALL)
    if not match:
        # 匹配裸 JSON 字符串
        match = re.search(r"(\{.*\})", llm_output, re.DOTALL)

    if match:
        json_str = match.group(1)
        try:
            # 先尝试直接解析
            data = json.loads(json_str)
            # 如果解析后是字符串（说明原来是 escaped 的 JSON 字符串）
            if isinstance(data, str):
                data = json.loads(data)
            if fields:
                return {key: data.get(key, "") for key in fields}
            return data
        except json.JSONDecodeError as e:
            print("Failed to parse JSON:", e)
            print("Original string:", json_str)
            return None
    else:
        print("No JSON block found.", llm_output)
        return None