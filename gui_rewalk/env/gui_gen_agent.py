"""Small screenshot-only VLM client used by traversal and collection stages."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
from typing import Any, Optional

import httpx
import numpy as np
import openai
from PIL import Image


logger = logging.getLogger("desktopenv.agent")
ERROR_CALLING_LLM = "Error calling LLM"

_VLM_CONNECT_TIMEOUT = float(os.environ.get("GUIWALK_LLM_CONNECT_TIMEOUT", "10"))
_VLM_REQUEST_TIMEOUT = float(os.environ.get("GUIWALK_LLM_TIMEOUT", "75"))
_VLM_CLIENT_MAX_RETRIES = 0


def _vlm_timeout(request_timeout: Optional[float] = None) -> httpx.Timeout:
    return httpx.Timeout(
        float(request_timeout or _VLM_REQUEST_TIMEOUT),
        connect=_VLM_CONNECT_TIMEOUT,
    )


def image_to_jpeg_bytes(image: Image.Image) -> bytes:
    """Encode a PIL image as JPEG, flattening transparency onto white."""
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    stream = io.BytesIO()
    image.save(stream, format="JPEG")
    return stream.getvalue()


def array_to_jpeg_bytes(image: Any) -> bytes:
    if isinstance(image, bytes):
        return image
    if isinstance(image, np.ndarray):
        return image_to_jpeg_bytes(Image.fromarray(image))
    if isinstance(image, Image.Image):
        return image_to_jpeg_bytes(image)
    raise ValueError("image must be bytes, a numpy array, or a PIL image")


def encode_image(image: Any) -> str:
    return base64.b64encode(array_to_jpeg_bytes(image)).decode("utf-8")


class GUIGenAgent:
    """DashScope-compatible Qwen transport for screenshot and text prompts.

    The constructor keeps the historical keyword surface so existing visual
    tools remain callable, but only ``observation_type='screenshot'`` is valid.
    """

    def __init__(
        self,
        completion_model: str = "",
        platform: str = "ubuntu",
        model: Optional[str] = None,
        model_version: Optional[str] = None,
        max_tokens: int = 1500,
        top_p: float = 0.9,
        temperature: float = 0.5,
        action_space: str = "gen_data",
        observation_type: str = "screenshot",
        max_trajectory_length: int = 3,
        max_retry: int = 3,
        enable_ocr: bool = False,
        enable_thinking: bool = False,
        **_: Any,
    ):
        if observation_type != "screenshot":
            raise ValueError("GUIGenAgent supports screenshot observations only")
        self.completion_model = completion_model
        self.platform = platform
        self.model = model
        self.model_version = model_version
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.action_space = action_space
        self.observation_type = observation_type
        self.max_trajectory_length = max_trajectory_length
        self.max_retry = max_retry
        self.enable_ocr = enable_ocr
        self.enable_thinking = enable_thinking
        self.thoughts: list[Any] = []
        self.actions: list[Any] = []
        self.observations: list[Any] = []
        self.last_prompt_tokens_details: dict[str, int] = {}

        api_key = str(os.environ.get("DASHSCOPE_API_KEY") or "")
        api_key = api_key.strip().lstrip("\ufeff").strip()
        self.model_client = openai.OpenAI(
            api_key=api_key or "sk-not-configured",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            http_client=httpx.Client(timeout=_vlm_timeout()),
            timeout=_vlm_timeout(),
            max_retries=_VLM_CLIENT_MAX_RETRIES,
        )

    def predict_mm(
        self, text_prompt: str, images: list[np.ndarray]
    ) -> tuple[str, Optional[int], Optional[int], int]:
        """Run one text-plus-screenshot request with bounded retries."""
        return self._predict_mm(text_prompt, images, self.max_retry)

    def predict_mm_with_policy(
        self,
        text_prompt: str,
        images: list[np.ndarray],
        max_attempts: int,
        timeout_seconds: Optional[float] = None,
        system_prompt: str = "",
    ) -> tuple[str, Optional[int], Optional[int], int]:
        """Run a request with a caller-owned transport-attempt budget.

        Visual roles that already have a semantic retry/fallback layer use this
        to avoid multiplying that layer by the transport default.
        """
        return self._predict_mm(
            text_prompt,
            images,
            max(1, int(max_attempts)),
            timeout_seconds=timeout_seconds,
            system_prompt=system_prompt,
        )

    def _predict_mm(
        self,
        text_prompt: str,
        images: list[np.ndarray],
        max_attempts: int,
        timeout_seconds: Optional[float] = None,
        system_prompt: str = "",
    ) -> tuple[str, Optional[int], Optional[int], int]:
        content: list[dict[str, Any]] = [{"type": "text", "text": text_prompt}]
        for image in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encode_image(image)}"},
            })
        messages: list[dict[str, Any]] = []
        if str(system_prompt or "").strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})

        self.last_prompt_tokens_details = {}
        prompt_total = 0
        completion_total = 0
        counter = 1
        wait_seconds = 3
        while counter <= max_attempts:
            try:
                response, prompt_tokens, completion_tokens = self.get_api_info(
                    messages, self.model_version,
                    timeout_seconds=timeout_seconds,
                )
                if isinstance(prompt_tokens, int):
                    prompt_total += prompt_tokens
                if isinstance(completion_tokens, int):
                    completion_total += completion_tokens
                return response, prompt_total, completion_total, counter
            except Exception as exc:
                logger.warning(
                    "predict_mm failed (attempt %d/%d): %s",
                    counter,
                    max_attempts,
                    exc,
                )
                counter += 1
                if counter <= max_attempts:
                    time.sleep(wait_seconds)
                    wait_seconds *= 2
        logger.error("predict_mm failed after %d attempts", max_attempts)
        return ERROR_CALLING_LLM, None, None, counter

    def get_api_info(
        self,
        messages: list[dict[str, Any]],
        model: str,
        timeout_seconds: Optional[float] = None,
    ):
        extra_body = {"enable_thinking": self.enable_thinking}
        client = self.model_client
        try:
            client = client.with_options(timeout=_vlm_timeout(timeout_seconds))
        except (AttributeError, TypeError):
            pass
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.temperature,
            extra_body=extra_body,
        )
        usage = completion.usage
        details = (
            usage.get("prompt_tokens_details")
            if isinstance(usage, dict)
            else getattr(usage, "prompt_tokens_details", None)
        )
        if hasattr(details, "model_dump"):
            details = details.model_dump()
        if not isinstance(details, dict):
            details = {
                key: getattr(details, key, None)
                for key in ("cached_tokens", "cache_creation_input_tokens")
                if getattr(details, key, None) is not None
            }
        self.last_prompt_tokens_details = {
            key: int(value)
            for key, value in details.items()
            if key in {"cached_tokens", "cache_creation_input_tokens"}
            and isinstance(value, int)
        }
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
        else:
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)
        if not completion.choices:
            raise RuntimeError("VLM returned no choices")
        return completion.choices[0].message.content, prompt_tokens, completion_tokens

    def parse_json(self, response: Any, fields: Optional[list[str]] = None):
        """Extract the first JSON object from a model response."""
        if isinstance(response, tuple):
            response = response[0]
        text = str(response or "")
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        raw = fenced.group(1) if fenced else None
        if raw is None:
            start, end = text.find("{"), text.rfind("}")
            raw = text[start:end + 1] if start >= 0 and end > start else ""
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON response: %.300s", text)
            return None
        if fields:
            return {key: data.get(key, "") for key in fields}
        return data

    def reset(self, replacement_logger=None) -> None:
        global logger
        if replacement_logger is not None:
            logger = replacement_logger
        self.thoughts = []
        self.actions = []
        self.observations = []
