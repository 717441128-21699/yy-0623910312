import random
import time
import hashlib
from typing import List, Dict
from abc import ABC, abstractmethod


class BaseSource(ABC):
    name = "base"

    @abstractmethod
    def fetch(self, game: str, time_range: str, limit: int = 200) -> List[Dict]:
        pass


_MOCK_STEAM_REVIEWS = [
    ("好评如潮，但更新后开始闪退了，每次进去不到5分钟就闪退到桌面，求修复！", 0.1),
    ("玩了200小时，昨天更新完频繁闪退，心态炸了。", 0.0),
    ("闪退+1，第三次了，存档还在就好，不然要退款了。", 0.05),
    ("游戏本身很棒，就是偶尔闪退，希望下次补丁解决。", 0.4),
    ("闪退闪退闪退！重要的事说三遍，根本没法玩。", 0.0),
    ("没有闪退，运行很稳定，帧数也足。", 0.9),
    ("存档消失了！我辛辛苦苦打了一周的进度没了，掉档了啊！", 0.0),
    ("昨晚突然掉档，重新进只剩新手教程，心态崩了。", 0.0),
    ("掉档警告，建议大家手动备份存档，自动保存有bug。", 0.1),
    ("还好我有备份，不然就真的掉档了，这个bug太致命。", 0.15),
    ("游戏剧情很好，就是优化有点差，偶尔卡顿。", 0.5),
    ("卡顿严重，战斗场景掉帧到20以下，根本没法打。", 0.1),
    ("不卡顿，全高画质60帧稳定，好评。", 0.95),
    ("服务器炸了，连不上，匹配半小时进不去。", 0.0),
    ("匹配机制有问题，新人被老玩家虐惨了。", 0.2),
    ("服务器维护了一下午，连个公告都没有，差评。", 0.0),
    ("退款了，实在玩不下去，与预期不符。", 0.0),
    ("已申请退款，不值这个价，内容太少。", 0.0),
    ("本来想退款，玩了几小时后发现还不错，留下了。", 0.7),
    ("bug太多，再这样我就要退款了。", 0.1),
    ("美术风格很喜欢，音乐也不错，沉浸感强。", 0.9),
    ("剧情反转太惊艳了，年度最佳独立游戏预定。", 1.0),
    ("操作手感有点怪，需要时间适应。", 0.6),
    ("新手教程做的很好，不用担心不会玩。", 0.85),
    ("建议加个中文语音，目前只有字幕。", 0.7),
    ("翻译质量很好，没有机翻痕迹。", 0.9),
    ("BOSS战设计很有创意，每一场都不一样。", 0.85),
    ("最后一关太难了，卡了3天，求削弱。", 0.4),
    ("难度适中，有挑战但不劝退，正好。", 0.8),
    ("外挂多的要死，PVP根本没法玩，全是锁头。", 0.0),
    ("举报了好几个外挂，都没处理，失望。", 0.05),
    ("反外挂系统形同虚设，建议学学隔壁。", 0.1),
    ("没遇到外挂，可能我段位低？", 0.7),
    ("封号了！我什么都没做啊，无辜躺枪。", 0.0),
    ("误封申诉三天没回复，客服死了？", 0.0),
    ("充值不到账，找客服也没人理，垃圾。", 0.0),
    ("内购太坑，不充钱根本玩不下去。", 0.1),
    ("付费DLC还不错，值这个价。", 0.75),
    ("黑屏！游戏启动后直接黑屏，有声音没画面。", 0.0),
    ("开局黑屏，切后台再回来就好了，玄学。", 0.3),
    ("报错弹窗，点确定就退出，玩不了。", 0.0),
    ("运行库装了N遍，还是报错启动失败。", 0.0),
    ("希望多出点mod，这个游戏很适合扩展。", 0.8),
    ("创意工坊的mod质量都很高，社区活跃。", 0.9),
    ("地图太小了，希望后续能更新更多内容。", 0.5),
    ("通关只用了10小时，流程太短，期待DLC。", 0.6),
    ("重复可玩性很高，每个职业体验都不一样。", 0.85),
    ("音效细节满分，戴上耳机体验拉满。", 0.95),
]

