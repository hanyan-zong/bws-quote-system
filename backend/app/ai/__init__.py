"""AI 子模块 — Claude 客户端 + 文档解析."""
from .claude_client import ClaudeClient, get_client
from .document_parser import parse_document, parse_template_document

__all__ = ["ClaudeClient", "get_client", "parse_document", "parse_template_document"]
