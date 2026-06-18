import re
import jieba
from difflib import SequenceMatcher
from collections import Counter, defaultdict
from typing import List, Dict, Tuple, Set

from .config import STOPWORDS, TOP_KEYWORDS_COUNT, NEGATIVE_SNIPPETS_COUNT, TOP_LINKS_COUNT
from .config import ALERT_CHANGE_THRESHOLD, ALERT_MIN_COUNT

jieba.setLogLevel(60)

_EXTRA_DICT = [
    "闪退", "掉档", "退款", "崩溃", "黑屏", "卡顿", "封号", "外挂",
    "匹配", "服务器", "报错", "存档", "闪退", "掉帧", "抽卡",
    "DLC", "MOD", "Mod", "dlc", "mod", "氪金", "内购", "体力值",
    "剧情", "美术", "音效", "优化", "平衡性", "联机", "延迟",
    "更新", "补丁", "热更", "修复", "削弱", "加强",
    "BOSS", "boss", "Boss", "攻略", "通关", "结局",
    "反外挂", "创意工坊", "云存档", "本地存档",
    "新手引导", "首充", "保底", "概率", "误封",
    "剧情杀", "卡关", "破防", "高画质", "中画质", "低画质",
    "独立游戏", "EA", "抢先体验", "正式版",
]

for _w in _EXTRA_DICT:
    jieba.add_word(_w)

_DUP_THRESHOLD = 0.7


def tokenize(text: str, min_len: int = 2) -> List[str]:
    text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9+\-#]", " ", text)
    words = jieba.cut(text)
    result = []
    for w in words:
        w = w.strip()
        if len(w) < min_len:
            continue
        if w in STOPWORDS:
            continue
        if re.fullmatch(r"\d+", w):
            continue
        result.append(w)
    return result


def count_keywords(posts: List[Dict], top_n: int = TOP_KEYWORDS_COUNT) -> List[Tuple[str, int]]:
    counter: Counter = Counter()
    for p in posts:
        content = p.get("content", "")
        words = tokenize(content)
        counter.update(words)
    return counter.most_common(top_n)


def compute_keyword_changes(
    current: Dict[str, int],
    previous: Dict[str, int],
) -> Dict[str, Dict]:
    changes = {}
    all_keys = set(current.keys()) | set(previous.keys())
    for k in all_keys:
        cur = current.get(k, 0)
        prev = previous.get(k, 0)
        if cur == 0 and prev == 0:
            continue
        if prev > 0:
            ratio = cur / prev
            delta = cur - prev
        else:
            ratio = float("inf") if cur > 0 else 1.0
            delta = cur
        changes[k] = {
            "current": cur,
            "previous": prev,
            "delta": delta,
            "ratio": ratio,
            "is_new": prev == 0 and cur > 0,
        }
    return changes


def detect_alerts(
    changes: Dict[str, Dict],
    watchlist: List[Dict],
    threshold: float = ALERT_CHANGE_THRESHOLD,
    min_count: int = ALERT_MIN_COUNT,
) -> List[Dict]:
    alerts = []
    watch_keywords = {w["keyword"]: w for w in watchlist}
    for kw, info in changes.items():
        w = watch_keywords.get(kw)
        t = w["threshold"] if w else threshold
        cur = info["current"]
        if cur < min_count:
            continue
        ratio = info["ratio"]
        if info["is_new"] and cur >= min_count:
            alerts.append({
                "keyword": kw,
                "type": "new",
                "current": cur,
                "previous": 0,
                "delta": cur,
                "ratio": "NEW",
                "watched": w is not None,
            })
        elif ratio >= t:
            alerts.append({
                "keyword": kw,
                "type": "spike",
                "current": cur,
                "previous": info["previous"],
                "delta": info["delta"],
                "ratio": round(ratio, 1),
                "watched": w is not None,
            })
    alerts.sort(key=lambda a: (0 if a["watched"] else 1, -a["current"]))
    return alerts


_SPAM_PATTERNS = [
    r"^(.+?)\1{2,}$",
    r"^(.)\1{5,}$",
]


def is_spam(text: str) -> bool:
    t = text.strip()
    for pat in _SPAM_PATTERNS:
        if re.search(pat, t):
            return True
    return False


