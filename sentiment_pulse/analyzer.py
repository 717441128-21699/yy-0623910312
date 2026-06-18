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


def merge_synonym_freqs(
    keyword_freq: Dict[str, int],
    synonym_groups: List[Dict],
) -> Dict[str, Dict]:
    """
    按同义词组合并词频，返回 {group_label: {total, breakdown}}
    """
    merged: Dict[str, Dict] = {}
    k_lower_to_orig = {k.lower(): k for k in keyword_freq.keys()}
    for g in synonym_groups:
        label = g["label"]
        words = [w.lower() for w in g["words"]]
        total = 0
        breakdown = {}
        for w in words:
            if w in k_lower_to_orig:
                orig = k_lower_to_orig[w]
                cnt = keyword_freq[orig]
                total += cnt
                breakdown[orig] = cnt
        if total > 0:
            merged[label] = {
                "total": total,
                "breakdown": breakdown,
                "words": g["words"],
            }
    return merged


def compute_group_changes(
    current_groups: Dict[str, Dict],
    previous_groups: Dict[str, Dict],
) -> Dict[str, Dict]:
    """计算同义词组级别的变化"""
    changes = {}
    all_labels = set(current_groups.keys()) | set(previous_groups.keys())
    for label in all_labels:
        cur = current_groups.get(label, {}).get("total", 0)
        prev = previous_groups.get(label, {}).get("total", 0)
        if cur == 0 and prev == 0:
            continue
        if prev > 0:
            ratio = cur / prev
            delta = cur - prev
        else:
            ratio = float("inf") if cur > 0 else 1.0
            delta = cur
        changes[label] = {
            "label": label,
            "current": cur,
            "previous": prev,
            "delta": delta,
            "ratio": ratio,
            "is_new": prev == 0 and cur > 0,
            "breakdown": current_groups.get(label, {}).get("breakdown", {}),
            "prev_breakdown": previous_groups.get(label, {}).get("breakdown", {}),
        }
    return changes


def detect_group_alerts(
    group_changes: Dict[str, Dict],
    watchlist: List[Dict],
    synonym_groups: List[Dict],
    threshold: float = ALERT_CHANGE_THRESHOLD,
    min_count: int = ALERT_MIN_COUNT,
) -> List[Dict]:
    """检测同义词组级别的告警"""
    watch_kw_lower = {w["keyword"].lower(): w for w in watchlist}
    group_map = {g["label"]: g for g in synonym_groups}
    alerts = []
    for label, info in group_changes.items():
        g = group_map.get(label)
        if not g:
            continue
        watched = False
        t = threshold
        # 判断是否命中关注清单：组内任意词在关注清单即视为关注
        for w in g["words"]:
            wl = watch_kw_lower.get(w.lower())
            if wl:
                watched = True
                t = min(t, wl["threshold"])
                break
        cur = info["current"]
        if cur < min_count:
            continue
        ratio = info["ratio"]
        if info["is_new"] and cur >= min_count:
            alerts.append({
                "label": label,
                "type": "new",
                "current": cur,
                "previous": 0,
                "delta": cur,
                "ratio": "NEW",
                "watched": watched,
                "words": g["words"],
                "breakdown": info["breakdown"],
                "is_group": True,
            })
        elif ratio >= t:
            alerts.append({
                "label": label,
                "type": "spike",
                "current": cur,
                "previous": info["previous"],
                "delta": info["delta"],
                "ratio": round(ratio, 1),
                "watched": watched,
                "words": g["words"],
                "breakdown": info["breakdown"],
                "is_group": True,
            })
    alerts.sort(key=lambda a: (0 if a["watched"] else 1, -a["current"]))
    return alerts


def find_representative_posts(
    posts: List[Dict],
    words: List[str],
    max_n: int = 3,
) -> List[Dict]:
    """
    为一组同义词找到代表性帖子，找最具代表性（负面/最常出现的原句
    """
    matched = []
    words_lower = [w.lower() for w in words]
    for p in posts:
        content_lower = p.get("content", "").lower()
        hit = any(w in content_lower for w in words_lower)
        if hit:
            matched.append(p)
    # 按情感负面程度 + 匹配词数排序
    def _score(p):
        c = p.get("content", "").lower()
        hits = sum(1 for w in words_lower if w in c)
        return -p.get("sentiment", 0.5) - hits * 0.1
    matched.sort(key=_score)
    result = []
    seen = set()
    for p in matched:
        snippet = p.get("content", "")[:120]
        if snippet in seen:
            continue
        seen.add(snippet)
        result.append({
            "content": p.get("content", ""),
            "source": p.get("source", ""),
            "author": p.get("author", ""),
            "url": p.get("url", ""),
            "sentiment": p.get("sentiment", 0.5),
        })
        if len(result) >= max_n:
            break
    return result


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
    synonym_groups: List[Dict] = None,
) -> Dict:
    if previous_freq is None:
        previous_freq = {}
    if watchlist is None:
        watchlist = []
    if synonym_groups is None:
        synonym_groups = []

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

    # 同义词组分析
    group_alerts = []
    group_freq_current = {}
    group_freq_prev = {}
    if synonym_groups:
        group_freq_current = merge_synonym_freqs(keyword_freq, synonym_groups)
        group_freq_prev = merge_synonym_freqs(previous_freq, synonym_groups)
        group_changes = compute_group_changes(group_freq_current, group_freq_prev)
        group_alerts = detect_group_alerts(group_changes, watchlist, synonym_groups)
        # 为每个组告警附上代表原句
        for ga in group_alerts:
            reps = find_representative_posts(posts, ga.get("words", []), max_n=3)
            ga["representative_posts"] = reps

    return {
        "keyword_freq": keyword_freq,
        "changes": changes,
        "alerts": alerts,
        "group_alerts": group_alerts,
        "top_keywords": top_keywords,
        "negative_snippets": negative_snippets,
        "top_links": top_links,
        "sentiment": sentiment_summary,
        "synonym_groups_current": group_freq_current,
        "synonym_groups_prev": group_freq_prev,
    }
