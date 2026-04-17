"""
RSTUH 可下注性评分器
- R/S/T/H 用规则打分（免 LLM）
- U 可选 LLM 评估，无 API key 时用启发式

分层策略：早期 veto 快速过滤，只有通过规则的才消耗 LLM。
"""
from __future__ import annotations
import os
import json
import datetime as dt
from typing import Dict, Optional


# ============================================================
# 规则打分：R / S / T / H
# ============================================================

def score_R(topic: dict) -> Dict:
    """Resolvable: 结果能否客观判定？"""
    resolution = topic.get("resolution", {})
    templates = topic.get("market_templates", [])
    if not templates:
        return {"score": 0, "reason": "未定义 market_templates，无可判定的结果"}

    # 只要有 binary 或 numeric-bucket 类型的模板 → R>=1
    types = {t.get("type") for t in templates}
    if "binary" in types or "numeric-bucket" in types or "multi-outcome" in types:
        # 进一步看结算源是否明确
        if resolution.get("primary_source"):
            return {"score": 2, "reason": "有明确市场模板 + 结算源"}
        return {"score": 1, "reason": "有市场模板但结算源不明"}
    return {"score": 0, "reason": "市场模板类型不支持客观判定"}


def score_S(topic: dict) -> Dict:
    """Sourced: 有权威结算源吗？"""
    resolution = topic.get("resolution", {})
    primary = resolution.get("primary_source", "")
    url = resolution.get("primary_url", "")
    risk = resolution.get("dispute_risk", "high")

    if not primary:
        return {"score": 0, "reason": "未指定 resolution.primary_source", "proposed_source": None}
    if not url:
        return {"score": 1, "reason": "有源但无官方 URL", "proposed_source": primary}
    if risk == "high":
        return {"score": 1, "reason": "有源但争议风险高", "proposed_source": primary}
    return {"score": 2, "reason": f"{primary}（{risk} 争议风险）", "proposed_source": primary}


def score_T(topic: dict) -> Dict:
    """Time-bound: 有明确截止吗？"""
    cadence = topic.get("cadence", "")
    expires = topic.get("expires_at")

    if cadence in ("weekly", "monthly", "quarterly", "annual"):
        return {"score": 2, "reason": f"周期性话题（{cadence}），有自然时间锚点"}
    if cadence == "one-shot":
        if expires:
            return {"score": 2, "reason": f"一次性话题，截止 {expires}"}
        return {"score": 1, "reason": "one-shot 但未设置 expires_at"}
    if cadence == "continuous":
        return {"score": 1, "reason": "事件驱动，无固定截止；派生市场按事件设"}
    return {"score": 0, "reason": "未设定 cadence 或 expires_at"}


def score_H(topic: dict, signals: dict) -> Dict:
    """Hot: 有人讨论吗？综合规则 + 信号数据"""
    gn_en = len(signals.get("gnews_en", []))
    gn_tl = len(signals.get("gnews_tl", []))
    reddit_n = len(signals.get("reddit", []))
    total_news = gn_en + gn_tl

    # 分数阈值
    if total_news >= 10 and reddit_n >= 3:
        score = 2
        reason = f"多源报道 ({gn_en} EN + {gn_tl} TL) + Reddit 活跃 ({reddit_n} 帖)"
    elif total_news >= 5 or reddit_n >= 5:
        score = 2
        reason = f"{total_news} 篇新闻 / {reddit_n} 个 Reddit 帖"
    elif total_news >= 3 or reddit_n >= 2:
        score = 1
        reason = f"中等讨论：{total_news} 新闻 / {reddit_n} Reddit"
    else:
        score = 0
        reason = f"低热度：{total_news} 新闻 / {reddit_n} Reddit"

    # 双语热度加分（作为额外信号记录）
    bilingual = gn_en >= 2 and gn_tl >= 1
    return {
        "score": score,
        "reason": reason,
        "metrics": {
            "gnews_en": gn_en,
            "gnews_tl": gn_tl,
            "reddit": reddit_n,
            "bilingual_hot": bilingual,
        },
    }


