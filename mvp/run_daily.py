#!/usr/bin/env python3
"""
菲律宾预测市场话题每日分析主入口

用法：
  # 沙箱/离线测试（不联网，用 mock 数据）
  python run_daily.py --mock

  # 真实运行（需要网络访问 Google News 和 Reddit）
  python run_daily.py

  # 启用 Gemini Flash 聚类/评分（推荐）
  GEMINI_API_KEY=xxx python run_daily.py --cluster

输出：
  ./reports/daily_YYYY-MM-DD.xlsx
"""
from __future__ import annotations
import os
import sys
import argparse
import yaml
import datetime as dt
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchers import fetch_topic_signals
from scorer import score_topic, classify_with_gemini
from reporter import generate_report
from discover import discover_new_topics, save_discoveries, fetch_gnews_clusters
from cluster import cluster_with_llm, cluster_keyword_fallback, groups_to_scored_topics, save_cluster_result


def load_topics(topics_dir: str) -> list:
    """读取 topics/ 下所有 yaml。"""
    topics = []
    for p in sorted(Path(topics_dir).glob("*.yaml")):
        with open(p) as f:
            topics.append(yaml.safe_load(f))
    return topics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true",
                        help="使用 mock 数据，不联网")
    parser.add_argument("--no-llm", action="store_true",
                        help="跳过 Gemini 调用，纯规则评分")
    parser.add_argument("--discover", action="store_true",
                        help="启用 Google News 话题聚类发现")
    parser.add_argument("--cluster", action="store_true",
                        help="LLM 聚类模式：直接从 Google News 发现并聚类，不依赖 topics/ YAML")
    parser.add_argument("--topics-dir", default="topics")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    topics_dir = os.path.join(base, args.topics_dir)
    output_dir = os.path.join(base, args.output_dir)

    api_key = os.environ.get("GEMINI_API_KEY")
    use_llm = (not args.no_llm) and bool(api_key)
    print(f"[INFO] LLM mode: {'Gemini Flash' if use_llm else 'heuristic only'}")
    print(f"[INFO] Fetch mode: {'mock' if args.mock else 'live'}")
    print()

    today = dt.date.today().isoformat()

    # ══════════════════════════════════════════════════════
    # 模式 A: --cluster  LLM 聚类模式（推荐，不依赖 topics/ YAML）
    # ══════════════════════════════════════════════════════
    if args.cluster:
        print("═══ Cluster Mode (LLM-first) ═══")

        # 1. 抓取所有 Google News 条目
        if args.mock:
            from discover import _mock_clusters
            raw_clusters = _mock_clusters()
        else:
            raw_clusters = fetch_gnews_clusters()
        print(f"[INFO] Fetched {len(raw_clusters)} Google News clusters")

        # 2. LLM 聚类
        if use_llm:
            print("[INFO] Sending to Gemini Flash for topic grouping...")
            cluster_result = cluster_with_llm(raw_clusters, api_key)
        else:
            print("[INFO] No API key — using keyword fallback clustering")
            cluster_result = cluster_keyword_fallback(raw_clusters)

        n_groups = len(cluster_result["groups"])
        n_noise = len(cluster_result.get("noise", []))
        print(f"[INFO] Groups: {n_groups}  |  Noise/unassigned: {n_noise}")
        for g in cluster_result["groups"]:
            total = g.get("R", 0) + g.get("S", 0) + g.get("T", 0) + g.get("U", 0) + g.get("H", 0)
            bet = "✓" if g.get("bettable") else "✗"
            print(f"  {bet} [{g['density']}] {g['name']} ({g.get('name_zh','')}) RSTUH={total}")

        cluster_path = save_cluster_result(cluster_result, output_dir)
        print(f"[OK] Cluster result → {cluster_path}")
        print()

        # 3. 转成 scored_topics 格式给 reporter
        scored = groups_to_scored_topics(cluster_result)

        out = os.path.join(output_dir, f"cluster_{today}.xlsx")
        generate_report(scored, out)
        print(f"[OK] Report → {out}")
        return

    # ══════════════════════════════════════════════════════
    # 模式 B: 经典 YAML 话题模式（原有流程）
    # ══════════════════════════════════════════════════════
    topics = load_topics(topics_dir)
    print(f"[INFO] Loaded {len(topics)} topics from {topics_dir}")

    # ── 话题发现 ──
    discoveries = None
    if args.discover:
        print("═══ Topic Discovery ═══")
        discoveries = discover_new_topics(topics, mock=args.mock)
        n_new = len(discoveries["new"])
        n_matched = len(discoveries["matched"])
        print(f"[INFO] Google News clusters: {discoveries['total_clusters']}")
        print(f"[INFO] Matched to existing topics: {n_matched}")
        print(f"[INFO] New candidates: {n_new}")
        if n_new:
            for item in discoveries["new"]:
                c = item["cluster"]
                print(f"  🆕 {c['cluster_title'][:70]}  ({c['source_count']} sources)")
        disco_path = save_discoveries(discoveries, output_dir)
        print(f"[OK] Discoveries → {disco_path}")
        print()

    # ── 话题评分 ──
    scored = []
    for topic in topics:
        print(f"→ {topic['topic_id']} ({topic['topic_name']})")
        signals = fetch_topic_signals(topic, mock=args.mock)
        n_news = len(signals["gnews_en"]) + len(signals["gnews_tl"])
        print(f"   signals: {n_news} news, {len(signals['reddit'])} reddit")
        scores = score_topic(topic, signals, use_llm=use_llm, api_key=api_key)
        if use_llm and scores["U"]["score"] is None:
            scores = classify_with_gemini(topic, signals, scores, api_key)
        print(f"   RSTUH = {scores['R']['score']}/{scores['S']['score']}/"
              f"{scores['T']['score']}/{scores['U']['score']}/{scores['H']['score']} "
              f"→ {scores['disposition']}")
        if scores["veto_dimensions"]:
            print(f"   veto: {scores['veto_dimensions']}")
        scored.append({"topic": topic, "signals": signals, "scores": scores})
        print()

    out = os.path.join(output_dir, f"daily_{today}.xlsx")
    generate_report(scored, out, discoveries=discoveries)
    print(f"[OK] Report → {out}")


if __name__ == "__main__":
    main()
