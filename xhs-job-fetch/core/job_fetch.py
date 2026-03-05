#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书信息自动化脚本（通用版）
根据主题、地区、筛选规则抓取、评分、总结并推送飞书。
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    from .workflow import XiaohongshuWorkflow
    from .crawler_executor import CrawlerExecutor
except ImportError:
    from core.workflow import XiaohongshuWorkflow
    from core.crawler_executor import CrawlerExecutor

DEFAULT_FEISHU_WEBHOOK_TIMEOUT = int(os.getenv("FEISHU_WEBHOOK_TIMEOUT", "15"))
DEFAULT_TOPIC = "AI"
DEFAULT_REGION = ""
DEFAULT_TOP_N = 8
DEFAULT_SUMMARY_MAX_LEN = 100
DEFAULT_WAIT_BETWEEN_SEARCH = 2.0

DEFAULT_MUST_HAVE = []
DEFAULT_EXCLUDE_SIGNALS = []
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_count(count_str):
    if isinstance(count_str, (int, float)):
        return float(count_str)
    if not isinstance(count_str, str):
        return 0
    if "万+" in count_str:
        return float(count_str.replace("万+", "")) * 10000
    if "万" in count_str:
        return float(count_str.replace("万", "")) * 10000
    try:
        return float(count_str)
    except (ValueError, TypeError):
        return 0


