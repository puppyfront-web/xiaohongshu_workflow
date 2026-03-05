#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书信息流主工作流
集成意图识别和 MCP 执行。
"""

import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

try:
    # Package import path.
    from .intent_recognizer import IntentRecognizer, Intent
    from .crawler_executor import CrawlerExecutor
except ImportError:
    # Module execution path.
    from core.intent_recognizer import IntentRecognizer, Intent
    from core.crawler_executor import CrawlerExecutor

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class XiaohongshuWorkflow:
    """小红书信息流工作流"""

    def __init__(self, littlecrawler_path: Optional[str] = None, use_uv: bool = True):
        """
        初始化工作流

        Args:
            littlecrawler_path: 兼容旧参数，已废弃
            use_uv: 兼容旧参数，已废弃
        """
        self.recognizer = IntentRecognizer()
        self.executor = CrawlerExecutor()
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def process_input(self, user_input: str) -> Intent:
        """
        处理用户输入，识别意图

        Args:
            user_input: 用户输入文本

        Returns:
            识别的意图
        """
        print(f"\n{'='*60}")
        print(f"🔍 意图识别")
        print(f"{'='*60}")
        print(f"用户输入: {user_input}\n")

        intent = self.recognizer.recognize(user_input)

        print(self.recognizer.format_response(intent))

        return intent

    async def execute_task(self, intent: Intent) -> Dict:
        """
        执行爬虫任务

        Args:
            intent: 意图识别结果

        Returns:
            执行结果
        """
        print(f"\n{'='*60}")
        print(f"🚀 执行任务")
        print(f"{'='*60}")

        result = await self.executor.run_crawler(intent)

        return result

    async def run(self, user_input: str, auto_execute: bool = True) -> Dict:
        """
        运行完整的工作流

        Args:
            user_input: 用户输入文本
            auto_execute: 是否自动执行爬虫

        Returns:
            工作流结果
        """
        try:
            # 1. 意图识别
            intent = self.process_input(user_input)

            # 2. 确认（如果 auto_execute=False）
            if not auto_execute:
                confirm = input("\n是否继续执行？(y/n): ").strip().lower()
                if confirm != 'y':
                    return {
                        'success': False,
                        'error': '用户取消执行',
                        'intent': intent
                    }

            # 3. 执行任务
            result = await self.execute_task(intent)

            # 4. 格式化输出
            print(f"\n{'='*60}")
            print(f"📋 执行结果")
            print(f"{'='*60}")
            print(self.executor.format_result(result))

            # 5. 保存结果
            self.save_result(intent, result)

            return {
                'success': result['success'],
                'intent': intent,
                'result': result
            }

        except Exception as e:
            print(f"✗ 工作流执行失败: {e}")
            import traceback
            traceback.print_exc()

            return {
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }

    def save_result(self, intent: Intent, result: Dict):
        """
        保存执行结果

        Args:
            intent: 意图识别结果
            result: 执行结果
        """
        # 创建结果目录
        results_dir = PROJECT_ROOT / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        # 保存结果
        result_file = results_dir / f"result_{self.session_id}.json"

        save_data = {
            'session_id': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'intent': {
                'platform': intent.platform,
                'keywords': intent.keywords,
                'crawler_type': intent.crawler_type,
                'confidence': intent.confidence,
                'metadata': intent.metadata
            },
            'execution': result
        }

        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        print(f"\n💾 结果已保存到: {result_file}")

    def batch_process(self, user_inputs: list, auto_execute: bool = True) -> list:
        """
        批量处理用户输入

        Args:
            user_inputs: 用户输入列表
            auto_execute: 是否自动执行爬虫

        Returns:
            处理结果列表
        """
        results = []

        print(f"\n{'='*60}")
        print(f"📦 批量处理模式")
        print(f"{'='*60}")
        print(f"任务数量: {len(user_inputs)}\n")

        for i, user_input in enumerate(user_inputs, 1):
            print(f"\n[{i}/{len(user_inputs)}] 处理任务...")

            result = asyncio.run(self.run(user_input, auto_execute))
            results.append(result)

        # 生成批量处理报告
        self.generate_batch_report(results)

        return results

    def generate_batch_report(self, results: list):
        """
        生成批量处理报告

        Args:
            results: 处理结果列表
        """
        total = len(results)
        success = sum(1 for r in results if r.get('success'))
        failed = total - success

        report = (
            f"\n{'='*60}\n"
            f"📊 批量处理报告\n"
            f"{'='*60}\n"
            f"总任务数: {total}\n"
            f"成功: {success}\n"
            f"失败: {failed}\n"
            f"成功率: {success/total*100:.1f}%\n"
        )

        if failed > 0:
            report += f"\n❌ 失败的任务:\n"
            for i, r in enumerate(results, 1):
                if not r.get('success'):
                    intent = r.get('intent')
                    if intent:
                        report += f"  {i}. {intent.keywords} - {r.get('error', '未知错误')}\n"

        print(report)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description='小红书信息流工作流'
    )
    parser.add_argument(
        'input',
        nargs='*',
        help='用户输入（搜索查询）'
    )
    parser.add_argument(
        '-f', '--file',
        help='从文件读取输入（每行一个查询）'
    )
    parser.add_argument(
        '--no-auto',
        action='store_true',
        help='不自动执行，需要手动确认'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='测试模式，只识别意图不执行'
    )

    args = parser.parse_args()

    # 创建工作流
    workflow = XiaohongshuWorkflow()

    # 获取输入列表
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            user_inputs = [line.strip() for line in f if line.strip()]
    elif args.input:
        user_inputs = [' '.join(args.input)]
    else:
        # 交互式输入
        print("请输入搜索查询（输入 'quit' 退出）：")
        user_inputs = []
        while True:
            line = input("> ").strip()
            if line.lower() == 'quit':
                break
            if line:
                user_inputs.append(line)

    if not user_inputs:
        print("未提供输入")
        return

    # 测试模式
    if args.test:
        for user_input in user_inputs:
            intent = workflow.process_input(user_input)
            print(f"✓ 测试完成: {intent.platform} - {intent.keywords}\n")
        return

    # 批量处理
    auto_execute = not args.no_auto
    if len(user_inputs) == 1:
        asyncio.run(workflow.run(user_inputs[0], auto_execute))
    else:
        workflow.batch_process(user_inputs, auto_execute)


if __name__ == "__main__":
    main()
