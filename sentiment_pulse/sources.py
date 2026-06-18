import re
import time
import random
from typing import List, Dict, Optional, Tuple
from abc import ABC, abstractmethod

import requests
from bs4 import BeautifulSoup


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = 12


class SourceUnavailableError(Exception):
    pass


class BaseSource(ABC):
    name = "base"

    @abstractmethod
    def fetch(self, game: str, time_range: str, limit: int = 200) -> List[Dict]:
        pass

    def _http_get(self, url: str, params: Dict = None, headers: Dict = None) -> Optional[dict]:
        h = {"User-Agent": _UA}
        if headers:
            h.update(headers)
        try:
            r = requests.get(url, params=params, headers=h, timeout=_TIMEOUT)
            if r.status_code != 200:
                raise SourceUnavailableError(f"HTTP {r.status_code}")
            ct = r.headers.get("Content-Type", "")
            if "application/json" in ct or ct == "":
                try:
                    return r.json()
                except Exception:
                    return {"_raw_html": r.text}
            return {"_raw_html": r.text}
        except requests.RequestException as e:
            raise SourceUnavailableError(f"网络错误: {e.__class__.__name__}")


def _parse_time_range(tr: str) -> int:
    tr = tr.strip().lower()
    if tr.endswith("h"):
        return int(tr[:-1])
    elif tr.endswith("d"):
        return int(tr[:-1]) * 24
    try:
        return int(tr)
    except ValueError:
        return 24


def _filter_by_time(posts: List[Dict], time_range: str) -> List[Dict]:
    hours = _parse_time_range(time_range)
    cutoff = int(time.time()) - hours * 3600
    return [p for p in posts if p.get("created_at", 0) >= cutoff]


def _estimate_sentiment(text: str) -> float:
    neg_kw = ["闪退", "掉档", "退款", "崩溃", "黑屏", "卡顿", "封号", "外挂", "报错", "炸了",
              "垃圾", "恶心", "差评", "玩不了", "连不上", "进不去", "坑", "差", "垃圾", "骗钱",
              "不到账", "维护", "卡", "崩", "破防", "虐", "难玩", "劝退", "严重"]
    pos_kw = ["好评", "喜欢", "不错", "推荐", "棒", "绝", "神作", "惊喜", "稳定", "丝滑",
              "沉浸", "用心", "细腻", "流畅", "值", "惊艳", "满意", "舒服", "快乐", "治愈"]
    s = 0.5
    for k in neg_kw:
        if k in text:
            s -= 0.12
    for k in pos_kw:
        if k in text:
            s += 0.12
    if "！" in text or "!" in text:
        s -= 0.03
    if "？" in text or "?" in text:
        s -= 0.02
    return max(0.0, min(1.0, s))


def _calc_priority(content: str, sentiment: float) -> float:
    score = 0.0
    if sentiment < 0.3:
        score += 5.0
    high_words = ["闪退", "掉档", "退款", "崩溃", "黑屏", "封号", "外挂", "服务器", "报错", "充值", "不到账"]
    for w in high_words:
        if w in content:
            score += 2.0
    if "!" in content or "！" in content:
        score += 0.5
    if content.count("？") + content.count("?") >= 2:
        score += 0.3
    return score + random.uniform(0, 0.5)


