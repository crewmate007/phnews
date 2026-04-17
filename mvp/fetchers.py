"""
Google News + Reddit 抓取模块
支持 live 和 mock 两种模式。mock 模式用于沙箱测试或离线开发。
"""
from __future__ import annotations
import feedparser
import urllib.parse
import urllib.request
import ssl
import time
import datetime as dt
from typing import List, Dict

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/123.0.0.0 Safari/537.36")


REDDIT_USER_AGENT = "ph-news-bot:v0.1 (by /u/ph_markets_research)"

def _fetch_url(url: str, timeout: int = 15, reddit: bool = False) -> str:
    """用 urllib + certifi 抓 URL，绕开 feedparser 的 HTTP 层。"""
    # Reddit 要求格式为 <platform>:<app>:<version> (by /u/<username>)
    ua = REDDIT_USER_AGENT if reddit else USER_AGENT
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ============================================================
# Google News RSS
# ============================================================

def build_gnews_url(query: str, lang: str = "en", country: str = "PH") -> str:
    """把 query 字符串包装成 Google News RSS 的搜索 URL。"""
    hl = "en-PH" if lang == "en" else "tl"
    q = urllib.parse.quote(query)
    return (f"https://news.google.com/rss/search?q={q}"
            f"&hl={hl}&gl={country}&ceid={country}:{lang}")


def fetch_gnews(query: str, lang: str = "en") -> List[Dict]:
    """抓一个 Google News 查询。返回文章 dict 列表。"""
    url = build_gnews_url(query, lang)
    content = _fetch_url(url)
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        items.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "source": entry.get("source", {}).get("title", "") if isinstance(entry.get("source"), dict) else str(entry.get("source", "")),
            "summary": entry.get("summary", ""),
        })
    return items


# ============================================================
# Reddit RSS
# ============================================================

def fetch_reddit(feed_url: str) -> List[Dict]:
    """抓一个 Reddit RSS feed。"""
    content = _fetch_url(feed_url, reddit=True)
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        items.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "author": entry.get("author", ""),
            "summary": entry.get("summary", ""),
        })
    return items


# ============================================================
# 主抓取接口
# ============================================================

def fetch_topic_signals(topic: dict, mock: bool = False) -> dict:
    """给一个话题拉所有信号。返回聚合字典。"""
    if mock:
        return _mock_signals(topic)

    signals = {
        "topic_id": topic["topic_id"],
        "fetched_at": dt.datetime.now().isoformat(),
        "gnews_en": [],
        "gnews_tl": [],
        "reddit": [],
    }
    queries = topic.get("queries", {})
    gnews = queries.get("google_news", {})

    for q in gnews.get("en", []):
        try:
            signals["gnews_en"].extend(fetch_gnews(q, "en"))
            time.sleep(1)  # 限速
        except Exception as e:
            print(f"  [WARN] gnews en '{q[:40]}...' failed: {e}")

    for q in gnews.get("tl", []):
        try:
            signals["gnews_tl"].extend(fetch_gnews(q, "tl"))
            time.sleep(1)
        except Exception as e:
            print(f"  [WARN] gnews tl '{q[:40]}...' failed: {e}")

    for r in queries.get("reddit", []):
        try:
            results = fetch_reddit(r["feed_url"])
            signals["reddit"].extend(results)
            time.sleep(2)  # Reddit 限速，必须慢一点
        except Exception as e:
            err = str(e)
            if "403" in err or "blocked" in err.lower():
                print(f"  [WARN] reddit '{r.get('subreddit')}' blocked (403) — Reddit 限速，稍后重试")
            elif "429" in err:
                print(f"  [WARN] reddit '{r.get('subreddit')}' rate-limited (429) — 等几分钟再跑")
            else:
                print(f"  [WARN] reddit '{r.get('subreddit')}' failed: {err[:80]}")

    # 按链接去重
    signals["gnews_en"] = _dedupe(signals["gnews_en"])
    signals["gnews_tl"] = _dedupe(signals["gnews_tl"])
    signals["reddit"] = _dedupe(signals["reddit"])
    return signals