# ============================================================
# U 维度：LLM 评估 或 启发式
# ============================================================

def score_U_heuristic(topic: dict, signals: dict, H_score: int) -> Dict:
    """无 API key 时的启发式：基于 H 与 category 粗估。"""
    cat = topic.get("category", "")

    # 经济/数据型话题：默认方向不确定
    if cat == "economy" and topic.get("subcategory") in ("energy-prices", "monetary-policy", "inflation"):
        return {"score": 2, "reason": "(heuristic) 数据型话题方向+幅度都不确定", "implied_prob": 0.50}

    # 灾害：事件是否发生取决于自然
    if cat == "disaster":
        return {"score": 2, "reason": "(heuristic) 自然事件高度不确定", "implied_prob": 0.40}

    # 地缘：事件频率高但方向不定
    if cat == "geopolitics":
        return {"score": 2, "reason": "(heuristic) 地缘事件频发但具体难测", "implied_prob": 0.55}

    # 政治：倾向需要具体分析，默认给 1
    if cat == "politics":
        if H_score == 2:
            # 高热度下政治话题常已倾向明朗
            return {"score": 1, "reason": "(heuristic) 政治热点常有舆论倾向", "implied_prob": 0.35}
        return {"score": 2, "reason": "(heuristic) 未高度曝光，仍有悬念", "implied_prob": 0.50}

    return {"score": 1, "reason": "(heuristic) 默认中性", "implied_prob": 0.50}


def score_U_llm(topic: dict, signals: dict, api_key: str) -> Dict:
    """用 Gemini Flash 评 U 维度（留接口，具体实现在 run_daily.py 主调度）。"""
    # 这里留简化 stub，实际调用放在 classify_with_gemini() 函数里
    raise NotImplementedError("call classify_with_gemini() directly instead")


# ============================================================
# 分层评分主函数
# ============================================================

def score_topic(topic: dict, signals: dict, use_llm: bool = False, api_key: Optional[str] = None) -> Dict:
    """给单个话题完整评分。
    返回按 Schema v1.4 的 bettability 对象。
    """
    R = score_R(topic)
    S = score_S(topic)
    T = score_T(topic)
    H = score_H(topic, signals)

    rule_scores = {"R": R["score"], "S": S["score"], "T": T["score"], "H": H["score"]}
    veto = [dim for dim, sc in rule_scores.items() if sc == 0]

    # 分层：已被 veto 的话题不浪费 LLM
    if veto:
        U = {"score": 0, "reason": "(skipped) 早期 veto", "implied_prob": None}
    elif use_llm and api_key:
        # 这里在 pipeline 里调用
        U = {"score": None, "reason": "(pending LLM)", "implied_prob": None}
    else:
        U = score_U_heuristic(topic, signals, H["score"])

    if U["score"] == 0 and "U" not in veto:
        veto.append("U")

    total = (R["score"] + S["score"] + T["score"] +
             (U["score"] if U["score"] is not None else 0) +
             H["score"])

    # 根据 decision_rules 决定处置
    heat_score = _compute_heat_score(H["metrics"])
    disposition = _decide_disposition(total, veto, heat_score, H["score"])

    return {
        "R": R,
        "S": S,
        "T": T,
        "U": U,
        "H": H,
        "total": total,
        "veto_dimensions": veto,
        "disposition": disposition,
        "heat_score": heat_score,
        "scored_at": dt.datetime.now().isoformat(),
    }


