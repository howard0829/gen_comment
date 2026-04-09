"""Ollama LLM 클라이언트"""

import logging

import requests

from config import (
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    DEFAULT_OLLAMA_URL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
)

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.options = {
            "num_ctx": DEFAULT_NUM_CTX,
            "temperature": DEFAULT_TEMPERATURE,
        }

    def check_connection(self) -> tuple[bool, str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                model_base = self.model.split(":")[0]
                found = any(model_base in m for m in models)
                if found:
                    return True, f"연결됨 (모델: {self.model})"
                return False, f"모델 '{self.model}' 없음. 사용 가능: {', '.join(models[:10])}"
            return False, "Ollama 응답 오류"
        except requests.ConnectionError:
            return False, "Ollama 연결 불가. ollama serve 실행 여부를 확인하세요."
        except Exception as e:
            return False, f"연결 오류: {e}"

    def generate_comment(self, system_prompt: str, user_prompt: str) -> str | None:
        messages = [
            {"role": "system", "content": system_prompt + "\n/nothink"},
            {"role": "user", "content": user_prompt},
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self.options,
        }

        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            if content:
                return content
            logger.warning("LLM 응답이 비어있습니다.")
            return None
        except requests.Timeout:
            logger.error("LLM 타임아웃 (%ds)", self.timeout)
            return None
        except requests.ConnectionError:
            logger.error("LLM 연결 끊김")
            return None
        except Exception as e:
            logger.error("LLM 오류: %s", e)
            return None