def _dedupe_similar(strings: List[str], threshold: float = _DUP_THRESHOLD) -> List[str]:
    kept: List[str] = []
    for s in strings:
        is_dup = False
        for k in kept:
            if SequenceMatcher(None, s, k).ratio() >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(s)
    return kept


def extract_negative_snippets(
    posts: List[Dict],
    max_n: int = NEGATIVE_SNIPPETS_COUNT,
    sentiment_cutoff: float = 0.35,
) -> List[Dict]:
    negatives = [p for p in posts if p.get("sentiment", 0.5) < sentiment_cutoff]
    negatives.sort(key=lambda p: (p.get("sentiment", 0.5), -p.get("priority", 0)))
    cleaned = []
    seen_contents: List[str] = []
    for p in negatives:
        c = p.get("content", "").strip()
        if not c or is_spam(c):
            continue
        dup = False
        for s in seen_contents:
            if SequenceMatcher(None, c, s).ratio() >= _DUP_THRESHOLD:
                dup = True
                break
        if dup:
            continue
        seen_contents.append(c)
        cleaned.append({
            "content": c,
            "source": p.get("source", ""),
            "author": p.get("author", ""),
            "url": p.get("url", ""),
            "sentiment": p.get("sentiment", 0.0),
        })
        if len(cleaned) >= max_n:
            break
    return cleaned


def extract_top_links(
    posts: List[Dict],
    max_n: int = TOP_LINKS_COUNT,
) -> List[Dict]:
    ranked = sorted(posts, key=lambda p: (
        0 if p.get("sentiment", 0.5) < 0.35 else 1,
        -p.get("priority", 0),
    ))
    seen_urls: Set[str] = set()
    result = []
    for p in ranked:
        url = p.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        c = p.get("content", "").strip()
        if len(c) > 50:
            c = c[:48] + "…"
        result.append({
            "url": url,
            "source": p.get("source", ""),
            "snippet": c,
            "sentiment": p.get("sentiment", 0.5),
            "author": p.get("author", ""),
        })
        if len(result) >= max_n:
            break
    return result


def summarize_sentiment(posts: List[Dict]) -> Dict:
    if not posts:
        return {"total": 0, "negative": 0, "neutral": 0, "positive": 0, "avg_sentiment": 0.5}
    total = len(posts)
    neg = sum(1 for p in posts if p.get("sentiment", 0.5) < 0.35)
    pos = sum(1 for p in posts if p.get("sentiment", 0.5) >= 0.65)
    neu = total - neg - pos
    avg = sum(p.get("sentiment", 0.5) for p in posts) / total
    return {
        "total": total,
        "negative": neg,
        "neutral": neu,
        "positive": pos,
        "avg_sentiment": round(avg, 3),
        "neg_ratio": round(neg / total, 3) if total else 0,
    }


def analyze(
    posts: List[Dict],
    previous_freq: Dict[str, int] = None,
    watchlist: List[Dict] = None,
) -> Dict:
    if previous_freq is None:
        previous_freq = {}
    if watchlist is None:
        watchlist = []

    keyword_freq = dict(count_keywords(posts, top_n=50))
    changes = compute_keyword_changes(keyword_freq, previous_freq)
    alerts = detect_alerts(changes, watchlist)
    top_keywords = []
    for kw, cnt in sorted(keyword_freq.items(), key=lambda x: -x[1])[:TOP_KEYWORDS_COUNT]:
        ch = changes.get(kw, {"current": cnt, "previous": 0, "delta": cnt, "ratio": 1.0, "is_new": True})
        top_keywords.append({
            "keyword": kw,
            "count": cnt,
            "previous": ch["previous"],
            "delta": ch["delta"],
            "ratio": ch["ratio"] if ch["ratio"] != float("inf") else "NEW",
            "is_new": ch.get("is_new", False),
            "watched": any(w["keyword"] == kw for w in watchlist),
        })
    negative_snippets = extract_negative_snippets(posts)
    top_links = extract_top_links(posts)
    sentiment_summary = summarize_sentiment(posts)

    return {
        "keyword_freq": keyword_freq,
        "changes": changes,
        "alerts": alerts,
        "top_keywords": top_keywords,
        "negative_snippets": negative_snippets,
        "top_links": top_links,
        "sentiment": sentiment_summary,
    }
