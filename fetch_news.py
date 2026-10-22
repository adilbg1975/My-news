"""Downloads news and saves it to news.json.
GitHub runs this automatically (see daily.yml). No extra packages needed."""

import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# q = search words for each language, bbc = backup BBC feed
TOPICS = {
    "top":       {"q": {"en": "", "ar": ""}, "bbc": "news/rss.xml"},
    "world":     {"q": {"en": "world news", "ar": "أخبار العالم"}, "bbc": "news/world/rss.xml"},
    "war":       {"q": {"en": "war OR conflict OR military", "ar": "حرب OR نزاع OR عسكري"}, "bbc": "news/world/rss.xml"},
    "politics":  {"q": {"en": "politics", "ar": "سياسة"}, "bbc": "news/politics/rss.xml"},
    "sports":    {"q": {"en": "sports", "ar": "رياضة"}, "bbc": "sport/rss.xml"},
    "business":  {"q": {"en": "business OR economy", "ar": "اقتصاد OR أعمال"}, "bbc": "news/business/rss.xml"},
    "tech":      {"q": {"en": "technology", "ar": "تقنية"}, "bbc": "news/technology/rss.xml"},
    "science":   {"q": {"en": "science", "ar": "علوم"}, "bbc": "news/science_and_environment/rss.xml"},
    "health":    {"q": {"en": "health", "ar": "صحة"}, "bbc": "news/health/rss.xml"},
    "entertain": {"q": {"en": "entertainment OR movies OR music", "ar": "ترفيه OR أفلام OR موسيقى"}, "bbc": "news/entertainment_and_arts/rss.xml"},
}

LANGS = ["en", "ar"]
MAX_PER_TOPIC = 25


def google_url(query, lang):
    region = "hl=ar&gl=SA&ceid=SA:ar" if lang == "ar" else "hl=en-US&gl=US&ceid=US:en"
    if not query:
        return "https://news.google.com/rss?" + region
    q = urllib.parse.quote(query + " when:2d")
    return "https://news.google.com/rss/search?q=" + q + "&" + region


def bbc_url(topic, lang):
    if lang == "ar":
        return "https://feeds.bbci.co.uk/arabic/rss.xml"
    return "https://feeds.bbci.co.uk/" + TOPICS[topic]["bbc"]


def download(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; MyNewsApp/1.0)"}
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()


def parse_feed(xml_bytes, default_source=""):
    """Turns RSS text into a list of {t: title, l: link, s: source, d: date}."""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate") or ""

        source_el = item.find("source")
        if source_el is not None and source_el.text:
            source = source_el.text.strip()
        else:
            source = default_source

        # Google titles look like "Headline - Source": remove the source part
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        elif not source and " - " in title:
            title, _, source = title.rpartition(" - ")

        try:
            date = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
        except Exception:
            date = ""

        if title and link:
            items.append({"t": title.strip(), "l": link, "s": source.strip(), "d": date})

    # newest first, no duplicate headlines
    items.sort(key=lambda x: x["d"], reverse=True)
    seen, unique = set(), []
    for it in items:
        if it["t"] not in seen:
            seen.add(it["t"])
            unique.append(it)
    return unique[:MAX_PER_TOPIC]


def get_topic(topic, lang):
    query = TOPICS[topic]["q"][lang]
    try:
        items = parse_feed(download(google_url(query, lang)))
        if items:
            return items
        print("  Google gave nothing, trying BBC")
    except Exception as error:
        print("  Google failed (" + str(error) + "), trying BBC")
    try:
        return parse_feed(download(bbc_url(topic, lang)), "BBC")
    except Exception as error:
        print("  BBC failed (" + str(error) + ")")
        return []


def main():
    result = {"updated": datetime.now(timezone.utc).isoformat()}
    total = 0
    for lang in LANGS:
        result[lang] = {}
        for topic in TOPICS:
            print("Getting", lang, topic)
            items = get_topic(topic, lang)
            result[lang][topic] = items
            total += len(items)
            print("  ->", len(items), "items")

    if total == 0:
        print("No news at all. Keeping the old news.json.")
        sys.exit(1)

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print("Saved", total, "articles")


if __name__ == "__main__":
    main()