# =====================================================================
# Steam 源：使用 Store Search + Store Reviews 公开 JSON API
# =====================================================================
_STEAM_ALIAS = {
    "星露谷物语": "Stardew Valley",
    "星露谷": "Stardew Valley",
    "艾尔登法环": "Elden Ring",
    "老头环": "Elden Ring",
    "赛博朋克2077": "Cyberpunk 2077",
    "只狼": "Sekiro",
    "黑暗之魂": "Dark Souls",
    "黑魂": "Dark Souls",
    "荒野大镖客": "Red Dead Redemption",
    "原神": "Genshin Impact",
    "空洞骑士": "Hollow Knight",
    "泰拉瑞亚": "Terraria",
    "我的世界": "Minecraft",
    "传送门": "Portal",
    "巫师3": "The Witcher 3",
    "塞尔达传说": "The Legend of Zelda",
    "动物森友会": "Animal Crossing",
    "动物之森": "Animal Crossing",
    "怪物猎人": "Monster Hunter",
    "求生之路": "Left 4 Dead",
    "求生之路2": "Left 4 Dead 2",
    "csgo": "Counter-Strike",
    "反恐精英": "Counter-Strike",
    "dota2": "Dota 2",
    "刀塔2": "Dota 2",
    "绝地求生": "PUBG",
    "吃鸡": "PUBG",
    "among us": "Among Us",
    "我们之间": "Among Us",
    "双人成行": "It Takes Two",
    "战神": "God of War",
    "最后生还者": "The Last of Us",
    "美末": "The Last of Us",
    "底特律变人": "Detroit",
    "底特律": "Detroit",
    "瘟疫公司": "Plague Inc",
    "中国式家长": "Chinese Parents",
    "太吾绘卷": "The Scroll Of Taiwu",
    "鬼谷八荒": "Guigubahuang",
    "暖雪": "Warm Snow",
    "黑神话悟空": "Black Myth",
    "黑神话：悟空": "Black Myth",
    "失落城堡": "Lost Castle",
    "骑砍": "Mount & Blade",
    "骑马与砍杀": "Mount & Blade",
    "杀戮尖塔": "Slay the Spire",
    "文明6": "Sid Meier's Civilization VI",
    "文明": "Civilization",
    "无人深空": "No Man's Sky",
    "星空": "Starfield",
    "辐射4": "Fallout 4",
    "辐射": "Fallout",
    "上古卷轴5": "The Elder Scrolls V",
    "老滚5": "The Elder Scrolls",
    "博德之门3": "Baldur's Gate 3",
    "博德之门": "Baldur's Gate",
}

class SteamSource(BaseSource):
    name = "steam"

    def _search_appid(self, game: str) -> Optional[str]:
        candidates = [game]
        alias = _STEAM_ALIAS.get(game) or _STEAM_ALIAS.get(game.lower())
        if alias:
            candidates.insert(0, alias)
        candidates.append(game.lower())
        seen = set()
        search_terms = []
        for c in candidates:
            if c and c not in seen:
                search_terms.append(c)
                seen.add(c)

        search_cfgs = [
            {"l": "schinese", "cc": "cn"},
            {"cc": "cn"},
            {},
        ]

        for term in search_terms:
            for cfg in search_cfgs:
                params = {"term": term}
                params.update(cfg)
                try:
                    data = self._http_get(
                        "https://store.steampowered.com/api/storesearch/",
                        params=params,
                    )
                except SourceUnavailableError:
                    continue
                if not isinstance(data, dict):
                    continue
                items = data.get("items") or []
                if items:
                    app = items[0]
                    if app.get("type") in ("app", "bundle", None):
                        return str(app["id"])
        return None

    def fetch(self, game: str, time_range: str, limit: int = 100) -> List[Dict]:
        appid = self._search_appid(game)
        if not appid:
            raise SourceUnavailableError(f"未在Steam商店找到游戏: {game}")

        reviews = []
        cursor = "*"
        seen_ids = set()
        max_pages = 3
        for _ in range(max_pages):
            data = self._http_get(
                f"https://store.steampowered.com/appreviews/{appid}",
                params={
                    "json": "1",
                    "filter": "recent",
                    "language": "schinese",
                    "num_per_page": min(limit, 100),
                    "cursor": cursor,
                    "purchase_type": "all",
                },
            )
            if not isinstance(data, dict) or data.get("success") != 1:
                break
            for rev in data.get("reviews", []):
                rid = rev.get("recommendationid")
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                author = (rev.get("author") or {}).get("steamid", "steam_user")
                content = (rev.get("review") or "").strip()
                if not content:
                    continue
                voted_up = rev.get("voted_up", False)
                base_s = 0.8 if voted_up else 0.2
                sentiment = (base_s + _estimate_sentiment(content)) / 2
                url = f"https://steamcommunity.com/app/{appid}/recommended/{rid}/"
                reviews.append({
                    "source": "steam",
                    "post_id": f"steam_{rid}",
                    "content": content,
                    "author": f"steam_{author[:10]}",
                    "url": url,
                    "sentiment": sentiment,
                    "created_at": rev.get("timestamp_created", int(time.time())),
                    "priority": 0,
                })
            cursor = data.get("cursor")
            if not cursor or not data.get("reviews"):
                break

        if not reviews:
            raise SourceUnavailableError("Steam 评论为空或API限制访问")

        for r in reviews:
            r["priority"] = _calc_priority(r["content"], r["sentiment"])

        filtered = _filter_by_time(reviews, time_range)
        filtered.sort(key=lambda x: x["priority"], reverse=True)
        return filtered[:limit]


