"""
AI 个股分析 - 提供商基类
每个提供商有不同的分析风格和报告格式，通过继承 BaseProvider 实现。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Union


@dataclass
class StockInfo:
    """个股分析输入参数"""
    code: str
    name: str = ""
    price: float = 0.0
    cost: float = 0.0
    profit_pct: float = 0.0
    score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisSection:
    """分析报告的一个章节"""
    title: str
    content: str
    style: str = "default"  # Union[default, warning, positive, negative, highlight]@dataclass
class AnalysisReport:
    """分析报告"""
    provider_key: str
    provider_name: str
    summary: str  # 一句话总结
    sections: list[AnalysisSection] = field(default_factory=list)
    raw_text: str = ""  # 原始文本（兼容旧格式）


class BaseProvider:
    """AI 分析提供商基类"""

    key: str = ""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"

    def analyze(self, stock: StockInfo) -> AnalysisReport:
        """执行分析，返回结构化报告"""
        raise NotImplementedError

    def get_info(self) -> dict[str, str]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "version": self.version,
        }