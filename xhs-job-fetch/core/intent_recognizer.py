#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
意图识别模块
根据用户输入识别需要访问的平台和搜索意图
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Intent:
    """意图识别结果"""
    platform: str  # 平台: xhs, zhihu, xhy
    keywords: str  # 搜索关键词
    crawler_type: str  # 爬取类型: search, detail, creator
    confidence: float  # 置信度 0-1
    metadata: Dict = None  # 额外的元数据

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class IntentRecognizer:
    """意图识别器"""

    def __init__(self):
        # 平台关键词映射
        self.platform_keywords = {
            'xhs': {
                'keywords': [
                    '小红书', 'xhs', '小红书笔记', '小红书帖子', '小红书用户',
                    '薯片', '小红书搜索', 'xhs搜索', '小红书创作者',
                    '笔记', '种草', '小红书内容'
                ],
                'weight': 1.0
            },
            'zhihu': {
                'keywords': [
                    '知乎', 'zhihu', '知乎问题', '知乎回答', '知乎文章',
                    '知乎专栏', '知乎用户', '知乎搜索', '知乎话题',
                    '问答', '知乎创作者'
                ],
                'weight': 1.0
            },
            'xhy': {
                'keywords': [
                    '闲鱼', '闲鱼商品', '闲鱼店铺', '闲鱼卖家',
                    '二手', '小黄鱼', 'xhy', '闲鱼搜索',
                    '闲鱼交易', '闲鱼买家'
                ],
                'weight': 1.0
            }
        }

        # 爬取类型关键词
        self.crawler_type_keywords = {
            'search': {
                'keywords': ['搜索', '查找', '找', '搜索内容', '查找内容'],
                'weight': 1.0
            },
            'detail': {
                'keywords': ['详情', '帖子详情', '文章详情', '商品详情', '笔记详情'],
                'weight': 1.0
            },
            'creator': {
                'keywords': ['创作者', '博主', '作者', 'up主', '用户', '主页', '卖家'],
                'weight': 1.0
            }
        }

    def extract_keywords(self, text: str) -> str:
        """从文本中提取搜索关键词"""
        # 移除平台关键词
        for platform, config in self.platform_keywords.items():
            for keyword in config['keywords']:
                text = text.replace(keyword, '')

        # 移除爬取类型关键词
        for crawler_type, config in self.crawler_type_keywords.items():
            for keyword in config['keywords']:
                text = text.replace(keyword, '')

        # 提取关键词（去除常见助词）
        keywords = re.sub(r'[的|了|和|与|或|在|从|到|等|及|以及|还有|包括|搜索|查找|找|详情|内容]', ' ', text)
        keywords = keywords.strip()

        # 如果太短，返回原文本
        if len(keywords) < 2:
            # 尝试从原始文本提取主要内容
            main_content = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', ' ', text)
            keywords = main_content.strip()

        return keywords

    def recognize_platform(self, text: str) -> Tuple[str, float]:
        """识别目标平台"""
        scores = {}

        for platform, config in self.platform_keywords.items():
            score = 0
            text_lower = text.lower()

            for keyword in config['keywords']:
                if keyword.lower() in text_lower:
                    score += config['weight']

            scores[platform] = score

        # 找到得分最高的平台
        if not any(scores.values()):
            # 如果没有明确的平台关键词，默认使用小红书
            return 'xhs', 0.5

        max_score = max(scores.values())
        best_platform = max(scores.items(), key=lambda x: x[1])[0]

        # 计算置信度
        confidence = min(1.0, max_score / 2.0)  # 标准化到 0-1

        return best_platform, confidence

    def recognize_crawler_type(self, text: str, platform: str) -> Tuple[str, float]:
        """识别爬取类型"""
        scores = {}

        for crawler_type, config in self.crawler_type_keywords.items():
            score = 0
            text_lower = text.lower()

            for keyword in config['keywords']:
                if keyword.lower() in text_lower:
                    score += config['weight']

            scores[crawler_type] = score

        # 默认使用 search 类型
        if not any(scores.values()):
            return 'search', 0.5

        max_score = max(scores.values())
        best_type = max(scores.items(), key=lambda x: x[1])[0]

        confidence = min(1.0, max_score)

        return best_type, confidence

    def recognize(self, user_input: str) -> Intent:
        """识别用户意图"""
        # 识别平台
        platform, platform_confidence = self.recognize_platform(user_input)

        # 识别爬取类型
        crawler_type, type_confidence = self.recognize_crawler_type(user_input, platform)

        # 提取关键词
        keywords = self.extract_keywords(user_input)

        # 如果没有提取到关键词，使用原始输入
        if not keywords:
            keywords = user_input

        # 综合置信度
        overall_confidence = (platform_confidence + type_confidence) / 2.0

        # 构建元数据
        metadata = {
            'original_input': user_input,
            'platform_confidence': platform_confidence,
            'type_confidence': type_confidence
        }

        return Intent(
            platform=platform,
            keywords=keywords,
            crawler_type=crawler_type,
            confidence=overall_confidence,
            metadata=metadata
        )

    def format_response(self, intent: Intent) -> str:
        """格式化意图识别结果"""
        platform_names = {
            'xhs': '小红书',
            'zhihu': '知乎',
            'xhy': '闲鱼'
        }

        type_names = {
            'search': '搜索',
            'detail': '详情',
            'creator': '创作者'
        }

        return (
            f"已识别到以下信息：\n"
            f"• 平台：{platform_names.get(intent.platform, intent.platform)}\n"
            f"• 类型：{type_names.get(intent.crawler_type, intent.crawler_type)}\n"
            f"• 关键词：{intent.keywords}\n"
            f"• 置信度：{intent.confidence:.1%}\n"
        )


def test_recognizer():
    """测试意图识别器"""
    recognizer = IntentRecognizer()

    test_cases = [
        "帮我搜索小红书上的咖啡相关内容",
        "找找知乎上关于人工智能的问题",
        "搜索闲鱼上的二手手机",
        "小红书咖啡推荐",
        "知乎Python教程",
        "闲鱼苹果手机",
        "看看小红书上关于旅游的笔记",
        "查找知乎的科技文章"
    ]

    print("=== 意图识别测试 ===\n")
    for test_case in test_cases:
        print(f"输入: {test_case}")
        intent = recognizer.recognize(test_case)
        print(recognizer.format_response(intent))
        print("-" * 50)


if __name__ == "__main__":
    test_recognizer()
