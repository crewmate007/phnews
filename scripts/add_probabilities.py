"""
Ask Gemini for a YES probability (0-100) + bilingual reasoning for each
bettable group, then patch the generated HTML so the probability bar + reason
render (matches the template used in docs/index.html).

Usage:
  python3 scripts/add_probabilities.py                # today
  python3 scripts/add_probabilities.py 2026-04-20     # specific date

Reads:  mvp/reports/clusters_YYYY-MM-DD.json
Reads+writes: mvp/reports/cluster_YYYY-MM-DD.html
"""
from __future__ import annotations
import json
import os
import re
import sys
import datetime as dt
from pathlib import Path


PROMPT = """You are a prediction-market analyst.

For each group below, give a YES probability (integer 0-100) for its
`suggested_question`, plus a short reason in Chinese and English (≤40 chars each).
Be calibrated: probabilities should reflect base rates and the specific evidence
in the narrative, not just enthusiasm. Avoid 50% unless genuinely uncertain.

Today is {date}.

Return ONLY a JSON array, one object per input group (same order, same names).
Schema per item:
{{
  "name": "...",
  "prob": <int 0-100>,
  "prob_reason_zh": "...",
  "prob_reason_en": "..."
}}

Groups:
{groups}
"""


def load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    # fallback: .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GEMINI_API_KEY not set and .env missing")


def call_gemini(bettable_groups: list, api_key: str) -> list:
    from google import genai

    payload_lines = []
    for g in bettable_groups:
        payload_lines.append(json.dumps({
            "name": g["name"],
            "narrative": g.get("narrative", ""),
            "suggested_question": g.get("suggested_question", ""),
            "resolution_source": g.get("resolution_source", ""),
        }, ensure_ascii=False))

    prompt = PROMPT.format(
        date=dt.date.today().isoformat(),
        groups="\n".join(payload_lines),
    )
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
    )
    text = resp.text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def patch_html(html: str, probs_by_name: dict) -> str:
    """Inject prob/prob_reason_zh/prob_reason_en into each group object and
    upgrade the render script so the prob bar appears (like docs/index.html)."""

    # 1) Insert prob fields into each embedded group object.
    # Groups are emitted by gen_html.py as JSON (ensure_ascii=False, indent=2)
    # assigned to `const groups = ...;`. Parse, patch, re-emit.
    m = re.search(r"const groups = (\[[\s\S]*?\]);", html)
    if not m:
        raise RuntimeError("Could not find `const groups = [...]` in HTML")
    groups = json.loads(m.group(1))
    for g in groups:
        info = probs_by_name.get(g["name_en"])
        if info and g.get("bettable"):
            g["prob"] = info["prob"]
            g["prob_reason_zh"] = info["prob_reason_zh"]
            g["prob_reason_en"] = info["prob_reason_en"]
        else:
            g["prob"] = None
            g["prob_reason_zh"] = ""
            g["prob_reason_en"] = ""
    new_groups = json.dumps(groups, ensure_ascii=False, indent=2)
    html = html.replace(m.group(1), new_groups, 1)

    # 2) Add the prob CSS (before the closing </style>).
    prob_css = """
  .prob-row { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
  .prob-label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }
  .prob-bar-track { flex: 1; height: 6px; background: #1e2535; border-radius: 3px; }
  .prob-bar-fill { height: 100%; border-radius: 3px; transition: width 0.4s ease; }
  .prob-val { font-size: 14px; font-weight: 700; white-space: nowrap; min-width: 38px; text-align: right; }
"""
    if ".prob-row" not in html:
        html = html.replace("</style>", prob_css + "\n</style>", 1)

    # 3) Replace the question-box render block to include the prob bar.
    old_block = """      ${g.bettable && g.question ? `
      <div class="question-box">
        <div class="q-label">${t.q_label}</div>
        <div class="q-text">${g.question}</div>
        <div class="q-source" style="margin-top:8px">${t.resolution}${g.source || ''}</div>
      </div>` : `<div class="no-bet">${t.no_bet}</div>`}"""
    new_block = """      ${g.bettable && g.question ? `
      <div class="question-box">
        <div class="q-label">${t.q_label}</div>
        <div class="q-text">${g.question}</div>
        ${g.prob !== null && g.prob !== undefined ? (() => {
          const p = g.prob;
          const color = p >= 65 ? '#22c55e' : p >= 40 ? '#f59e0b' : '#ef4444';
          const reason = lang === 'zh' ? g.prob_reason_zh : g.prob_reason_en;
          return `<div class="prob-row">
            <div class="prob-label">${lang === 'zh' ? 'YES 概率' : 'YES prob'}</div>
            <div class="prob-bar-track"><div class="prob-bar-fill" style="width:${p}%;background:${color}"></div></div>
            <div class="prob-val" style="color:${color}">${p}%</div>
          </div>
          <div style="font-size:11px;color:#64748b;margin-top:4px">${reason}</div>`;
        })() : ''}
        <div class="q-source" style="margin-top:8px">${t.resolution}${g.source || ''}</div>
      </div>` : `<div class="no-bet">${t.no_bet}</div>`}"""
    if old_block in html:
        html = html.replace(old_block, new_block, 1)
    return html


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    base = Path(__file__).resolve().parent.parent
    json_path = base / "mvp" / "reports" / f"clusters_{date}.json"
    html_path = base / "mvp" / "reports" / f"cluster_{date}.html"
    if not json_path.exists():
        print(f"[ERR] missing {json_path}", file=sys.stderr)
        sys.exit(1)
    if not html_path.exists():
        print(f"[ERR] missing {html_path} — run gen_html.py first", file=sys.stderr)
        sys.exit(1)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    bettable = [g for g in data.get("groups", []) if g.get("bettable")]
    if not bettable:
        print("[INFO] No bettable groups; nothing to do.")
        return

    api_key = load_api_key()
    print(f"[INFO] Asking Gemini for probabilities on {len(bettable)} groups...")
    out = call_gemini(bettable, api_key)
    probs_by_name = {item["name"]: item for item in out}

    html = html_path.read_text(encoding="utf-8")
    html = patch_html(html, probs_by_name)
    html_path.write_text(html, encoding="utf-8")
    print(f"[OK] Patched {html_path}")


if __name__ == "__main__":
    main()