def strip_emoji(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(
        r"[\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
        r"\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF"
        r"\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF\U00002600-\U000026FF"
        r"\U00002700-\U000027BF]",
        "",
        text,
    )


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = strip_emoji(text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def shorten(text: str, max_len: int) -> str:
    text = clean_text(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def strip_xhs_tags(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"#[^#]*?\[话题\]#?", "", text)
    text = re.sub(r"#\S+", "", text)
    text = re.sub(r"@\S+", "", text)
    text = re.sub(r"\[[^\]]{1,10}R?\]", "", text)
    return text


def fmt_number(v: float) -> str:
    if v >= 10000:
        return f"{v / 10000:.1f}w"
    if v >= 1000:
        return f"{v / 1000:.1f}k"
    return str(int(v))


def normalize_str_list(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    result = []
    for value in values:
        if not isinstance(value, str):
            continue
        for part in value.split(","):
            part = clean_text(part)
            if part:
                result.append(part)
    return result


def merge_unique_lists(*list_values):
    merged = []
    seen = set()
    for values in list_values:
        for item in normalize_str_list(values):
            lowered = item.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(item)
    return merged


def deduplicate_items(all_items: list) -> list:
    seen = set()
    unique = []
    for item in all_items:
        nid = item.get("note_id", "")
        if nid and nid not in seen:
            seen.add(nid)
            unique.append(item)
    return unique


def build_default_search_keywords(topic: str, region: str, time_constraint: str = "") -> list:
    region_part = f" {region}" if region else ""
    queries = [
        f"{topic}{region_part}",
        f"{topic} 最新",
        f"{topic} 经验",
        f"{topic} 推荐",
        f"{topic} 避坑",
        f"{topic} 测评",
    ]
    if time_constraint and time_constraint not in ("不限", "none", "None"):
        queries.extend([
            f"{topic} {time_constraint}",
            f"{topic}{region_part} {time_constraint}",
        ])
    return merge_unique_lists(queries)


def build_default_priority_rules(topic: str, region: str, focus_keywords: list) -> dict:
    rules = {}
    if region:
        rules["region"] = {
            "keywords": [region],
            "weight": 3.0,
            "label": f"📍 {region}",
        }
    if topic:
        rules["topic"] = {
            "keywords": [topic],
            "weight": 2.0,
            "label": f"🧭 {topic}",
        }
    if focus_keywords:
        rules["focus"] = {
            "keywords": focus_keywords,
            "weight": 2.0,
            "label": "🎯 重点",
        }
    return rules or {
        "topic": {"keywords": [topic] if topic else [], "weight": 1.0, "label": "🧭 主题"}
    }


def sanitize_priority_rules(raw_rules: dict, fallback_rules: dict) -> dict:
    if not isinstance(raw_rules, dict) or not raw_rules:
        return fallback_rules

    cleaned = {}
    for name, rule in raw_rules.items():
        if not isinstance(name, str) or not isinstance(rule, dict):
            continue
        keywords = merge_unique_lists(rule.get("keywords", []))
        if not keywords:
            continue
        label = clean_text(str(rule.get("label", name)))
        try:
            weight = float(rule.get("weight", 1.0))
        except (ValueError, TypeError):
            weight = 1.0
        cleaned[name] = {"keywords": keywords, "weight": weight, "label": label or name}

    return cleaned or fallback_rules


def load_profile_config(config_path: str) -> dict:
    if not config_path:
        return {}
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {p}")
    with open(p, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("配置文件格式错误：顶层必须是 JSON object")
    return payload


def build_runtime_profile(args) -> dict:
    cfg = load_profile_config(args.config)

    topic = clean_text(args.topic or cfg.get("topic") or args.role or cfg.get("role") or DEFAULT_TOPIC)
    region = clean_text(args.region or cfg.get("region") or args.location or cfg.get("location") or DEFAULT_REGION)
    title = clean_text(args.title or cfg.get("title") or f"{topic}信息精选")
    time_constraint = clean_text(args.time_constraint or cfg.get("time_constraint") or "不限")
    output_format = clean_text(args.output_format or cfg.get("output_format") or "json").lower()
    if output_format not in ("json", "markdown", "both"):
        raise ValueError("output_format 仅支持: json / markdown / both")

    cli_search_keywords = normalize_str_list(args.search_keyword)
    cfg_search_keywords = normalize_str_list(cfg.get("search_keywords"))
    search_keywords = (
        cli_search_keywords
        or cfg_search_keywords
        or build_default_search_keywords(topic, region, time_constraint=time_constraint)
    )

    focus_keywords = merge_unique_lists(cfg.get("focus_keywords"), args.include_keyword)

    default_rules = build_default_priority_rules(topic, region, focus_keywords)
    priority_rules = sanitize_priority_rules(cfg.get("priority_rules"), default_rules)

    if focus_keywords and "focus" not in priority_rules:
        priority_rules["focus"] = {
            "keywords": focus_keywords,
            "weight": 2.0,
            "label": "🎯 重点",
        }

    must_have_signals = merge_unique_lists(
        DEFAULT_MUST_HAVE,
        cfg.get("must_have"),
        cfg.get("job_must_have"),
        args.must_have,
    )
    exclude_signals = merge_unique_lists(DEFAULT_EXCLUDE_SIGNALS, cfg.get("exclude_signals"), args.exclude_keyword)

    top_n = args.top_n if args.top_n is not None else int(cfg.get("top_n", DEFAULT_TOP_N))
    summary_max_len = (
        args.summary_max_len
        if args.summary_max_len is not None
        else int(cfg.get("summary_max_len", DEFAULT_SUMMARY_MAX_LEN))
    )
    wait_between_search = (
        args.wait_between_search
        if args.wait_between_search is not None
        else float(cfg.get("wait_between_search", DEFAULT_WAIT_BETWEEN_SEARCH))
    )

    push_feishu_cfg = cfg.get("push_feishu", True)
    push_feishu = bool(push_feishu_cfg) and (not args.no_feishu)

    return {
        "topic": topic,
        "region": region,
        "title": title,
        "time_constraint": time_constraint,
        "output_format": output_format,
        "search_keywords": search_keywords,
        "priority_rules": priority_rules,
        "must_have_signals": must_have_signals,
        "exclude_signals": exclude_signals,
        "top_n": max(1, int(top_n)),
        "summary_max_len": max(20, int(summary_max_len)),
        "wait_between_search": max(0.0, float(wait_between_search)),
        "push_feishu": push_feishu,
        "source_config": args.config or "",
    }


def match_priority(item: dict, priority_rules: dict) -> dict:
    title = clean_text(item.get("title", "")).lower()
    desc = clean_text(item.get("desc", "")).lower()
    text = f"{title} {desc}"

    matched = {}
    total_weight = 0.0
    for rule_name, rule in priority_rules.items():
        keywords = [k.lower() for k in normalize_str_list(rule.get("keywords", []))]
        hit = any(k in text for k in keywords)
        matched[rule_name] = hit
        if hit:
            total_weight += float(rule.get("weight", 1.0))

    return {"matched": matched, "weight": total_weight}


def item_score(item: dict, priority_rules: dict) -> float:
    priority = match_priority(item, priority_rules)
    priority_score = priority["weight"] * 10

    likes = parse_count(item.get("liked_count", 0))
    collects = parse_count(item.get("collected_count", 0))
    comments = parse_count(item.get("comment_count", 0))
    engagement = likes * 0.3 + collects * 0.5 + comments * 0.2

    return priority_score + engagement


def get_priority_labels(item: dict, priority_rules: dict) -> list:
    priority = match_priority(item, priority_rules)
    labels = []
    for rule_name, rule in priority_rules.items():
        if priority["matched"].get(rule_name):
            label = clean_text(str(rule.get("label", "")))
            if label:
                labels.append(label)
    return labels


def is_target_related(item: dict, must_have_signals: list, exclude_signals: list) -> bool:
    title = clean_text(item.get("title", "")).lower()
    desc = clean_text(item.get("desc", "")).lower()
    text = f"{title} {desc}"

    if any(ex.lower() in text for ex in exclude_signals):
        return False
    if not must_have_signals:
        return True
    return any(s.lower() in text for s in must_have_signals)


def select_top_items(data: list, profile: dict) -> list:
    relevant = [
        item
        for item in data
        if is_target_related(item, profile["must_have_signals"], profile["exclude_signals"])
    ]
    ranked = sorted(
        relevant,
        key=lambda item: item_score(item, profile["priority_rules"]),
        reverse=True,
    )
    return ranked[: profile["top_n"]]


def fetch_note_summaries(items: list, max_len: int = 100) -> dict:
    summaries = {}
    try:
        executor = CrawlerExecutor()
    except Exception:
        return summaries

    for item in items:
        note_id = item.get("note_id", "")
        xsec_token = item.get("xsec_token", "")
        if not note_id or not xsec_token:
            continue
        try:
            result = executor._call_tool(
                "get_feed_detail",
                {"feed_id": note_id, "xsec_token": xsec_token},
                timeout=30,
            )
            text = executor._extract_text_content(result)
            try:
                obj = json.loads(text)
                desc = obj.get("data", {}).get("note", {}).get("desc", "")
            except json.JSONDecodeError:
                desc = ""
            desc = strip_xhs_tags(desc)
            desc = clean_text(desc)
            if desc:
                summaries[note_id] = shorten(desc, max_len)
        except Exception:
            continue

    return summaries


def build_info_feishu_card(top_items: list, total_count: int, profile: dict, summaries: dict = None):
    summaries = summaries or {}
    now_str = datetime.now().strftime("%m/%d %H:%M")

    if not top_items:
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"{profile['title']} | {now_str}"},
                    "template": "blue",
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "plain_text", "content": "今日暂无符合筛选条件的内容。"}},
                ],
            },
        }

    rule_hits = []
    for rule_name, rule in profile["priority_rules"].items():
        count = sum(
            1
            for item in top_items
            if match_priority(item, profile["priority_rules"])["matched"].get(rule_name)
        )
        if count > 0:
            rule_hits.append(f"{rule.get('label', rule_name)} {count}")

    summary = (
        f"今日采集 **{total_count}** 条内容，精选 **{len(top_items)}** 条\n"
        f"命中规则：{' · '.join(rule_hits) if rule_hits else '无'}\n"
        f"时间约束：{profile.get('time_constraint', '不限')}"
    )

    elements = []
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": summary},
    })
    elements.append({"tag": "hr"})

    for i, item in enumerate(top_items, 1):
        title = shorten(clean_text(item.get("title", "")), 35) or "无标题"
        nickname = clean_text(item.get("nickname", ""))
        likes = parse_count(item.get("liked_count", 0))
        collects = parse_count(item.get("collected_count", 0))
        comments = parse_count(item.get("comment_count", 0))
        note_url = item.get("note_url", "")

        labels = get_priority_labels(item, profile["priority_rules"])
        label_str = " ".join(labels) if labels else "📌 匹配"

        note_id = item.get("note_id", "")
        summary_line = f"\n📝 {summaries[note_id]}" if note_id in summaries else ""

        content_md = (
            f"**{i}. {title}**\n"
            f"{label_str} · @{nickname}\n"
            f"{fmt_number(likes)} 赞 · {fmt_number(collects)} 藏 · {fmt_number(comments)} 评"
            f"{summary_line}"
        )

        item_element = {
            "tag": "div",
            "text": {"tag": "lark_md", "content": content_md},
        }

        if note_url:
            item_element["extra"] = {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看"},
                "type": "primary",
                "url": note_url,
            }

        elements.append(item_element)

    elements.append({"tag": "hr"})

    kw_line = " · ".join(profile["search_keywords"][:4])
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"🔍 {kw_line}"},
    })

    elements.append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text", "content": f"Clawdbot · {profile['title']} · {now_str}"},
        ],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"{profile['title']} | {now_str}"},
                "template": "blue",
            },
            "elements": elements,
        },
    }