# =====================================================================
# TapTap 源：使用 webapiv2 搜索应用 + 评论接口
# =====================================================================
class TapTapSource(BaseSource):
    name = "taptap"

    def _search_app(self, game: str) -> Optional[Dict]:
        data = self._http_get(
            "https://www.taptap.cn/webapiv2/search-app",
            params={"query": game, "limit": "5"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        if not isinstance(data, dict):
            return None
        data = data.get("data") or data
        if isinstance(data, dict):
            items = (data.get("apps") or data.get("list") or [])
        else:
            items = []
        if not items:
            return None
        app = items[0]
        app_id = str(app.get("id") or app.get("app_id") or app.get("appid") or "")
        title = app.get("title") or app.get("name") or ""
        if not app_id:
            return None
        return {"id": app_id, "title": title}

    def fetch(self, game: str, time_range: str, limit: int = 100) -> List[Dict]:
        app = self._search_app(game)
        if not app:
            raise SourceUnavailableError(f"未在TapTap找到游戏: {game}")
        app_id = app["id"]

        posts: List[Dict] = []
        seen_ids = set()

        review_data = self._http_get(
            "https://www.taptap.cn/webapiv2/review",
            params={
                "app_id": app_id,
                "limit": str(min(limit, 50)),
                "sort": "new",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        if isinstance(review_data, dict):
            rdata = review_data.get("data") or review_data
            items = []
            if isinstance(rdata, dict):
                items = rdata.get("list") or rdata.get("reviews") or []
            elif isinstance(rdata, list):
                items = rdata
            for item in items:
                rid = str(item.get("id") or item.get("review_id") or "")
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                user = item.get("author") or item.get("user") or {}
                uname = user.get("name") or user.get("nickname") or f"taptap_{rid[:8]}"
                content = str(item.get("contents") or item.get("content") or item.get("text") or "").strip()
                if not content:
                    continue
                rating = item.get("star") or item.get("rating") or item.get("score") or 3
                base_s = ((float(rating) if isinstance(rating, (int, float)) else 3.0) - 1) / 4
                sentiment = (base_s + _estimate_sentiment(content)) / 2
                created_at = item.get("created_at") or item.get("create_time") or item.get("updated_at")
                if isinstance(created_at, (int, float)):
                    ts = int(created_at)
                elif isinstance(created_at, str):
                    try:
                        ts = int(time.mktime(time.strptime(created_at[:19], "%Y-%m-%d %H:%M:%S")))
                    except Exception:
                        ts = int(time.time())
                else:
                    ts = int(time.time())
                url = f"https://www.taptap.cn/app/{app_id}/review/{rid}"
                posts.append({
                    "source": "taptap",
                    "post_id": f"taptap_{rid}",
                    "content": content,
                    "author": str(uname),
                    "url": url,
                    "sentiment": sentiment,
                    "created_at": ts,
                    "priority": 0,
                })

        if not posts:
            fallback = self._fallback_search_taptap(game, limit)
            posts.extend(fallback)

        if not posts:
            raise SourceUnavailableError("TapTap接口未返回数据或地区限制")

        for r in posts:
            r["priority"] = _calc_priority(r["content"], r["sentiment"])

        filtered = _filter_by_time(posts, time_range)
        filtered.sort(key=lambda x: x["priority"], reverse=True)
        return filtered[:limit]

    def _fallback_search_taptap(self, game: str, limit: int) -> List[Dict]:
        data = self._http_get(
            "https://www.taptap.cn/webapiv2/search-topic",
            params={"query": game, "limit": str(limit)},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        if not isinstance(data, dict):
            return []
        rdata = data.get("data") or data
        items = []
        if isinstance(rdata, dict):
            items = rdata.get("list") or rdata.get("topics") or []
        elif isinstance(rdata, list):
            items = rdata
        out = []
        for it in items:
            tid = str(it.get("id") or it.get("topic_id") or "")
            if not tid:
                continue
            user = it.get("author") or {}
            uname = user.get("name") or f"taptap_user"
            content = str(it.get("contents") or it.get("summary") or it.get("title") or "").strip()
            if not content:
                continue
            ts = int(time.time()) - random.randint(0, 3 * 3600)
            out.append({
                "source": "taptap",
                "post_id": f"taptap_topic_{tid}",
                "content": content,
                "author": uname,
                "url": f"https://www.taptap.cn/topic/{tid}",
                "sentiment": _estimate_sentiment(content),
                "created_at": ts,
                "priority": 0,
            })
        return out


# =====================================================================
# B站 源：搜索视频接口，返回视频标题+简介内容
# =====================================================================
class BilibiliSource(BaseSource):
    name = "bilibili"

    def fetch(self, game: str, time_range: str, limit: int = 100) -> List[Dict]:
        keyword = f"{game} 反馈"
        data = self._http_get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={"search_type": "video", "keyword": keyword, "order": "pubdate", "page": "1"},
            headers={"Referer": "https://search.bilibili.com/"},
        )
        if not isinstance(data, dict) or data.get("code") != 0:
            raise SourceUnavailableError(f"B站搜索失败: {data.get('message') if isinstance(data, dict) else '格式异常'}")

        result = (data.get("data") or {}).get("result") or []
        if not result:
            raise SourceUnavailableError(f"B站未找到与 {game} 相关的视频")

        posts: List[Dict] = []
        for v in result:
            bvid = v.get("bvid") or v.get("id")
            aid = v.get("aid")
            if not bvid and not aid:
                continue
            title = re.sub(r"<[^>]+>", "", str(v.get("title") or ""))
            desc = str(v.get("description") or "").strip()
            content = (title + " | " + desc).strip(" |")
            if not content:
                continue
            author = str(v.get("author") or v.get("uname") or "b站用户")
            pub = v.get("pubdate") or v.get("senddate")
            if isinstance(pub, (int, float)):
                ts = int(pub)
            else:
                ts = int(time.time()) - random.randint(0, 24 * 3600)
            url = f"https://www.bilibili.com/video/{bvid}" if bvid else f"https://www.bilibili.com/video/av{aid}"
            sentiment = _estimate_sentiment(content)
            posts.append({
                "source": "bilibili",
                "post_id": f"bili_{bvid or aid}",
                "content": content,
                "author": author,
                "url": url,
                "sentiment": sentiment,
                "created_at": ts,
                "priority": 0,
            })

        if not posts:
            raise SourceUnavailableError("B站搜索结果为空")

        for r in posts:
            r["priority"] = _calc_priority(r["content"], r["sentiment"])

        filtered = _filter_by_time(posts, time_range)
        filtered.sort(key=lambda x: x["priority"], reverse=True)
        return filtered[:limit]


# =====================================================================
# 贴吧 源：搜索接口
# =====================================================================
class TiebaSource(BaseSource):
    name = "tieba"

    def fetch(self, game: str, time_range: str, limit: int = 100) -> List[Dict]:
        posts: List[Dict] = []

        kw = game.strip()
        data = self._http_get(
            "https://tieba.baidu.com/f/search/res",
            params={"ie": "utf-8", "qw": kw, "rn": str(min(limit, 50)), "un": "", "only_thread": "0"},
            headers={"Referer": "https://tieba.baidu.com/"},
        )
        html = ""
        if isinstance(data, dict) and "_raw_html" in data:
            html = data["_raw_html"]
        elif isinstance(data, str):
            html = data
        if not html:
            raise SourceUnavailableError("贴吧搜索无响应或反爬限制")

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".s_post") or soup.select(".p_content") or soup.find_all("div", class_=re.compile(r"s_post|post"))
        for idx, card in enumerate(cards[:limit]):
            title_a = card.find("a", class_="bluelink") or card.find("a", href=re.compile(r"/p/\d+"))
            content_node = card.find(class_="p_content") or card.find(class_="s_content") or card
            user_node = card.find(class_="s_user") or card.find("a", class_=re.compile(r"user"))
            time_node = card.find(class_="s-post-create-time") or card.find(class_="s_time") or card.find(class_="p_date")

            href = title_a["href"] if title_a and title_a.has_attr("href") else ""
            tid_match = re.search(r"/p/(\d+)", href) if href else None
            tid = tid_match.group(1) if tid_match else f"tieba_{idx}"
            title = (title_a.get_text(strip=True) if title_a else "")
            body = content_node.get_text(" ", strip=True) if content_node else ""
            content = f"{title} | {body}".strip(" |")
            if len(content) < 5:
                continue
            author = (user_node.get_text(strip=True) if user_node else f"吧友{idx+1}")
            if time_node:
                ttxt = time_node.get_text(strip=True)
                ts = self._parse_tieba_time(ttxt)
            else:
                ts = int(time.time()) - random.randint(0, 72 * 3600)
            url = f"https://tieba.baidu.com{href}" if href.startswith("/") else (href or f"https://tieba.baidu.com/f?kw={kw}")
            sentiment = _estimate_sentiment(content)
            posts.append({
                "source": "tieba",
                "post_id": f"tieba_{tid}",
                "content": content[:500],
                "author": author[:16],
                "url": url,
                "sentiment": sentiment,
                "created_at": ts,
                "priority": 0,
            })

        if not posts:
            raise SourceUnavailableError("贴吧未解析到帖子或关键词无匹配")

        for r in posts:
            r["priority"] = _calc_priority(r["content"], r["sentiment"])

        filtered = _filter_by_time(posts, time_range)
        filtered.sort(key=lambda x: x["priority"], reverse=True)
        return filtered[:limit]

    def _parse_tieba_time(self, txt: str) -> int:
        now = int(time.time())
        txt = txt.strip()
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", txt)
        if m:
            try:
                return int(time.mktime(time.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)} 12:00:00", "%Y-%m-%d %H:%M:%S")))
            except Exception:
                pass
        m = re.match(r"(\d{1,2})-(\d{1,2})", txt)
        if m:
            y = time.localtime().tm_year
            try:
                return int(time.mktime(time.strptime(f"{y}-{m.group(1)}-{m.group(2)} 12:00:00", "%Y-%m-%d %H:%M:%S")))
            except Exception:
                pass
        if "分钟前" in txt or "小时前" in txt:
            h = 1 if "分钟" in txt else 6
            return now - h * 3600
        if "昨天" in txt:
            return now - 24 * 3600
        if "前天" in txt:
            return now - 48 * 3600
        return now - random.randint(1, 72) * 3600


_SOURCE_MAP = {
    "steam": SteamSource,
    "taptap": TapTapSource,
    "bilibili": BilibiliSource,
    "tieba": TiebaSource,
}


def get_source(name: str) -> BaseSource:
    cls = _SOURCE_MAP.get(name.lower())
    if cls is None:
        raise ValueError(f"Unknown source: {name}, available: {list(_SOURCE_MAP.keys())}")
    return cls()


def fetch_all(
    game: str,
    sources: List[str],
    time_range: str,
    per_source_limit: int = 100,
) -> Tuple[List[Dict], Dict[str, Dict]]:
    """
    返回 (所有帖子, 每个来源的状态字典)
    状态格式: {source_name: {"ok": True, "count": N} | {"ok": False, "reason": str}}
    """
    all_posts: List[Dict] = []
    statuses: Dict[str, Dict] = {}
    for src_name in sources:
        try:
            src = get_source(src_name)
            posts = src.fetch(game, time_range, limit=per_source_limit)
            all_posts.extend(posts)
            statuses[src_name] = {"ok": True, "count": len(posts)}
        except SourceUnavailableError as e:
            statuses[src_name] = {"ok": False, "reason": str(e)}
        except Exception as e:
            statuses[src_name] = {"ok": False, "reason": f"{e.__class__.__name__}: {e}"}
    return all_posts, statuses
