"""
Google News 话题聚类发现模块

从 Google News Philippines 顶部新闻 RSS 获取话题聚类，
与现有话题比对后输出新发现的候选话题。
"""
from __future__ import annotations
import json
import datetime as dt
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Optional

from fetchers import _fetch_url

import feedparser

# Google News PH RSS feeds
# Top Stories + 三个对预测市场有价值的 section
GNEWS_FEEDS = {
    "Top Stories": "https://news.google.com/rss?gl=PH&hl=en-PH&ceid=PH:en",
    "Nation": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRFZxYUdjU0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=PH&hl=en-PH&ceid=PH:en",
    "Business": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx6TVdZU0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=PH&hl=en-PH&ceid=PH:en",
    "World": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=PH&hl=en-PH&ceid=PH:en",
}


# ============================================================
# HTML 解析：提取聚类中的子文章
# ============================================================

class _ClusterParser(HTMLParser):
    """解析 Google News RSS description 里的 <ol><li><a>...</a><font>source</font> 结构。"""

    def __init__(self):
        super().__init__()
        self.articles: List[Dict[str, str]] = []
        self._in_a = False
        self._in_font = False
        self._text = ""
        self._source = ""
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._in_a = True
            self._text = ""
            self._href = dict(attrs).get("href", "")
        elif tag == "font":
            self._in_font = True
            self._source = ""

    def handle_data(self, data):
        if self._in_a:
            self._text += data
        elif self._in_font:
            self._source += data

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            self.articles.append({
                "title": self._text.strip(),
                "link": self._href,
                "source": "",
            })
            self._in_a = False
        elif tag == "font" and self._in_font:
            if self.articles:
                self.articles[-1]["source"] = self._source.strip()
            self._in_font = False


def _parse_cluster_articles(description_html: str) -> List[Dict[str, str]]:
    parser = _ClusterParser()
    parser.feed(description_html)
    return parser.articles


# ============================================================
# 抓取 Google News 聚类
# ============================================================

def fetch_gnews_clusters(sections: List[str] = None) -> List[Dict]:
    """从 Google News PH 多个 section 获取全部聚类，按 link 去重。

    Args:
        sections: 要抓的 section 名称列表。None = 全部。
                  可选值: "Top Stories", "Nation", "Business", "World"
    """
    if sections is None:
        sections = list(GNEWS_FEEDS.keys())

    clusters = []
    seen_links = set()

    for section_name in sections:
        url = GNEWS_FEEDS.get(section_name)
        if not url:
            print(f"  [WARN] unknown section: {section_name}")
            continue
        try:
            content = _fetch_url(url)
            feed = feedparser.parse(content)
            section_new = 0
            for entry in feed.entries:
                link = entry.get("link", "")
                # 按 link 去重（同一 cluster 在不同 section 出现时只保留首次）
                if link in seen_links:
                    continue
                seen_links.add(link)

                desc = entry.get("summary", entry.get("description", ""))
                sub_articles = _parse_cluster_articles(desc)
                sources = list({a["source"] for a in sub_articles if a["source"]})

                clusters.append({
                    "cluster_title": entry.get("title", ""),
                    "published": entry.get("published", ""),
                    "link": link,
                    "section": section_name,
                    "sub_articles": sub_articles,
                    "source_count": len(sources),
                    "sources": sources,
                })
                section_new += 1
            print(f"  [OK] {section_name}: {len(feed.entries)} entries, {section_new} unique new")
        except Exception as e:
            print(f"  [WARN] {section_name} fetch failed: {e}")

    return clusters


# ============================================================
# 与现有话题匹配
# ============================================================

def _extract_topic_keywords(topic: dict) -> set:
    """从话题 YAML 中提取关键词集合，用于匹配。"""
    words = set()

    # topic_name
    for w in _tokenize(topic.get("topic_name", "")):
        words.add(w)

    # google_news 查询中的关键词
    queries = topic.get("queries", {})
    gnews = queries.get("google_news", {})
    for lang_queries in gnews.values():
        if isinstance(lang_queries, list):
            for q in lang_queries:
                # 去掉 Google News 时间过滤语法
                clean = re.sub(r'when:\w+', '', q)
                clean = re.sub(r'["\']', '', clean)
                for w in _tokenize(clean):
                    words.add(w)

    # canonical_entities 的 aliases
    for ent in topic.get("canonical_entities", []):
        for alias in ent.get("aliases", []):
            for w in _tokenize(alias):
                words.add(w)

    return words