def post_feishu_webhook(webhook_url: str, payload: dict, timeout: int = 15):
    req = urllib_request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            if resp.status >= 400:
                return False, f"HTTP {resp.status}: {body[:300]}"
            try:
                obj = json.loads(body) if body else {}
            except json.JSONDecodeError:
                obj = {}
            code = obj.get("code", 0)
            if code not in (0, "0", None):
                return False, f"code={code}, msg={obj.get('msg', '')}"
            return True, "ok"
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return False, f"HTTPError {exc.code}: {detail[:300]}"
    except urllib_error.URLError as exc:
        return False, f"URLError: {exc}"
    except Exception as exc:
        return False, f"异常: {exc}"


def build_markdown_report(report_data: dict, summaries: dict) -> str:
    profile = report_data.get("profile", {})
    selected_items = report_data.get("selected_items", [])
    lines = []
    lines.append(f"# {profile.get('title', '小红书信息报告')}")
    lines.append("")
    lines.append(f"- 时间: {report_data.get('timestamp', '')}")
    lines.append(f"- 主题: {profile.get('topic', '')}")
    lines.append(f"- 地区: {profile.get('region', '') or '不限'}")
    lines.append(f"- 时间约束: {profile.get('time_constraint', '不限')}")
    lines.append(f"- 采集总数: {report_data.get('total_crawled', 0)}")
    lines.append(f"- 去重后: {report_data.get('unique_count', 0)}")
    lines.append(f"- 精选条数: {report_data.get('selected_count', 0)}")
    lines.append("")
    lines.append("## 精选内容")
    lines.append("")

    if not selected_items:
        lines.append("暂无符合条件的内容。")
        return "\n".join(lines)

    for idx, item in enumerate(selected_items, 1):
        lines.append(f"{idx}. **{item.get('title', '无标题')}**")
        lines.append(f"   - 作者: @{item.get('nickname', '')}")
        labels = item.get("priority_labels") or []
        if labels:
            lines.append(f"   - 标签: {' / '.join(labels)}")
        lines.append(f"   - 评分: {item.get('score', 0):.2f}")
        note_url = item.get("note_url", "")
        if note_url:
            lines.append(f"   - 链接: {note_url}")
        note_id = item.get("note_id", "")
        if note_id and summaries.get(note_id):
            lines.append(f"   - 摘要: {summaries[note_id]}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def run_profile(profile: dict):
    print("=" * 60)
    print(f"{profile['title']} 自动化任务")
    print("=" * 60)

    print("\n📥 步骤 1: 多关键词搜索...")
    all_items = []
    workflow = XiaohongshuWorkflow()

    for kw in profile["search_keywords"]:
        print(f"  🔍 搜索: {kw}")
        try:
            result = await workflow.run(f"小红书 {kw}", auto_execute=True)
            if result.get("success"):
                data_dir = PROJECT_ROOT / "data" / "xhs" / "json"
                json_files = sorted(
                    data_dir.glob("search_contents_*.json"),
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                )
                if json_files:
                    with open(json_files[0], "r", encoding="utf-8") as f:
                        items = json.load(f)
                    print(f"     ✅ 获取 {len(items)} 条")
                    all_items.extend(items)
            else:
                error = result.get("error", "未知错误")
                print(f"     ⚠️ 失败: {error}")
        except Exception as exc:
            print(f"     ⚠️ 异常: {exc}")

        time.sleep(profile["wait_between_search"])

    if not all_items:
        print("\n❌ 未获取到任何数据")
        return None, False

    print("\n📊 步骤 2: 数据处理...")
    unique_items = deduplicate_items(all_items)
    print(f"  原始 {len(all_items)} 条 → 去重后 {len(unique_items)} 条")

    top_items = select_top_items(unique_items, profile)
    print(f"  精选 {len(top_items)} 条符合条件内容")

    print("\n📝 步骤 3: 获取笔记摘要...")
    summaries = fetch_note_summaries(top_items, max_len=profile["summary_max_len"])
    print(f"  ✅ 成功获取 {len(summaries)}/{len(top_items)} 条摘要")

    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_data = {
        "timestamp": ts,
        "profile": {
            "topic": profile["topic"],
            "region": profile["region"],
            "title": profile["title"],
            "time_constraint": profile["time_constraint"],
            "output_format": profile["output_format"],
            "search_keywords": profile["search_keywords"],
            "top_n": profile["top_n"],
            "summary_max_len": profile["summary_max_len"],
            "source_config": profile["source_config"],
        },
        "total_crawled": len(all_items),
        "unique_count": len(unique_items),
        "selected_count": len(top_items),
        "selected_items": [
            {
                "title": item.get("title", ""),
                "nickname": item.get("nickname", ""),
                "note_url": item.get("note_url", ""),
                "note_id": item.get("note_id", ""),
                "priority_labels": get_priority_labels(item, profile["priority_rules"]),
                "score": item_score(item, profile["priority_rules"]),
            }
            for item in top_items
        ],
    }

    data_file = report_dir / f"info_report_{ts}.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告已保存: {data_file}")

    markdown_file = None
    if profile["output_format"] in ("markdown", "both"):
        markdown_text = build_markdown_report(report_data, summaries=summaries)
        markdown_file = report_dir / f"info_report_{ts}.md"
        with open(markdown_file, "w", encoding="utf-8") as f:
            f.write(markdown_text)
        report_data["markdown_report"] = str(markdown_file)
        print(f"📝 Markdown 已保存: {markdown_file}")

    print("\n📤 步骤 4: 推送到飞书...")
    if not profile["push_feishu"]:
        print("  ℹ️ 当前 profile 配置 push_feishu=false，跳过飞书推送")
    else:
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
        if not webhook_url:
            print("  ℹ️ 未配置 FEISHU_WEBHOOK_URL，跳过飞书推送")
        else:
            card_payload = build_info_feishu_card(top_items, len(unique_items), profile, summaries=summaries)
            ok, msg = post_feishu_webhook(webhook_url, card_payload, timeout=DEFAULT_FEISHU_WEBHOOK_TIMEOUT)
            if ok:
                print(f"  ✅ 飞书推送成功: {msg}")
            else:
                print(f"  ⚠️ 飞书推送失败: {msg}")

    return report_data, True