_MOCK_TAPTAP = [
    ("闪退严重，小米13Ultra一进就退，难受。", 0.0),
    ("游戏不错，就是发热有点严重，冬天可以当暖手宝。", 0.5),
    ("掉档了啊啊啊，我玩了三天的进度，TapTap云存档也没了？", 0.0),
    ("已退款，优化太差，骁龙8gen2都卡。", 0.0),
    ("手感比预期好，操作挺跟手的，好评。", 0.9),
    ("充值了648，钻石没到账，客服联系不上。", 0.0),
    ("匹配不到人，排位等了10分钟，人都麻了。", 0.1),
    ("服务器是不是在维护？一直显示网络错误。", 0.05),
    ("闪退问题终于修复了，更新后稳定了。", 0.85),
    ("bug反馈了一周没人理，官方装死？", 0.1),
    ("美术真的绝，每一张截图都是壁纸。", 1.0),
    ("剧情太感人了，结局直接泪目。", 0.9),
    ("卡顿，手机烫的可以煎鸡蛋，求优化。", 0.15),
    ("黑屏，卡在启动界面不动，重启也没用。", 0.0),
    ("游戏很好，但是广告太多了，到处都是弹窗。", 0.3),
    ("体力值系统太恶心了，不买体力根本玩不了几分钟。", 0.2),
    ("抽卡概率太坑，100抽保底才出，非酋哭了。", 0.25),
    ("首充福利还不错，新手引导做得很用心。", 0.7),
    ("外挂太多了，竞技场全是科技与狠活。", 0.05),
    ("官方能不能管管外挂？打PVP被虐惨了。", 0.1),
    ("存档没了！更新后自动清空了本地存档？", 0.0),
    ("报错代码502，什么意思，能玩吗？", 0.05),
    ("建议加个手柄支持，触屏操作太累。", 0.6),
    ("和朋友联机很顺畅，没有延迟，体验很好。", 0.9),
    ("角色平衡性太差，某几个角色太强了，其他没法玩。", 0.35),
]

_MOCK_BILIBILI = [
    ("新出的补丁又搞崩了？弹幕全在刷闪退。", 0.1),
    ("这个游戏剧情解说，第十五分钟高能预警！", 0.85),
    ("【攻略】教你如何避免掉档，亲测有效。", 0.9),
    ("直播录像：挑战无伤通关BOSS，结果闪退了（笑）", 0.5),
    ("退款吐槽：花了钱买罪受，这游戏也太坑了。", 0.0),
    ("独立游戏黑马！这个月最值得玩的新游。", 0.95),
    ("服务器崩了？直播间连不上游戏，观众都在笑。", 0.2),
    ("深度评测：为什么我说这款游戏值9分", 0.8),
    ("外挂实锤！这个UP主用外挂还敢发视频？", 0.05),
    ("全结局收集攻略，包含隐藏结局，附存档位置", 0.9),
    ("卡顿优化教程，几步设置让你的游戏丝滑流畅", 0.85),
    ("新手必看，避免前期踩坑的10个技巧", 0.8),
    ("吐槽一下匹配机制，我白银怎么排到王者了？", 0.3),
    ("这游戏也太难了吧，被虐到想退款了。", 0.4),
    ("【MOD推荐】这5个MOD让游戏体验提升100%", 0.9),
    ("付费DLC值不值得买？看完这个视频你就知道了", 0.7),
    ("主播开挂被封号，现场光速变脸", 0.15),
    ("黑屏问题解决方法，亲测有效", 0.8),
    ("报错解决方案汇总，常见问题都在这里", 0.75),
    ("掉档了，心态崩了，直播现场破防", 0.0),
]

