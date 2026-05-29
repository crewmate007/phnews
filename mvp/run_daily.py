#!/usr/bin/env python3
"""
预测市场话题每日分析主入口

用法：
  # 沙箱/离线测试（不联网，用 mock 数据）
  python run_daily.py --mock

  # 真实运行（读取 SourceIntel JSON，并访问 Reddit）
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
import subprocess
import yaml
import datetime as dt
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchers import fetch_topic_signals
from scorer import score_topic, classify_with_gemini
from reporter import generate_report
from cluster import cluster_with_llm, cluster_keyword_fallback, groups_to_scored_topics, save_cluster_result
from regions import get_region, reports_dir
import db  # Supabase mirror; no-op without SUPABASE_* env vars
from source_intel_bridge import (
    load_source_intel_clusters,
    mock_source_intel_clusters,
    source_intel_discoveries,
)


def load_topics(topics_dir: str) -> list:
    """读取 topics/ 下所有 yaml。"""
    topics = []
    for p in sorted(Path(topics_dir).glob("*.yaml")):
        with open(p) as f:
            topics.append(yaml.safe_load(f))
    return topics


def load_gemini_api_key() -> str | None:
    """Load Gemini key from shell env, then repo .env as a local fallback."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "GEMINI_API_KEY":
            return value.strip().strip('"').strip("'") or None
    return None