# 停用词（不参与匹配）
_STOP_WORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "be", "been", "will", "shall", "may",
    "can", "do", "does", "did", "not", "no", "but", "if", "as", "by",
    "from", "with", "this", "that", "it", "its", "has", "have", "had",
    "vs", "says", "said", "new", "news", "philippines", "philippine",
    "ph", "filipino", "manila",
}


def _stem(word: str) -> str:
    """极简词干化：只去掉复数 s，使 rate/rates、price/prices 能匹配。"""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"      # countries → country
    if len(word) > 3 and word.endswith("s") and word[-2] not in "su":
        return word[:-1]            # rates → rate, prices → price
    return word


def _tokenize(text: str) -> List[str]:
    """拆分文本为小写 token，去掉停用词和短词，做简单词干化。"""
    tokens = re.findall(r'[a-zA-Z]{3,}', text.lower())
    return [_stem(t) for t in tokens if t not in _STOP_WORDS]


def _cluster_text(cluster: dict) -> str:
    """把聚类的标题和子文章标题拼成一段文本。"""
    parts = [cluster["cluster_title"]]
    for art in cluster["sub_articles"]:
        parts.append(art["title"])
    return " ".join(parts)


def match_cluster_to_topics(cluster: dict, topics: list,
                            threshold: int = 2) -> Optional[str]:
    """尝试把一个聚类匹配到现有话题。
    返回匹配的 topic_id 或 None。

    threshold: 需要至少多少个关键词交集才算匹配。
    """
    cluster_tokens = set(_tokenize(_cluster_text(cluster)))

    best_topic = None
    best_overlap = 0

    for topic in topics:
        topic_kw = _extract_topic_keywords(topic)
        overlap = len(cluster_tokens & topic_kw)
        if overlap > best_overlap:
            best_overlap = overlap
            best_topic = topic["topic_id"]

    if best_overlap >= threshold:
        return best_topic
    return None


# ============================================================
# 主发现接口
# ============================================================

def discover_new_topics(topics: list,
                        mock: bool = False) -> Dict[str, list]:
    """发现新话题。

    返回:
        {
            "matched": [{"cluster": ..., "matched_topic": "ph-fuel-weekly"}],
            "new": [{"cluster": ..., "matched_topic": None}],
            "fetched_at": "...",
        }
    """
    if mock:
        clusters = _mock_clusters()
    else:
        clusters = fetch_gnews_clusters()

    matched = []
    new = []

    for cluster in clusters:
        topic_id = match_cluster_to_topics(cluster, topics)
        entry = {
            "cluster": cluster,
            "matched_topic": topic_id,
        }
        if topic_id:
            matched.append(entry)
        else:
            new.append(entry)

    return {
        "matched": matched,
        "new": new,
        "total_clusters": len(clusters),
        "fetched_at": dt.datetime.now().isoformat(),
    }