def parse_args():
    parser = argparse.ArgumentParser(description="通用小红书信息抓取与总结")
    parser.add_argument("--config", help="JSON 配置文件路径（可选）")
    parser.add_argument("--topic", help="抓取主题，如：AI/租房/旅游/探店")
    parser.add_argument("--region", help="地区关键词，如：深圳/上海/北京")
    parser.add_argument("--role", help="兼容旧参数：等价于 --topic")
    parser.add_argument("--location", help="兼容旧参数：等价于 --region")
    parser.add_argument("--title", help="推送标题，如：AI 信息精选")
    parser.add_argument("--time-constraint", help="时间约束，如：近7天/近30天/不限")
    parser.add_argument("--output-format", help="结果格式: json/markdown/both")
    parser.add_argument("--search-keyword", action="append", help="搜索关键词，可重复传入")
    parser.add_argument("--include-keyword", action="append", help="优先级加权关键词，可重复传入")
    parser.add_argument("--must-have", action="append", help="必须命中的关键词，可重复传入")
    parser.add_argument("--exclude-keyword", action="append", help="排除词，可重复传入")
    parser.add_argument("--top-n", type=int, help="最多保留条数")
    parser.add_argument("--summary-max-len", type=int, help="摘要长度")
    parser.add_argument("--wait-between-search", type=float, help="每次搜索间隔秒数")
    parser.add_argument("--no-feishu", action="store_true", help="不推送飞书，仅保存结果")
    parser.add_argument("--print-config", action="store_true", help="打印最终生效配置")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        profile = build_runtime_profile(args)
    except Exception as exc:
        print(f"❌ 加载配置失败: {exc}")
        sys.exit(2)

    if args.print_config:
        print("Runtime profile:")
        print(json.dumps(profile, ensure_ascii=False, indent=2))

    result, success = asyncio.run(run_profile(profile))
    if success:
        print("\n" + "=" * 60)
        print("✅ 信息抓取任务完成")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ 任务执行失败")
        print("=" * 60)
        sys.exit(1)