def _dedupe(items: List[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for it in items:
        key = it.get("link", it.get("title"))
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


# ============================================================
# Mock 数据（沙箱测试用 / 离线开发）
# ============================================================

_MOCK_FIXTURES = {
    "ph-fuel-weekly": {
        "gnews_en": [
            {"title": "Oil firms to implement big-time rollback next week", "source": "Inquirer", "link": "https://mock/1", "published": "Mon, 14 Apr 2026"},
            {"title": "Diesel prices to drop PHP 1.20/L, gasoline by PHP 0.90/L", "source": "Rappler", "link": "https://mock/2", "published": "Mon, 14 Apr 2026"},
            {"title": "DOE confirms fuel price rollback for April 15 implementation", "source": "Philstar", "link": "https://mock/3", "published": "Mon, 14 Apr 2026"},
            {"title": "Jeepney drivers welcome oil price rollback after weeks of hikes", "source": "GMA News", "link": "https://mock/4", "published": "Mon, 14 Apr 2026"},
            {"title": "OPEC+ decision pushes Brent lower, good news for PH motorists", "source": "BusinessWorld", "link": "https://mock/5", "published": "Sun, 13 Apr 2026"},
            {"title": "Peso strengthening adds to fuel price rollback this week", "source": "Manila Bulletin", "link": "https://mock/6", "published": "Mon, 14 Apr 2026"},
            {"title": "DOE Oil Monitoring: Metro Manila average diesel now PHP 56.20/L", "source": "PNA", "link": "https://mock/7", "published": "Mon, 14 Apr 2026"},
        ],
        "gnews_tl": [
            {"title": "Rollback sa presyo ng gasolina, idedeklara ngayong linggo", "source": "Abante", "link": "https://mock/t1", "published": "Mon, 14 Apr 2026"},
            {"title": "Bumababang presyo ng diesel, pasasalamatan ng mga driver", "source": "Bandera", "link": "https://mock/t2", "published": "Mon, 14 Apr 2026"},
            {"title": "DOE: Malaking rollback sa gasolina para sa Abril 15", "source": "Pilipino Star Ngayon", "link": "https://mock/t3", "published": "Mon, 14 Apr 2026"},
            {"title": "Mga tsuper at operator, natuwa sa rollback", "source": "Remate", "link": "https://mock/t4", "published": "Mon, 14 Apr 2026"},
            {"title": "Kaya ba matuloy ang rollback? Eksperto, may pag-aalinlangan", "source": "Abante", "link": "https://mock/t5", "published": "Sun, 13 Apr 2026"},
        ],
        "reddit": [
            {"title": "Big rollback incoming this week - DOE", "link": "https://mock/r1", "published": "Mon"},
            {"title": "Finally some relief at the pump", "link": "https://mock/r2", "published": "Mon"},
            {"title": "How long will this rollback last?", "link": "https://mock/r3", "published": "Mon"},
            {"title": "Impact on inflation: discussion", "link": "https://mock/r4", "published": "Sun"},
        ],
    },

    "ph-bsp-rate": {
        "gnews_en": [
            {"title": "BSP expected to hold rates steady at May 15 meeting, analysts say", "source": "Reuters", "link": "https://mock/b1", "published": "Mon"},
            {"title": "Inflation data keeps BSP on cautious path", "source": "BusinessWorld", "link": "https://mock/b2", "published": "Mon"},
            {"title": "Governor signals 'data-dependent' approach for next decision", "source": "Philstar", "link": "https://mock/b3", "published": "Sun"},
            {"title": "Markets price in small chance of rate cut, peso reacts", "source": "Bloomberg", "link": "https://mock/b4", "published": "Sun"},
            {"title": "BSP Monetary Board to meet May 15, watch list", "source": "Inquirer", "link": "https://mock/b5", "published": "Sat"},
        ],
        "gnews_tl": [
            {"title": "BSP, aasahan ang pag-mentaining sa interes sa Mayo", "source": "Bandera", "link": "https://mock/bt1", "published": "Mon"},
        ],
        "reddit": [
            {"title": "What are we expecting from BSP next month?", "link": "https://mock/br1", "published": "Mon"},
            {"title": "Rate cut or hold? phinvest predictions thread", "link": "https://mock/br2", "published": "Sun"},
        ],
    },

    "ph-south-china-sea": {
        "gnews_en": [
            {"title": "Chinese coast guard water cannons PH resupply boat at Ayungin", "source": "Reuters", "link": "https://mock/s1", "published": "Mon"},
            {"title": "PCG condemns 'aggressive' Chinese action near Scarborough", "source": "Rappler", "link": "https://mock/s2", "published": "Mon"},
            {"title": "DFA summons Chinese envoy over latest maritime incident", "source": "Inquirer", "link": "https://mock/s3", "published": "Mon"},
            {"title": "US condemns Chinese actions, reaffirms Mutual Defense Treaty", "source": "AP", "link": "https://mock/s4", "published": "Mon"},
            {"title": "Philippines files 200th diplomatic protest this year", "source": "Philstar", "link": "https://mock/s5", "published": "Sun"},
            {"title": "Analysis: Why the next 30 days matter for West PH Sea", "source": "Nikkei Asia", "link": "https://mock/s6", "published": "Sun"},
        ],
        "gnews_tl": [
            {"title": "China, pinaghagisan ng water cannon ang PH bangka sa Ayungin", "source": "Abante", "link": "https://mock/st1", "published": "Mon"},
        ],
        "reddit": [
            {"title": "Latest Ayungin incident footage", "link": "https://mock/sr1", "published": "Mon"},
            {"title": "How long can PH keep filing diplomatic protests?", "link": "https://mock/sr2", "published": "Mon"},
            {"title": "MDT activation: actual probability discussion", "link": "https://mock/sr3", "published": "Sun"},
        ],
    },

    "ph-typhoon-season": {
        # 4月不是台风季，模拟低热度
        "gnews_en": [
            {"title": "PAGASA: Early onset possible for 2026 typhoon season", "source": "Inquirer", "link": "https://mock/t1", "published": "Sun"},
        ],
        "gnews_tl": [],
        "reddit": [],
    },

    "ph-sara-impeachment": {
        "gnews_en": [
            {"title": "Senate impeachment trial schedule still uncertain, says senator", "source": "Rappler", "link": "https://mock/i1", "published": "Mon"},
            {"title": "VP Sara Duterte dismisses 'witch hunt' as trial looms", "source": "Inquirer", "link": "https://mock/i2", "published": "Mon"},
            {"title": "Marcos allies push for June start of impeachment trial", "source": "Philstar", "link": "https://mock/i3", "published": "Sun"},
            {"title": "Legal experts: conviction requires 2/3 vote, unlikely now", "source": "BusinessWorld", "link": "https://mock/i4", "published": "Sun"},
        ],
        "gnews_tl": [
            {"title": "Paglilitis ng impeachment, posibleng maantala pa", "source": "Pilipino Star Ngayon", "link": "https://mock/it1", "published": "Mon"},
        ],
        "reddit": [
            {"title": "Will Sara actually be convicted? Odds thread", "link": "https://mock/ir1", "published": "Mon"},
            {"title": "UniTeam breakup - where we are now", "link": "https://mock/ir2", "published": "Mon"},
            {"title": "Impeachment timeline explainer", "link": "https://mock/ir3", "published": "Sun"},
        ],
    },
}


def _mock_signals(topic: dict) -> dict:
    tid = topic["topic_id"]
    fixture = _MOCK_FIXTURES.get(tid, {"gnews_en": [], "gnews_tl": [], "reddit": []})
    return {
        "topic_id": tid,
        "fetched_at": dt.datetime.now().isoformat(),
        "gnews_en": fixture["gnews_en"],
        "gnews_tl": fixture["gnews_tl"],
        "reddit": fixture["reddit"],
        "_mock": True,
    }
