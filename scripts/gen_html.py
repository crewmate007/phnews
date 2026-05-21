"""
Generate a bilingual HTML report from clusters_YYYY-MM-DD.json.

Usage:
  python3 scripts/gen_html.py                    # use today's JSON
  python3 scripts/gen_html.py 2026-04-18         # use a specific date

Output:
  mvp/reports/cluster_YYYY-MM-DD.html
"""
from __future__ import annotations
import json
import sys
import datetime as dt
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mvp"))
from regions import get_region


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__SITE_NAME__ · Prediction Market Daily · __DATE__</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }

  header { padding: 32px 40px 24px; border-bottom: 1px solid #1e2535; display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 16px; }
  header h1 { font-size: 22px; font-weight: 700; color: #fff; letter-spacing: -0.3px; }
  header .meta { margin-top: 6px; font-size: 13px; color: #64748b; }
  header .meta span { margin-right: 20px; }

  .top-controls { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
  .region-toggle, .lang-toggle { display: flex; background: #161b27; border: 1px solid #1e2535; border-radius: 8px; overflow: hidden; flex-shrink: 0; }
  .region-link, .lang-btn { padding: 8px 18px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; background: transparent; color: #64748b; transition: all 0.15s; text-decoration: none; line-height: 1.2; }
  .region-link.active, .lang-btn.active { background: #1e2535; color: #fff; }
  .lang-btn.active { background: #1e2535; color: #fff; }
  .filter-btn { padding: 8px 14px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid #1e2535; border-radius: 8px; background: #161b27; color: #64748b; transition: all 0.15s; }
  .filter-btn.active { background: #1e2535; color: #e2e8f0; }

  .stats { display: flex; gap: 12px; padding: 20px 40px; border-bottom: 1px solid #1e2535; flex-wrap: wrap; }
  .stat { background: #161b27; border: 1px solid #1e2535; border-radius: 8px; padding: 14px 20px; min-width: 110px; }
  .stat .val { font-size: 26px; font-weight: 700; color: #fff; }
  .stat .lbl { font-size: 11px; color: #64748b; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }

  .main { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 24px 40px; }

  .card { background: #161b27; border: 1px solid #1e2535; border-radius: 12px; padding: 20px; transition: border-color 0.15s; }
  .card:hover { border-color: #334155; }
  .card.top    { border-left: 3px solid #22c55e; }
  .card.candidate { border-left: 3px solid #f59e0b; }
  .card.watch  { border-left: 3px solid #3b82f6; }
  .card.drop   { border-left: 3px solid #374151; opacity: 0.6; }

  .card-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 10px; }
  .card-title { font-size: 15px; font-weight: 600; color: #fff; line-height: 1.3; }
  .card-title .sub { display: block; font-size: 12px; color: #64748b; font-weight: 400; margin-top: 3px; }

  .badge { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 20px; white-space: nowrap; flex-shrink: 0; margin-left: 10px; margin-top: 2px; }
  .badge.top       { background: #14532d; color: #4ade80; }
  .badge.candidate { background: #451a03; color: #fbbf24; }
  .badge.watch     { background: #1e3a5f; color: #60a5fa; }
  .badge.drop      { background: #1f2937; color: #6b7280; }

  .narrative { font-size: 13px; color: #94a3b8; line-height: 1.6; margin-bottom: 14px; }
  .source-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
  .source-chip { font-size: 10px; font-weight: 700; letter-spacing: 0.2px; padding: 4px 8px; border-radius: 999px; border: 1px solid #273244; color: #94a3b8; background: #101722; }
  .source-chip.x_grok { color: #c4b5fd; border-color: #4c1d95; background: #1f1733; }
  .source-chip.google_news { color: #93c5fd; border-color: #1d4ed8; background: #111d35; }
  .source-list { margin: -2px 0 14px; display: grid; gap: 6px; }
  .source-item { display: grid; grid-template-columns: 74px 1fr; gap: 8px; font-size: 11px; color: #64748b; line-height: 1.35; }
  .source-item .source-name { font-weight: 700; color: #94a3b8; }
  .source-item.x_grok .source-name { color: #c4b5fd; }
  .source-item.google_news .source-name { color: #93c5fd; }
  .source-item .source-title { color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .density-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .density-bar .label { font-size: 11px; color: #64748b; width: 72px; flex-shrink: 0; }
  .bar-track { flex: 1; height: 4px; background: #1e2535; border-radius: 2px; }
  .bar-fill  { height: 100%; border-radius: 2px; background: #3b82f6; }
  .density-bar .count { font-size: 11px; color: #94a3b8; width: 40px; text-align: right; }

  .rstuh { display: flex; gap: 6px; margin-bottom: 14px; }
  .dim { display: flex; flex-direction: column; align-items: center; background: #0f1117; border-radius: 6px; padding: 6px 10px; min-width: 38px; }
  .dim .letter { font-size: 10px; color: #64748b; font-weight: 600; }
  .dim .score  { font-size: 16px; font-weight: 700; }
  .dim .score.s2 { color: #22c55e; }
  .dim .score.s1 { color: #f59e0b; }
  .dim .score.s0 { color: #ef4444; }
  .dim-total { display: flex; flex-direction: column; align-items: center; background: #0f1117; border-radius: 6px; padding: 6px 10px; min-width: 38px; margin-left: 4px; border: 1px solid #1e2535; }
  .dim-total .letter { font-size: 10px; color: #64748b; font-weight: 600; }
  .dim-total .score  { font-size: 16px; font-weight: 700; color: #fff; }

  .question-box { background: #0f1117; border: 1px solid #1e2535; border-radius: 8px; padding: 12px 14px; margin-top: 4px; }
  .question-box .q-label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
  .question-box .q-text  { font-size: 13px; color: #e2e8f0; line-height: 1.5; font-style: italic; }
  .question-box .q-source { font-size: 11px; color: #64748b; margin-top: 6px; }
  .no-bet { font-size: 12px; color: #4b5563; margin-top: 4px; }
  .prob-row { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
  .prob-label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }
  .prob-bar-track { flex: 1; height: 6px; background: #1e2535; border-radius: 3px; }
  .prob-bar-fill { height: 100%; border-radius: 3px; transition: width 0.4s ease; }
  .prob-val { font-size: 14px; font-weight: 700; white-space: nowrap; min-width: 38px; text-align: right; }

  @media (max-width: 900px) {
    .main { grid-template-columns: 1fr; }
    header, .stats, .main { padding-left: 20px; padding-right: 20px; }
  }
</style>
</head>
<body>

<header>
  <div>
    <h1 id="h-title">__FLAG__ __SITE_NAME__ __COUNTRY_ZH__预测市场话题日报</h1>
    <div class="meta">
      <span>📅 __DATE__</span>
      <span id="h-clusters">📰 读取 __TOTAL__ 条 SourceIntel 热点</span>
      <span>🤖 Gemini 3.1 Flash Lite</span>
    </div>
  </div>
  <div class="top-controls">
    <div class="region-toggle" aria-label="Region">
      <a class="region-link __PH_ACTIVE__" data-region-link="ph" href="./index.html">PH</a>
      <a class="region-link __ID_ACTIVE__" data-region-link="id" href="./id/index.html">IN</a>
    </div>
    <div class="lang-toggle" aria-label="Language">
      <button class="lang-btn active" onclick="setLang('zh')">中文</button>
      <button class="lang-btn" onclick="setLang('en')">EN</button>
    </div>
    <button id="filter-toggle" class="filter-btn" onclick="toggleFiltered()"></button>
  </div>
</header>

<div class="stats">
  <div class="stat"><div class="val">__N_GROUPS__</div><div class="lbl" data-zh="话题组" data-en="Topics">话题组</div></div>
  <div class="stat"><div class="val" style="color:#4ade80">__N_TOP__</div><div class="lbl" data-zh="TOP 级" data-en="TOP tier">TOP 级</div></div>
  <div class="stat"><div class="val" style="color:#fbbf24">__N_CAND__</div><div class="lbl" data-zh="候选" data-en="Candidates">候选</div></div>
  <div class="stat"><div class="val">__N_BET__</div><div class="lbl" data-zh="可下注" data-en="Bettable">可下注</div></div>
  <div class="stat"><div class="val" style="color:#64748b">__N_NOISE__</div><div class="lbl" data-zh="噪音过滤" data-en="Noise filtered">噪音过滤</div></div>
</div>

<div class="main" id="cards"></div>

<script>
let currentLang = "zh";
let showFiltered = false;

const i18n = {
  zh: {
    title: "__FLAG__ __SITE_NAME__ __COUNTRY_ZH__预测市场话题日报",
    clusters: "📰 读取 __TOTAL__ 条 SourceIntel 热点",
    density: "新闻密度",
    articles: "条",
    total: "合计",
    q_label: "建议市场问题",
    resolution: "📎 结算源：",
    no_bet: "不适合作为预测市场话题",
    source_mix: "来源",
    show_filtered: "显示过滤",
    hide_filtered: "隐藏过滤",
    badge: { top: "🟢 TOP", candidate: "🟡 候选", watch: "👀 关注", drop: "⚫ 过滤" },
  },
  en: {
    title: "__FLAG__ __SITE_NAME__ __COUNTRY_EN__ Prediction Market Daily",
    clusters: "📰 __TOTAL__ SourceIntel hotspots loaded",
    density: "Coverage",
    articles: "articles",
    total: "Total",
    q_label: "Suggested Market Question",
    resolution: "📎 Resolution source: ",
    no_bet: "Not suitable as a prediction market topic",
    source_mix: "Sources",
    show_filtered: "Show filtered",
    hide_filtered: "Hide filtered",
    badge: { top: "🟢 TOP", candidate: "🟡 Candidate", watch: "👀 Watch", drop: "⚫ Drop" },
  }
};

const groups = __GROUPS_JSON__;

function siteBasePath() {
  let path = window.location.pathname;
  if (path.endsWith("/")) path += "index.html";
  if (path.includes("/id/reports/")) return path.split("/id/reports/")[0] + "/";
  if (path.includes("/id/")) return path.split("/id/")[0] + "/";
  if (path.includes("/reports/")) return path.split("/reports/")[0] + "/";
  return path.replace(/[^/]*$/, "");
}

function initRegionLinks() {
  const base = siteBasePath();
  document.querySelector('[data-region-link="ph"]').href = base + "index.html";
  document.querySelector('[data-region-link="id"]').href = base + "id/index.html";
}

function getDisposition(g) {
  const total = g.R + g.S + g.T + g.U + g.H;
  const veto = [g.R, g.S, g.T, g.U, g.H].filter(s => s === 0).length;
  if (!g.bettable) return "drop";
  if (veto === 0 && total >= 9) return "top";
  if (veto === 0 && total >= 7) return "candidate";
  return "watch";
}

const MAX_DENSITY = Math.max(...groups.map(g => g.density));

const sorted = [...groups].sort((a, b) => {
  const order = { top: 0, candidate: 1, watch: 2, drop: 3 };
  const da = getDisposition(a), db = getDisposition(b);
  if (order[da] !== order[db]) return order[da] - order[db];
  return (b.R+b.S+b.T+b.U+b.H) - (a.R+a.S+a.T+a.U+a.H);
});

function renderCards(lang) {
  const t = i18n[lang];
  const container = document.getElementById("cards");
  container.innerHTML = "";

  sorted.forEach(g => {
    const disp = getDisposition(g);
    if (disp === "drop" && !showFiltered) return;
    const total = g.R + g.S + g.T + g.U + g.H;
    const pct = Math.round((g.density / MAX_DENSITY) * 100);
    const title   = lang === "zh" ? g.name_zh : g.name_en;
    const sub     = lang === "zh" ? g.name_en : g.name_zh;
    const narr    = lang === "zh" ? (g.narrative_zh || g.narrative_en) : g.narrative_en;
    const showNarrative = shouldShowNarrative(g, disp, narr);
    const question = lang === "zh" ? (g.question_zh || g.question_en || g.question) : (g.question_en || g.question);
    const densityCount = `${g.density} ${t.articles}`;
    const sourceChips = Object.entries(g.source_mix || {}).map(([source, count]) =>
      `<span class="source-chip ${source}">${sourceLabel(source)} ${count}</span>`
    ).join("");
    const sourceItems = (g.source_examples || []).slice(0, 4).map(item => {
      const title = lang === "zh" ? (item.title_zh || item.title_en) : (item.title_en || item.title_zh);
      return `<div class="source-item ${item.source}">
        <span class="source-name">${sourceLabel(item.source)}</span>
        <span class="source-title" title="${escapeAttr(title)}">${escapeHtml(title)}</span>
      </div>`;
    }).join("");

    const card = document.createElement("div");
    card.className = `card ${disp}`;
    card.innerHTML = `
      <div class="card-header">
        <div class="card-title">
          ${title}
          <span class="sub">${sub}</span>
        </div>
        <span class="badge ${disp}">${t.badge[disp]}</span>
      </div>

      ${showNarrative ? `<p class="narrative">${escapeHtml(narr)}</p>` : ""}

      ${sourceChips ? `<div class="source-row" aria-label="${t.source_mix}">${sourceChips}</div>` : ""}
      ${sourceItems ? `<div class="source-list">${sourceItems}</div>` : ""}

      <div class="density-bar">
        <div class="label">${t.density}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        <div class="count">${densityCount}</div>
      </div>

      <div class="rstuh">
        ${["R","S","T","U","H"].map((l,i) => {
          const s = [g.R,g.S,g.T,g.U,g.H][i];
          return `<div class="dim"><div class="letter">${l}</div><div class="score s${s}">${s}</div></div>`;
        }).join("")}
        <div class="dim-total"><div class="letter">${t.total}</div><div class="score">${total}</div></div>
      </div>

      ${g.bettable && question ? `
      <div class="question-box">
        <div class="q-label">${t.q_label}</div>
        <div class="q-text">${question}</div>
        ${g.prob !== null && g.prob !== undefined ? (() => {
          const p = g.prob;
          const color = p >= 65 ? '#22c55e' : p >= 40 ? '#f59e0b' : '#ef4444';
          const reason = lang === 'zh' ? g.prob_reason_zh : g.prob_reason_en;
          return `<div class="prob-row">
            <div class="prob-label">${lang === 'zh' ? 'YES 概率' : 'YES prob'}</div>
            <div class="prob-bar-track"><div class="prob-bar-fill" style="width:${p}%;background:${color}"></div></div>
            <div class="prob-val" style="color:${color}">${p}%</div>
          </div>
          <div style="font-size:11px;color:#64748b;margin-top:4px">${reason || ''}</div>`;
        })() : ''}
        <div class="q-source" style="margin-top:8px">${t.resolution}${g.source || ''}</div>
      </div>` : `<div class="no-bet">${t.no_bet}</div>`}
    `;
    container.appendChild(card);
  });
}

function shouldShowNarrative(g, disp, narr) {
  if (!narr) return false;
  if (disp !== "drop") return true;
  if (g.density > 1) return true;
  const lowered = String(narr).toLowerCase();
  if (lowered.startsWith("google news groups this under")) return false;
  const first = (g.source_examples || [])[0] || {};
  const titles = [first.title_en, first.title_zh, g.name_en, g.name_zh]
    .filter(Boolean)
    .map(value => String(value).slice(0, 72).toLowerCase());
  return !titles.some(title => title && lowered.includes(title));
}

function sourceLabel(source) {
  return {
    google_news: "Google News",
    x_grok: "Grok/X"
  }[source] || source || "SourceIntel";
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[ch]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function updateFilterButton() {
  const btn = document.getElementById("filter-toggle");
  btn.textContent = showFiltered ? i18n[currentLang].hide_filtered : i18n[currentLang].show_filtered;
  btn.classList.toggle("active", showFiltered);
}

function toggleFiltered() {
  showFiltered = !showFiltered;
  updateFilterButton();
  renderCards(currentLang);
}

function setLang(lang) {
  currentLang = lang;
  document.querySelectorAll(".lang-btn").forEach(b => b.classList.toggle("active", b.textContent.trim() === (lang === "zh" ? "中文" : "EN")));
  document.getElementById("h-title").textContent = i18n[lang].title;
  document.getElementById("h-clusters").textContent = i18n[lang].clusters;
  document.querySelectorAll("[data-zh]").forEach(el => {
    el.textContent = el.dataset[lang];
  });
  updateFilterButton();
  renderCards(lang);
}

initRegionLinks();
updateFilterButton();
renderCards("zh");
</script>

</body></html>
"""


def classify_disposition(g: dict) -> str:
    if not g.get("bettable"):
        return "drop"
    total = g["R"] + g["S"] + g["T"] + g["U"] + g["H"]
    veto = sum(1 for k in "RSTUH" if g[k] == 0)
    if veto == 0 and total >= 9:
        return "top"
    if veto == 0 and total >= 7:
        return "candidate"
    return "watch"


def build_group(g: dict) -> dict:
    narr = g.get("narrative", "")
    question_en = g.get("suggested_question")
    question_zh = g.get("suggested_question_zh") or question_en
    return {
        "name_en": g.get("name", ""),
        "name_zh": g.get("name_zh") or g.get("name", ""),
        "density": g.get("density", 0),
        "R": g.get("R", 0),
        "S": g.get("S", 0),
        "T": g.get("T", 0),
        "U": g.get("U", 0),
        "H": g.get("H", 0),
        "narrative_en": narr,
        "narrative_zh": g.get("narrative_zh") or narr,
        "source_mix": g.get("source_mix", {}),
        "source_labels": g.get("source_labels", []),
        "source_examples": g.get("source_examples", []),
        "bettable": bool(g.get("bettable")),
        "question": question_en,
        "question_en": question_en,
        "question_zh": question_zh,
        "source": g.get("resolution_source", ""),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=dt.date.today().isoformat())
    parser.add_argument("--region", default="ph", choices=("ph", "id"))
    args = parser.parse_args()

    date = args.date
    region = get_region(args.region)
    base = Path(__file__).resolve().parent.parent
    reports_dir = base / "mvp" / "reports"
    if region.reports_subdir:
        reports_dir = reports_dir / region.reports_subdir
    json_path = reports_dir / f"clusters_{date}.json"
    if not json_path.exists():
        print(f"[ERR] Not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    groups_raw = data.get("groups", [])
    groups = [build_group(g) for g in groups_raw if g.get("name", "").lower() != "noise"]

    dispositions = [classify_disposition(g) for g in groups]
    n_top = dispositions.count("top")
    n_cand = dispositions.count("candidate")
    n_bet = sum(1 for g in groups if g["bettable"])
    total_entries = data.get("total_entries", sum(g["density"] for g in groups))
    n_noise = data.get("noise_count", len(data.get("noise", [])))

    groups_json = json.dumps(groups, ensure_ascii=False, indent=2)

    html = (HTML_TEMPLATE
            .replace("__SITE_NAME__", region.site_name)
            .replace("__FLAG__", region.flag)
            .replace("__COUNTRY_ZH__", region.country_name_zh)
            .replace("__COUNTRY_EN__", region.country_label_en)
            .replace("__PH_ACTIVE__", "active" if region.slug == "ph" else "")
            .replace("__ID_ACTIVE__", "active" if region.slug == "id" else "")
            .replace("__DATE__", date)
            .replace("__TOTAL__", str(total_entries))
            .replace("__N_GROUPS__", str(len(groups)))
            .replace("__N_TOP__", str(n_top))
            .replace("__N_CAND__", str(n_cand))
            .replace("__N_BET__", str(n_bet))
            .replace("__N_NOISE__", str(n_noise))
            .replace("__GROUPS_JSON__", groups_json))

    out_path = reports_dir / f"cluster_{date}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"[OK] HTML → {out_path}")


if __name__ == "__main__":
    main()
