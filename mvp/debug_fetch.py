"""诊断脚本：检查 Google News 和 Reddit RSS 实际返回了什么"""
import urllib.request
import urllib.parse
import feedparser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch_raw(url):
    """用 urllib 直接抓，绕开 feedparser 的 HTTP 层"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)

def test_gnews():
    print("=" * 60)
    print("TEST 1: Google News RSS")
    url = "https://news.google.com/rss/search?q=philippines+fuel+price&hl=en-PH&gl=PH&ceid=PH:en"
    print(f"URL: {url[:80]}...")
    status, body = fetch_raw(url)
    print(f"HTTP status: {status}")
    print(f"Body (first 500 chars): {body[:500]}")
    if status == 200:
        feed = feedparser.parse(body)
        print(f"feedparser entries: {len(feed.entries)}")
        if feed.entries:
            print(f"First title: {feed.entries[0].title}")
    print()

def test_reddit():
    print("=" * 60)
    print("TEST 2: Reddit RSS")
    url = "https://www.reddit.com/r/Philippines/search/.rss?q=fuel+price&restrict_sr=on&sort=new"
    print(f"URL: {url}")
    status, body = fetch_raw(url)
    print(f"HTTP status: {status}")
    print(f"Body (first 500 chars): {body[:500]}")
    if status == 200:
        feed = feedparser.parse(body)
        print(f"feedparser entries: {len(feed.entries)}")
    print()

def test_simple_gnews():
    print("=" * 60)
    print("TEST 3: Simple Google News (top PH headlines)")
    url = "https://news.google.com/rss?hl=en-PH&gl=PH&ceid=PH:en"
    status, body = fetch_raw(url)
    print(f"HTTP status: {status}")
    print(f"Body (first 500 chars): {body[:500]}")
    if status == 200:
        feed = feedparser.parse(body)
        print(f"feedparser entries: {len(feed.entries)}")
        for e in feed.entries[:3]:
            print(f"  - {e.title[:70]}")
    print()

if __name__ == "__main__":
    test_gnews()
    test_reddit()
    test_simple_gnews()