_MOCK_TIEBA = [
    ("兄弟们，今天更新后闪退频率变高了，有人一样吗？", 0.15),
    ("楼主我找到闪退的临时解决办法了，把画质调低。", 0.5),
    ("求助！掉档了，有办法恢复吗？很急！", 0.05),
    ("有没有退款成功的？能不能教下怎么操作。", 0.1),
    ("这游戏优化是真的烂，我3080都卡顿。", 0.15),
    ("服务器崩了吧，吧里全是进不去的帖子。", 0.1),
    ("匹配机制能不能改改，把把都是猪队友。", 0.25),
    ("挂壁又出来了，这ID大家避雷一下。", 0.1),
    ("官方贴吧，BUG反馈专用楼，集中发在这里。", 0.6),
    ("求大佬分享个全收集存档，孩子打不过去了。", 0.5),
    ("黑屏+1，而且还关不掉，只能强杀进程。", 0.0),
    ("有没有遇到报错的，错误码E-1003是什么鬼？", 0.1),
    ("新DLC体验，这次的剧情是真的短。", 0.55),
    ("美术组是神吧，这场景设计的也太好看了。", 0.95),
    ("建议降低一下难度，手残党真的过不去啊。", 0.45),
    ("封号了，求助怎么解封，没开挂啊。", 0.0),
    ("兄弟们我找到了一个刷钱的BUG，不知道会不会封。", 0.3),
    ("这个游戏是不是要凉了？官方好久没发公告了。", 0.35),
    ("联机连不上，一直显示连接超时，有人遇到吗？", 0.15),
    ("存档在哪个文件夹？想备份一下防止掉档。", 0.4),
    ("充值了但是没到账，怎么办？吧友们支个招。", 0.0),
    ("抽卡概率统计，我用了200抽测试，结果惨不忍睹。", 0.2),
    ("闪退闪退闪退，第四次了，心态炸了。", 0.0),
    ("推荐一下类似的游戏，这个玩腻了。", 0.6),
    ("和朋友开黑真的快乐，游戏嘛，开心最重要。", 0.9),
]


class MockSource(BaseSource):
    def __init__(self, source_name: str, pool: List[tuple]):
        self._name = source_name
        self._pool = pool

    @property
    def name(self):
        return self._name

    def fetch(self, game: str, time_range: str, limit: int = 100) -> List[Dict]:
        posts = []
        pool = list(self._pool)
        random.shuffle(pool)

        hours = _parse_time_range(time_range)
        now = int(time.time())
        base_count = min(limit, max(10, int(hours * 1.5) + 10))

        for i in range(base_count):
            content, sentiment = random.choice(pool)
            created_at = now - random.randint(0, max(1, hours * 3600))
            post_id = hashlib.md5(f"{self._name}-{game}-{i}-{created_at}".encode()).hexdigest()[:12]
            author = _random_author()
            posts.append({
                "source": self._name,
                "post_id": post_id,
                "content": content,
                "author": author,
                "url": f"https://{self._name}.example.com/post/{post_id}",
                "sentiment": sentiment,
                "created_at": created_at,
                "priority": _calc_priority(content, sentiment),
            })

        posts.sort(key=lambda x: x["priority"], reverse=True)
        return posts


class SteamSource(MockSource):
    def __init__(self):
        super().__init__("steam", _MOCK_STEAM_REVIEWS)


class TapTapSource(MockSource):
    def __init__(self):
        super().__init__("taptap", _MOCK_TAPTAP)


class BilibiliSource(MockSource):
    def __init__(self):
        super().__init__("bilibili", _MOCK_BILIBILI)


class TiebaSource(MockSource):
    def __init__(self):
        super().__init__("tieba", _MOCK_TIEBA)


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


def fetch_all(game: str, sources: List[str], time_range: str, per_source_limit: int = 100) -> List[Dict]:
    all_posts = []
    for src_name in sources:
        try:
            src = get_source(src_name)
            posts = src.fetch(game, time_range, limit=per_source_limit)
            all_posts.extend(posts)
        except Exception as e:
            print(f"[warn] source {src_name} fetch failed: {e}")
    return all_posts


def _parse_time_range(tr: str) -> int:
    tr = tr.strip().lower()
    if tr.endswith("h"):
        return int(tr[:-1])
    elif tr.endswith("d"):
        return int(tr[:-1]) * 24
    else:
        try:
            return int(tr)
        except ValueError:
            return 24


def _random_author() -> str:
    prefixes = ["玩家", "路人", "老铁", "老", "小", "大"]
    names = ["小明", "阿强", "张三", "李四", "王五", "老六", "咸鱼", "柠檬", "橘子", "可乐",
             "雪碧", "咖啡", "奶茶", "布丁", "蛋糕", "饼干", "糖糖", "豆豆", "毛毛", "球球"]
    suffix = str(random.randint(100, 9999))
    return random.choice(prefixes) + random.choice(names) + suffix


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
