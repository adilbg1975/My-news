"""robot.py - downloads news (with photos) and news videos, and saves them to news.json.
GitHub runs this automatically (see daily.yml). No extra packages needed.

If one news source is broken, it is skipped and the others still work."""

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

LANGS = ["en", "ar"]
TOPIC_ORDER = ["top", "india", "world", "war", "politics", "sports",
               "business", "tech", "science", "health", "entertain"]

MAX_PER_TOPIC = 30     # headlines kept for each topic
PER_FEED = 20          # most headlines taken from one publisher feed
PER_GOOGLE = 15        # most headlines taken from Google News (no photos)
MAX_VIDEOS = 12        # videos kept for each topic
MIN_VIDEOS = 6         # if a topic has fewer matching videos, fill up with latest ones
PAUSE = 0.4            # seconds to wait between downloads (be polite)

BBC = "https://feeds.bbci.co.uk/"
GUARDIAN = "https://www.theguardian.com/"


# ---------------------------------------------------------------------------
# 1. WHAT TO DOWNLOAD
# ---------------------------------------------------------------------------

# Google News search words (no photos, but wide coverage)
Q = {
    "top":       {"en": "", "ar": ""},
    "india":     {"en": "", "ar": "الهند OR هندي OR نيودلهي OR مودي"},
    "world":     {"en": "world news", "ar": "أخبار العالم"},
    "war":       {"en": "war OR conflict OR military", "ar": "حرب OR نزاع OR عسكري"},
    "politics":  {"en": "politics", "ar": "سياسة"},
    "sports":    {"en": "sports", "ar": "رياضة"},
    "business":  {"en": "business OR economy", "ar": "اقتصاد OR أعمال"},
    "tech":      {"en": "technology", "ar": "تقنية"},
    "science":   {"en": "science", "ar": "علوم"},
    "health":    {"en": "health", "ar": "صحة"},
    "entertain": {"en": "entertainment OR movies OR music", "ar": "ترفيه OR أفلام OR موسيقى"},
}


def F(name, url, filtered=False):
    """A feed. filtered=True means: keep only headlines that match the topic words."""
    return (name, url, filtered)


