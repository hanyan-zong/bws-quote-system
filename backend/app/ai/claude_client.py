"""Claude API 客户端封装 — 没有 key 时走 mock 不影响开发."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from ..config import settings

logger = logging.getLogger("bws.ai")


class ClaudeClient:
    """轻量封装 Anthropic SDK; 失败时降级为 mock."""

    def __init__(self, api_key: str | None, model: str, max_tokens: int = 4096, timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None
        self.mock_mode = not bool(api_key)
        if self.mock_mode:
            logger.warning("Claude API key 未设置 — AI 模块走 mock 模式")
        else:
            try:
                import anthropic  # type: ignore

                self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
            except Exception as exc:
                logger.exception("anthropic SDK 初始化失败, 走 mock: %s", exc)
                self.mock_mode = True

    # ------------------------------------------------------------------
    #  抽取调用 — system + user content (text 或 image blocks)
    # ------------------------------------------------------------------
    def extract_json(self, *, system: str, content_blocks: list[dict]) -> dict[str, Any]:
        """要求模型返回严格 JSON.失败时给 mock 数据."""
        if self.mock_mode:
            return self._mock_extract(content_blocks)

        try:
            response = self._client.messages.create(  # type: ignore[union-attr]
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": content_blocks}],
            )
            text = "".join(block.text for block in response.content if hasattr(block, "text"))
            return self._parse_json_safely(text)
        except Exception as exc:
            logger.exception("Claude 调用失败, 降级 mock: %s", exc)
            return self._mock_extract(content_blocks, error=str(exc))

    # ------------------------------------------------------------------
    #  通用聊天 — 用于 AI 路线评估、信心分等
    # ------------------------------------------------------------------
    def chat_text(self, *, system: str, user: str) -> str:
        if self.mock_mode:
            return self._mock_chat(user)
        try:
            response = self._client.messages.create(  # type: ignore[union-attr]
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(block.text for block in response.content if hasattr(block, "text"))
        except Exception as exc:
            logger.exception("Claude chat 失败: %s", exc)
            return self._mock_chat(user, error=str(exc))

    # ------------------------------------------------------------------
    #  内部
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json_safely(text: str) -> dict[str, Any]:
        text = text.strip()
        # 先尝试整个解析
        try:
            return json.loads(text)
        except Exception:
            pass
        # 回退: 抠 ```json...``` 块
        if "```" in text:
            try:
                start = text.index("```")
                end = text.rindex("```")
                inner = text[start + 3:end]
                if inner.startswith("json"):
                    inner = inner[4:]
                return json.loads(inner.strip())
            except Exception:
                pass
        # 再回退: 找到第一个 { 到最后一个 }
        try:
            l = text.index("{")
            r = text.rindex("}")
            return json.loads(text[l:r + 1])
        except Exception:
            pass
        return {"_parse_error": True, "raw": text}

    @staticmethod
    def _mock_extract(content_blocks: list[dict], error: str | None = None) -> dict[str, Any]:
        """没 API key 时返回一份示例数据,让前端流程能跑通."""
        return {
            "file_name": "MOCK_FILE",
            "extraction_summary": "（mock 模式）识别到 2 家酒店 1 个车型",
            "_mock": True,
            "_error": error,
            "resources": [
                {
                    "resource_type": "hotel_room",
                    "confidence": 0.9,
                    "low_confidence_fields": [],
                    "data": {
                        "hotel_name_zh": "示例酒店 A",
                        "hotel_name_en": "Example Hotel A",
                        "destination_code": "DPS",
                        "area": "努沙杜瓦",
                        "star": 4,
                        "room_type": "Deluxe Room",
                        "max_occupancy": 2,
                        "breakfast_included": True,
                        "cost_idr_low": 1500000,
                        "cost_idr_high": 2200000,
                        "valid_from": "2026-01-01",
                        "valid_to": "2026-12-31",
                        "supplier": "Mock Supplier",
                    },
                },
                {
                    "resource_type": "vehicle",
                    "confidence": 0.85,
                    "data": {
                        "destination_code": "DPS",
                        "seat_count": 17,
                        "vehicle_type": "Toyota Hiace",
                        "cost_idr_per_day": 750000,
                        "includes_fuel": True,
                        "includes_driver": True,
                    },
                },
            ],
            "warnings": ["MOCK 模式: 请配置 ANTHROPIC_API_KEY 启用真实解析"]
            + ([f"调用错误: {error}"] if error else []),
        }

    @staticmethod
    def _mock_extract_template(error: str | None = None) -> dict[str, Any]:
        """模板专用 mock — 返回一份巴厘乌布文化游骨架."""
        return {
            "_mock": True,
            "_error": error,
            "name_zh": "乌布文化半日游",
            "name_en": "Ubud Cultural Half-Day",
            "description": "圣猴森林 → 德格拉朗梯田 → 脏鸭餐厅午餐 → 乌布皇宫",
            "total_minutes_estimate": 360,
            "difficulty": "easy",
            "destination_code": "DPS",
            "attractions": [
                {"name_zh": "圣猴森林", "stay_minutes": 60, "order_index": 1},
                {"name_zh": "德格拉朗梯田", "stay_minutes": 45, "order_index": 2},
                {"name_zh": "乌布皇宫", "stay_minutes": 45, "order_index": 3},
            ],
            "restaurants": [
                {"name_zh": "脏鸭餐厅", "meal_type": "lunch"},
            ],
            "warnings": ["MOCK 模式: 配置 ANTHROPIC_API_KEY 启用真实解析"]
            + ([f"调用错误: {error}"] if error else []),
        }

    @staticmethod
    def _mock_chat(user: str, error: str | None = None) -> str:
        return json.dumps(
            {
                "_mock": True,
                "_error": error,
                "score": 7,
                "issues": ["（mock）建议人工审核行程合理性"],
                "improved_route": [],
                "confidence": 0.7,
                "reasoning": "Mock 模式下的占位评估",
            },
            ensure_ascii=False,
        )


@lru_cache(maxsize=1)
def get_client() -> ClaudeClient:
    return ClaudeClient(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        max_tokens=settings.ai_max_tokens,
        timeout=settings.ai_request_timeout_seconds,
    )