def run_site_step(script_name: str, date: str, region_slug: str,
                  required: bool = True) -> bool:
    """Run a repo-level site publishing helper script."""
    base = Path(__file__).resolve().parent
    repo_root = base.parent
    script_path = repo_root / "scripts" / script_name
    if not script_path.exists():
        msg = f"[WARN] Site script missing: {script_path}"
        if required:
            raise FileNotFoundError(msg)
        print(msg)
        return False

    try:
        completed = subprocess.run(
            [sys.executable, str(script_path), date, "--region", region_slug],
            cwd=str(repo_root),
            check=True,
            text=True,
            capture_output=True,
        )
        if completed.stdout:
            print(completed.stdout.rstrip())
        return True
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout.rstrip())
        if exc.stderr:
            print(exc.stderr.rstrip(), file=sys.stderr)
        if required:
            raise
        print(f"[WARN] Optional site step failed ({script_name}): {exc}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true",
                        help="使用 mock 数据，不联网")
    parser.add_argument("--no-llm", action="store_true",
                        help="跳过 Gemini 调用，纯规则评分")
    parser.add_argument("--discover", action="store_true",
                        help="启用 SourceIntel 话题发现匹配")
    parser.add_argument("--cluster", action="store_true",
                        help="LLM 聚类模式：从 SourceIntel 热点聚类，不依赖 topics/ YAML")
    parser.add_argument("--region", default="ph", choices=("ph", "id"),
                        help="地区：ph=菲律宾，id=印尼")
    parser.add_argument("--topics-dir", default="topics")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--source-intel-dir",
                        help="SourceIntel project directory; default is sibling ../SourceIntel")
    parser.add_argument("--source-intel-report",
                        help="Explicit SourceIntel hotspots JSON report path")
    args = parser.parse_args()

    region = get_region(args.region)
    base = os.path.dirname(os.path.abspath(__file__))
    topics_dir = os.path.join(base, args.topics_dir)
    output_dir = reports_dir(os.path.join(base, args.output_dir), region)

    api_key = load_gemini_api_key()
    use_llm = (not args.no_llm) and bool(api_key)
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    print(f"[INFO] LLM mode: {'Gemini Flash' if use_llm else 'heuristic only'}")
    if use_llm:
        print(f"[INFO] LLM model: {gemini_model}")
    print(f"[INFO] Fetch mode: {'mock' if args.mock else 'live'}")
    print(f"[INFO] Region: {region.flag} {region.country_name}")
    print()

    today = dt.date.today().isoformat()

    # ══════════════════════════════════════════════════════
    # 模式 A: --cluster  LLM 聚类模式（推荐，不依赖 topics/ YAML）
    # ══════════════════════════════════════════════════════
    if args.cluster:
        print("═══ Cluster Mode (LLM-first) ═══")

        # 1. 读取 SourceIntel 热点条目
        if args.mock:
            raw_clusters = mock_source_intel_clusters(region)
        else:
            raw_clusters = load_source_intel_clusters(
                region=region,
                source_intel_dir=args.source_intel_dir,
                report_path=args.source_intel_report,
            )
        print(f"[INFO] Loaded {len(raw_clusters)} SourceIntel hotspots")

        # 2. LLM 聚类
        if use_llm:
            print("[INFO] Sending to Gemini Flash for topic grouping...")
            cluster_result = cluster_with_llm(
                raw_clusters,
                api_key,
                region=region,
                model=gemini_model,
            )
        else:
            print("[INFO] No API key — using keyword fallback clustering")
            cluster_result = cluster_keyword_fallback(raw_clusters, region=region)

        n_groups = len(cluster_result["groups"])
        n_noise = len(cluster_result.get("noise", []))
        print(f"[INFO] Groups: {n_groups}  |  Noise/unassigned: {n_noise}")
        for g in cluster_result["groups"]:
            total = g.get("R", 0) + g.get("S", 0) + g.get("T", 0) + g.get("U", 0) + g.get("H", 0)
            bet = "✓" if g.get("bettable") else "✗"
            print(f"  {bet} [{g['density']}] {g['name']} ({g.get('name_zh','')}) RSTUH={total}")

        cluster_path = save_cluster_result(cluster_result, os.path.join(base, args.output_dir), region)
        print(f"[OK] Cluster result → {cluster_path}")

        # Phase 1 dual-write: mirror the result into Supabase. No-op without
        # SUPABASE_* env; never raises (failure only logs, JSON is unaffected).
        if db.write_run(cluster_result, region.slug, today):
            print(f"[OK] Supabase ← mirrored {region.slug} {today}")
        print()

        # 3. 转成 scored_topics 格式给 reporter
        scored = groups_to_scored_topics(cluster_result)

        out = os.path.join(output_dir, f"cluster_{today}.xlsx")
        generate_report(scored, out)
        print(f"[OK] Report → {out}")
        print()

        print("═══ Static Site Publish ═══")
        run_site_step("gen_html.py", today, region.slug)
        if use_llm:
            run_site_step("add_probabilities.py", today, region.slug, required=False)
        else:
            print("[INFO] Skipping probability enrichment: no Gemini API key")
        run_site_step("publish_site.py", today, region.slug)
        print("[OK] GitHub Pages site updated in ../docs")
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
        if args.mock:
            mock_clusters = [
                {"cluster": cluster, "matched_topic": None}
                for cluster in mock_source_intel_clusters(region)
            ]
            discoveries = {
                "matched": [],
                "new": mock_clusters,
                "total_clusters": len(mock_clusters),
                "fetched_at": dt.datetime.now().isoformat(),
                "source": "source_intel_mock",
            }
        else:
            discoveries = source_intel_discoveries(
                topics,
                region=region,
                source_intel_dir=args.source_intel_dir,
                report_path=args.source_intel_report,
            )
        n_new = len(discoveries["new"])
        n_matched = len(discoveries["matched"])
        print(f"[INFO] SourceIntel hotspots: {discoveries['total_clusters']}")
        print(f"[INFO] Matched to existing topics: {n_matched}")
        print(f"[INFO] New candidates: {n_new}")
        if n_new:
            for item in discoveries["new"]:
                c = item["cluster"]
                print(f"  🆕 {c['cluster_title'][:70]}  ({c['source_count']} sources)")
        print()

    # ── 话题评分 ──
    scored = []
    for topic in topics:
        print(f"→ {topic['topic_id']} ({topic['topic_name']})")
        signals = fetch_topic_signals(
            topic,
            mock=args.mock,
            region=region,
            source_intel_dir=args.source_intel_dir,
            source_intel_report=args.source_intel_report,
        )
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