def save_discoveries(result: dict, output_dir: str):
    """把发现结果保存为 JSON。"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    path = Path(output_dir) / f"discoveries_{today}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(path)


# ============================================================
# Mock 数据
# ============================================================

def _mock_clusters() -> List[Dict]:
    """Mock 聚类数据，用于离线测试。"""
    return [
        {
            "cluster_title": "Major rollback in fuel prices in the Philippines - Human Resources Online",
            "published": "Wed, 15 Apr 2026 07:57:15 GMT",
            "link": "https://mock/cluster1",
            "section": "Top Stories",
            "sub_articles": [
                {"title": "Major rollback in fuel prices in the Philippines", "source": "HR Online", "link": ""},
                {"title": "P4 to P21 rollback seen for gasoline, diesel Tuesday", "source": "PNA", "link": ""},
                {"title": "Big rollbacks expected again next week", "source": "ABS-CBN", "link": ""},
                {"title": "DOE sees another fuel price rollback", "source": "Philstar", "link": ""},
                {"title": "OIL PRICE WATCH as of April 16, 2026", "source": "Inquirer", "link": ""},
            ],
            "source_count": 5,
            "sources": ["HR Online", "PNA", "ABS-CBN", "Philstar", "Inquirer"],
        },
        {
            "cluster_title": "BSP expected to hold rates steady at May meeting - Reuters",
            "published": "Wed, 15 Apr 2026 06:00:00 GMT",
            "link": "https://mock/cluster2",
            "section": "Business",
            "sub_articles": [
                {"title": "BSP expected to hold rates steady at May meeting", "source": "Reuters", "link": ""},
                {"title": "Inflation data keeps BSP on cautious path", "source": "BusinessWorld", "link": ""},
            ],
            "source_count": 2,
            "sources": ["Reuters", "BusinessWorld"],
        },
        {
            "cluster_title": "Massive earthquake hits Mindanao, tsunami warning issued - Reuters",
            "published": "Wed, 15 Apr 2026 10:00:00 GMT",
            "link": "https://mock/cluster3",
            "section": "Nation",
            "sub_articles": [
                {"title": "Massive earthquake hits Mindanao, tsunami warning issued", "source": "Reuters", "link": ""},
                {"title": "7.2 magnitude earthquake rocks Davao region", "source": "Inquirer", "link": ""},
                {"title": "PHIVOLCS raises Alert Level after Mindanao quake", "source": "Rappler", "link": ""},
                {"title": "Thousands evacuated in coastal Mindanao after quake", "source": "GMA News", "link": ""},
                {"title": "Marcos orders immediate response to Mindanao earthquake", "source": "PNA", "link": ""},
            ],
            "source_count": 5,
            "sources": ["Reuters", "Inquirer", "Rappler", "GMA News", "PNA"],
        },
        {
            "cluster_title": "POGO ban: 200 more Chinese nationals deported this week - Inquirer",
            "published": "Wed, 15 Apr 2026 09:00:00 GMT",
            "link": "https://mock/cluster4",
            "section": "Nation",
            "sub_articles": [
                {"title": "POGO ban: 200 more Chinese nationals deported this week", "source": "Inquirer", "link": ""},
                {"title": "BI intensifies deportation of illegal POGO workers", "source": "Philstar", "link": ""},
                {"title": "Senate probe reveals remaining underground POGO operations", "source": "Rappler", "link": ""},
            ],
            "source_count": 3,
            "sources": ["Inquirer", "Philstar", "Rappler"],
        },
        {
            "cluster_title": "Sara Duterte impeachment trial schedule still uncertain - Rappler",
            "published": "Wed, 15 Apr 2026 05:00:00 GMT",
            "link": "https://mock/cluster5",
            "section": "Top Stories",
            "sub_articles": [
                {"title": "Senate impeachment trial schedule still uncertain", "source": "Rappler", "link": ""},
                {"title": "VP Sara dismisses witch hunt as trial looms", "source": "Inquirer", "link": ""},
                {"title": "Marcos allies push for June start of impeachment trial", "source": "Philstar", "link": ""},
            ],
            "source_count": 3,
            "sources": ["Rappler", "Inquirer", "Philstar"],
        },
        {
            "cluster_title": "Maharlika Corp: Fund can invest in oil depot, power infra - ABS-CBN",
            "published": "Wed, 15 Apr 2026 08:00:00 GMT",
            "link": "https://mock/cluster6",
            "section": "Business",
            "sub_articles": [
                {"title": "Maharlika Corp: Fund can invest in oil depot, power infra", "source": "ABS-CBN", "link": ""},
                {"title": "Maharlika fund eyes energy sector investments", "source": "BusinessWorld", "link": ""},
            ],
            "source_count": 2,
            "sources": ["ABS-CBN", "BusinessWorld"],
        },
        {
            "cluster_title": "US and Iran in indirect talks to extend ceasefire - The Guardian",
            "published": "Wed, 15 Apr 2026 11:00:00 GMT",
            "link": "https://mock/cluster7",
            "section": "World",
            "sub_articles": [
                {"title": "US and Iran in indirect talks to extend two-week ceasefire", "source": "The Guardian", "link": ""},
                {"title": "Iran nuclear talks resume amid blockade tensions", "source": "Reuters", "link": ""},
                {"title": "Oil prices swing on Iran diplomacy signals", "source": "Bloomberg", "link": ""},
            ],
            "source_count": 3,
            "sources": ["The Guardian", "Reuters", "Bloomberg"],
        },
    ]