def _compute_heat_score(metrics: dict) -> float:
    """Heat score 0-1。简易公式，后续可按 YAML 中权重调整。"""
    gn = metrics.get("gnews_en", 0) + metrics.get("gnews_tl", 0)
    rd = metrics.get("reddit", 0)
    # 对数缩放 + 加权
    import math
    gn_comp = min(math.log1p(gn) / math.log1p(30), 1.0)   # 30 篇封顶
    rd_comp = min(math.log1p(rd) / math.log1p(10), 1.0)   # 10 帖封顶
    bilingual = 0.1 if metrics.get("bilingual_hot") else 0.0
    return round(0.6 * gn_comp + 0.3 * rd_comp + bilingual, 2)


def _decide_disposition(total: int, veto: list, heat_score: float, H_score: int) -> str:
    """按 classifier_calibration_examples.json 里的规则。"""
    has_su_veto = ("S" in veto) or ("U" in veto)

    if has_su_veto and heat_score >= 0.7:
        return "DROP_BUT_DIGEST"
    if veto and total <= 6:
        return "DROP"
    if not veto and total >= 9:
        return "TOP"
    if not veto and 7 <= total <= 8:
        return "CANDIDATE"
    if 5 <= total <= 6:
        return "WATCH"
    if total >= 7 and veto == ["T"]:
        return "WATCH"
    return "DROP"


# ============================================================
# Gemini Flash LLM 调用（只评 U + 生成 suggested market question）
# ============================================================

def classify_with_gemini(topic: dict, signals: dict, scores: dict, api_key: str) -> dict:
    """调用 Gemini Flash 评 U 维度 + 生成 suggested_market_question。
    scores: score_topic 的输出。
    """
    try:
        from google import genai
    except ImportError:
        print("  [INFO] google-genai 未安装。pip install google-genai")
        return scores

    client = genai.Client(api_key=api_key)

    # 载入 few-shot
    calibration_path = os.path.join(os.path.dirname(__file__), "..", "classifier_calibration_examples.json")
    calibration = ""
    if os.path.exists(calibration_path):
        with open(calibration_path) as f:
            calibration = f.read()

    # 提取最多 6 个代表性标题作为上下文
    headlines = ([f"[EN] {x['title']} ({x.get('source','')})" for x in signals["gnews_en"][:3]] +
                 [f"[TL] {x['title']}" for x in signals["gnews_tl"][:2]] +
                 [f"[Reddit] {x['title']}" for x in signals["reddit"][:2]])
    headlines_text = "\n".join(headlines)

    prompt = f"""你是预测市场可下注性评估员。仅对 U 维度打分，并生成建议市场问题。

【校准样本】
{calibration}

【待评估话题】
topic_id: {topic['topic_id']}
topic_name: {topic['topic_name']}
category: {topic['category']}
cadence: {topic.get('cadence')}
resolution_source: {topic['resolution']['primary_source']}

【今日标题样本】
{headlines_text}

【已评分】
R={scores['R']['score']}, S={scores['S']['score']}, T={scores['T']['score']}, H={scores['H']['score']}

请严格输出 JSON（无多余文字）：
{{
  "U": {{"score": 0|1|2, "reason": "...", "implied_prob": 0.0-1.0}},
  "suggested_market_question": "Will ..."
}}
"""
    try:
        response = client.models.generate_content(
            model="gemini-3.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        # 去掉可能的 markdown ```json
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        scores["U"] = result["U"]
        scores["suggested_market_question"] = result.get("suggested_market_question")
        # 重算 total
        scores["total"] = (scores["R"]["score"] + scores["S"]["score"] +
                          scores["T"]["score"] + scores["U"]["score"] +
                          scores["H"]["score"])
        # 重新判 veto
        scores["veto_dimensions"] = [d for d in "RSTUH"
                                     if scores[d]["score"] == 0]
        scores["disposition"] = _decide_disposition(scores["total"],
                                                    scores["veto_dimensions"],
                                                    scores["heat_score"],
                                                    scores["H"]["score"])
    except Exception as e:
        print(f"  [WARN] Gemini call failed: {e}. Falling back to heuristic.")
    return scores