# English publisher feeds. These normally come WITH photos.
EN_FEEDS = {
    "top": [F("BBC", BBC + "news/rss.xml"),
            F("The Guardian", GUARDIAN + "international/rss")],
    "india": [F("BBC", BBC + "news/world/asia/india/rss.xml"),
              F("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
              F("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
              F("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"),
              F("The Indian Express", "https://indianexpress.com/section/india/feed/"),
              F("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories")],
    "world": [F("BBC", BBC + "news/world/rss.xml"),
              F("The Guardian", GUARDIAN + "world/rss")],
    "war": [F("BBC", BBC + "news/world/rss.xml", True),
            F("The Guardian", GUARDIAN + "world/rss", True)],
    "politics": [F("BBC", BBC + "news/politics/rss.xml"),
                 F("The Guardian", GUARDIAN + "politics/rss")],
    "sports": [F("BBC Sport", BBC + "sport/rss.xml"),
               F("The Guardian", GUARDIAN + "sport/rss")],
    "business": [F("BBC", BBC + "news/business/rss.xml"),
                 F("The Guardian", GUARDIAN + "business/rss")],
    "tech": [F("BBC", BBC + "news/technology/rss.xml"),
             F("The Guardian", GUARDIAN + "technology/rss")],
    "science": [F("BBC", BBC + "news/science_and_environment/rss.xml"),
                F("The Guardian", GUARDIAN + "science/rss")],
    "health": [F("BBC", BBC + "news/health/rss.xml"),
               F("The Guardian", GUARDIAN + "society/health/rss")],
    "entertain": [F("BBC", BBC + "news/entertainment_and_arts/rss.xml"),
                  F("The Guardian", GUARDIAN + "culture/rss")],
}

# Arabic publisher feeds. They are general, so for each topic we keep only
# the headlines that match the topic words (except Top Stories and World).
AR_FEEDS = [
    ("BBC عربي", BBC + "arabic/rss.xml"),
    ("الجزيرة", "https://www.aljazeera.net/aljazeerarss/a7c186be-1baa-4bd4-9d80-a84db769f779/73d0e1b4-532f-45ef-b135-bfdff8b8cab9"),
    ("سكاي نيوز عربية", "https://www.skynewsarabia.com/web/rss"),
    ("العربية", "https://www.alarabiya.net/feed/rss2/ar.xml"),
]

# Words used to pick headlines (and videos) that belong to a topic.
KW = {
    "india": {
        "en": ["india", "indian", "modi", "delhi", "mumbai", "kolkata", "bengal", "bollywood", "kashmir"],
        "ar": ["الهند", "هندي", "هندية", "نيودلهي", "مودي", "بومباي", "كشمير"]},
    "war": {
        "en": ["war", "attack", "strike", "military", "army", "troops", "missile", "drone", "conflict",
               "ceasefire", "bomb", "soldier", "gaza", "ukraine", "hamas", "israel", "iran", "russia"],
        "ar": ["حرب", "غارة", "غارات", "قصف", "عسكري", "عسكرية", "جيش", "هجوم", "صاروخ", "صواريخ",
               "مسيرة", "هدنة", "وقف إطلاق النار", "قتلى", "معارك", "اشتباكات", "غزة", "أوكرانيا"]},
    "politics": {
        "en": ["politic", "election", "president", "minister", "government", "parliament", "congress",
               "senate", "vote", "trump", "party", "prime minister", "summit"],
        "ar": ["سياسة", "سياسي", "رئيس", "وزير", "انتخابات", "حكومة", "برلمان", "الرئاسة", "قمة",
               "مفاوضات", "سفير", "الخارجية", "البيت الأبيض", "ترمب", "ترامب"]},
    "sports": {
        "en": ["sport", "match", "cup", "league", "football", "soccer", "cricket", "tennis", "goal",
               "champion", "olympic", "nba", "formula", "player", "coach", "world cup"],
        "ar": ["رياضة", "مباراة", "كأس", "دوري", "كرة", "لاعب", "منتخب", "هدف", "بطولة", "نادي",
               "مدرب", "أولمبي", "تنس", "فورمولا"]},
    "business": {
        "en": ["business", "economy", "economic", "market", "stock", "bank", "oil", "inflation", "trade",
               "tariff", "company", "price", "dollar", "gold", "invest"],
        "ar": ["اقتصاد", "اقتصادي", "أسعار", "سعر", "بنك", "بنوك", "نفط", "أسهم", "بورصة", "الأسواق",
               "استثمار", "تضخم", "دولار", "ذهب", "شركة", "أعمال"]},
    "tech": {
        "en": ["tech", "artificial intelligence", " ai ", "apple", "google", "microsoft", "iphone",
               "software", "robot", "cyber", "internet", "chip", "openai", "smartphone"],
        "ar": ["تقنية", "تكنولوجيا", "ذكاء اصطناعي", "هاتف", "تطبيق", "آبل", "جوجل", "غوغل",
               "مايكروسوفت", "إنترنت", "روبوت", "سيبراني", "رقمي", "أيفون"]},
    "science": {
        "en": ["science", "scientist", "study", "space", "nasa", "planet", "climate", "discovery",
               "research", "moon", "mars", "telescope"],
        "ar": ["علماء", "دراسة", "فضاء", "علوم", "اكتشاف", "ناسا", "كوكب", "مناخ", "بحث علمي",
               "فلك", "قمر", "مسبار"]},
    "health": {
        "en": ["health", "disease", "cancer", "vaccine", "drug", "hospital", "doctor", "virus",
               "medical", "patient", "covid", "mental"],
        "ar": ["صحة", "صحي", "مرض", "علاج", "لقاح", "دواء", "مستشفى", "طبيب", "وباء", "سرطان",
               "فيروس", "أطباء"]},
    "entertain": {
        "en": ["film", "movie", "series", "actor", "actress", "singer", "music", "festival", "cinema",
               "song", "celebrity", "netflix", "concert"],
        "ar": ["فيلم", "أفلام", "مسلسل", "فنان", "فنانة", "موسيقى", "مهرجان", "سينما", "أغنية",
               "ممثل", "ممثلة", "حفل", "نجم"]},
}

# YouTube news channels: (channel id, group, language)
# If an id is wrong or a channel is missing, it is just skipped.
YT_CHANNELS = [
    ("UCNye-wNBqNL5ZzHSJj3l8Bg", "general", "en"),   # Al Jazeera English
    ("UC16niRr50-MSBwiO3YDb3RA", "general", "en"),   # BBC News
    ("UCknLrEdhRCp1aegoMqRaCZg", "general", "en"),   # DW News
    ("UCoMdktPbSTixAyNGwb-UYkQ", "general", "en"),   # Sky News
    ("UCQfwfsi5VrQ8yKZ-UWmAEFg", "general", "en"),   # France 24 English
    ("UCZFMm1mMw0F81Z37aaEzTUA", "india", "en"),     # NDTV
    ("UCYPvAwZP8pZhSMW8qs7cVCw", "india", "en"),     # India Today
    ("UC_gUM8rL-Lrg6O3adPW9K1g", "india", "en"),     # WION
    ("UCiWLfSweyRNmLpgEHekhoAg", "sports", "en"),    # ESPN
    ("UCNAf1k0yIjyGu3k9BwAg3lg", "sports", "en"),    # Sky Sports Football
    ("UCfiwzLy-8yKzIbsmZTzxDgw", "general", "ar"),   # Al Jazeera Arabic
    ("UCahpxixMCwoANAftn6IxkTg", "general", "ar"),   # Al Arabiya
]


# ---------------------------------------------------------------------------
# 2. DOWNLOADING
# ---------------------------------------------------------------------------

def download(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return response.read()
        except Exception as error:
            last_error = error
            time.sleep(2)
    raise last_error


_cache = {}


def cached(url, parser):
    """Downloads and parses a feed once. A broken feed gives [] and is not retried."""
    if url in _cache:
        return _cache[url]
    try:
        time.sleep(PAUSE)
        items = parser(download(url))
        print("  ok   %3d items  %s" % (len(items), url[:80]))
    except Exception as error:
        items = []
        print("  FAIL %s  (%s)" % (url[:80], str(error)[:60]))
    _cache[url] = items
    return items


# ---------------------------------------------------------------------------
# 3. READING FEEDS
# ---------------------------------------------------------------------------

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def clean_text(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(text):
    if not text:
        return ""
    try:
        dt = parsedate_to_datetime(text.strip())
    except Exception:
        try:
            dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except Exception:
            return ""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def looks_like_image(url):
    return url.lower().split("?")[0].endswith(IMG_EXT)


def clean_image(url):
    url = html.unescape((url or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if not url.startswith("https://"):
        return ""
    # BBC gives tiny 240px pictures. The same picture exists in a bigger size.
    url = re.sub(r"(ichef\.bbci\.co\.uk/.*?)/240/", r"\g<1>/800/", url, count=1)
    return url


def find_image(item):
    """Looks for a photo inside one RSS <item>. Returns '' if there is none."""
    found = []  # (width, url)
    for el in item.iter():
        name = local(el.tag)
        url = ""
        if name == "thumbnail":
            url = el.get("url") or ""
        elif name == "content":
            u = el.get("url") or ""
            kind = ((el.get("medium") or "") + " " + (el.get("type") or "")).strip()
            if "image" in kind or (not kind and looks_like_image(u)):
                url = u
        elif name == "enclosure":
            u = el.get("url") or ""
            if (el.get("type") or "").startswith("image") or looks_like_image(u):
                url = u
        if url:
            try:
                width = int(el.get("width") or 0)
            except ValueError:
                width = 0
            if width != 1:  # width 1 = tracking pixel
                found.append((width, url))

    if not found:
        for el in item.iter():
            if local(el.tag) in ("description", "encoded", "summary"):
                match = re.search(r'<img[^>]+src=["\']([^"\']+)', el.text or "", re.I)
                if match:
                    found.append((0, match.group(1)))
                    break
    if not found:
        return ""

    sized = [f for f in found if 0 < f[0] <= 800]
    if sized:
        url = max(sized)[1]          # biggest picture that is not huge
    else:
        unknown = [f for f in found if f[0] == 0]
        url = (unknown or sorted(found))[0][1]
    return clean_image(url)


def parse_rss(xml_bytes, default_source="", google=False):
    """RSS text -> list of {t: title, l: link, s: source, d: date, i: photo}."""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        title = clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if not link:
            link = (item.findtext("guid") or "").strip()
        source = default_source

        if google:
            source_el = item.find("source")
            if source_el is not None and source_el.text:
                source = clean_text(source_el.text)
            # Google titles look like "Headline - Source"
            if source and title.endswith(" - " + source):
                title = title[: -len(" - " + source)]
            elif not source and " - " in title:
                title, _, source = title.rpartition(" - ")

        if not title or not link.startswith("http"):
            continue
        entry = {"t": title.strip(), "l": link, "s": source.strip(),
                 "d": parse_date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date"))}
        image = find_image(item)
        if image:
            entry["i"] = image
        items.append(entry)
    return items


NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def parse_youtube(xml_bytes):
    """YouTube channel feed -> list of {id, t, c: channel, d: date}."""
    root = ET.fromstring(xml_bytes)
    channel = clean_text(root.findtext("a:title", namespaces=NS))
    videos = []
    for entry in root.findall("a:entry", NS):
        video_id = (entry.findtext("yt:videoId", namespaces=NS) or "").strip()
        title = clean_text(entry.findtext("a:title", namespaces=NS))
        link_el = entry.find("a:link", NS)
        link = link_el.get("href") if link_el is not None else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or not title:
            continue
        if "/shorts/" in (link or ""):
            continue  # skip YouTube Shorts
        videos.append({"id": video_id, "t": title, "c": channel,
                       "d": parse_date(entry.findtext("a:published", namespaces=NS))})
    return videos


# ---------------------------------------------------------------------------
# 4. BUILDING THE TOPICS
# ---------------------------------------------------------------------------

def matches(title, words):
    low = " " + title.lower() + " "
    return any(w in low for w in words)


def norm(title):
    return re.sub(r"\W+", " ", title.lower()).strip()


def google_url(topic, lang):
    query = Q[topic][lang]
    if lang == "ar":
        region = "hl=ar&gl=SA&ceid=SA:ar"
    elif topic == "india":
        region = "hl=en-IN&gl=IN&ceid=IN:en"
    else:
        region = "hl=en-US&gl=US&ceid=US:en"
    if not query:
        return "https://news.google.com/rss?" + region
    return ("https://news.google.com/rss/search?q=" +
            urllib.parse.quote(query + " when:2d") + "&" + region)


def build_news(lang, topic):
    words = KW.get(topic, {}).get(lang, [])
    items = []

    # publisher feeds first (they have photos)
    if lang == "en":
        feeds = EN_FEEDS.get(topic, [])
    else:
        filtered = topic not in ("top", "world")
        feeds = [(name, url, filtered) for name, url in AR_FEEDS]

    for name, url, filtered in feeds:
        got = cached(url, lambda data, n=name: parse_rss(data, n))
        if filtered and words:
            got = [x for x in got if matches(x["t"], words)]
        items += got[:PER_FEED]

    # Google News (no photos) fills the gaps
    google = cached(google_url(topic, lang), lambda data: parse_rss(data, "", google=True))
    items += google[:PER_GOOGLE]

    # remove repeated headlines (the first one kept is the one with the photo)
    seen, unique = set(), []
    for it in items:
        key = norm(it["t"])
        if key and key not in seen:
            seen.add(key)
            unique.append(it)
    unique.sort(key=lambda x: x["d"], reverse=True)
    return unique[:MAX_PER_TOPIC]


def get_all_videos():
    videos = []
    for channel_id, group, lang in YT_CHANNELS:
        url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + channel_id
        for v in cached(url, parse_youtube):
            videos.append(dict(v, g=group, lang=lang))
    return videos


def pick_videos(lang, topic, videos):
    pool = sorted([v for v in videos if v["lang"] == lang], key=lambda v: v["d"], reverse=True)
    general = [v for v in pool if v["g"] == "general"]
    words = KW.get(topic, {}).get(lang, [])

    if topic in ("top", "world"):
        chosen = general
    elif topic == "india" and lang == "en":
        chosen = [v for v in pool if v["g"] == "india"]
    else:
        chosen = []
        if topic == "sports":
            chosen += [v for v in pool if v["g"] == "sports"]
        chosen += [v for v in general if matches(v["t"], words)]
        chosen.sort(key=lambda v: v["d"], reverse=True)
        if len(chosen) < MIN_VIDEOS and topic != "india":
            chosen += general          # fill up with the latest news videos

    seen, out = set(), []
    for v in chosen:
        if v["id"] not in seen:
            seen.add(v["id"])
            out.append({"id": v["id"], "t": v["t"], "c": v["c"], "d": v["d"]})
    return out[:MAX_VIDEOS]


# ---------------------------------------------------------------------------
# 5. MAIN
# ---------------------------------------------------------------------------

def main():
    result = {"updated": datetime.now(timezone.utc).isoformat(),
              "en": {}, "ar": {}, "videos": {"en": {}, "ar": {}}}
    total_news = total_photos = 0

    for lang in LANGS:
        for topic in TOPIC_ORDER:
            print("News:", lang, topic)
            items = build_news(lang, topic)
            result[lang][topic] = items
            total_news += len(items)
            total_photos += sum(1 for x in items if x.get("i"))

    print("Videos")
    videos = get_all_videos()
    total_videos = 0
    for lang in LANGS:
        for topic in TOPIC_ORDER:
            picked = pick_videos(lang, topic, videos)
            result["videos"][lang][topic] = picked
            total_videos += len(picked)

    print("Summary: %d headlines, %d with photos, %d videos" % (total_news, total_photos, total_videos))

    if total_news == 0:
        print("No news at all. Keeping the old news.json.")
        sys.exit(1)

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print("Saved news.json")


if __name__ == "__main__":
    main()
