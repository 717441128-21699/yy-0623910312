import sys
import os
import io
import time

if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import click

from . import storage
from . import sources as source_module
from . import analyzer
from . import display
from .config import DEFAULT_SOURCES, DEFAULT_TIME_RANGES


@click.group(help="🎮 SentimentPulse - 极简游戏社区舆情巡检工具")
def cli():
    storage.init_db()


@cli.command(help="执行一次舆情巡检")
@click.option("-g", "--game", required=True, help="游戏名称，如 '星露谷物语'")
@click.option("-s", "--source", "sources", multiple=True,
              type=click.Choice(DEFAULT_SOURCES),
              help=f"社区来源，可多选，默认全部。可选: {', '.join(DEFAULT_SOURCES)}")
@click.option("-t", "--time-range", "time_range", default="24h", show_default=True,
              type=click.Choice(DEFAULT_TIME_RANGES),
              help=f"巡检时间窗口，可选: {', '.join(DEFAULT_TIME_RANGES)}")
@click.option("--limit", default=150, show_default=True, type=int, help="每个来源最多抓取帖子数")
@click.option("--no-save", is_flag=True, help="不保存本次巡检记录到数据库")
def scan(game, sources, time_range, limit, no_save):
    """执行舆情巡检"""
    if not sources:
        sources = tuple(DEFAULT_SOURCES)
    sources_list = sorted(set(sources))

    display.render_info(f"正在扫描社区... 游戏=[bold yellow]{game}[/bold yellow]  "
                        f"来源=[bold cyan]{', '.join(sources_list)}[/bold cyan]  "
                        f"窗口=[bold]{time_range}[/bold]")

    try:
        posts, statuses = source_module.fetch_all(game, sources_list, time_range, per_source_limit=limit)
    except Exception as e:
        display.render_error(f"数据获取失败: {e}")
        sys.exit(1)

    display.render_source_statuses(statuses)

    ok_sources = [n for n, s in statuses.items() if s.get("ok") and s.get("count", 0) > 0]
    bad_sources = [n for n, s in statuses.items() if not s.get("ok")]

    if bad_sources and not ok_sources:
        display.render_error("所有来源均不可用，未获取到任何有效帖子。请稍后重试或更换关键词/来源。")
        sys.exit(1)

    if not posts:
        display.render_error(
            f"指定时间窗口内没有帖子（窗口={time_range}）。"
            f"可尝试扩大窗口到 3d / 7d，或更换更热门的游戏关键词。"
        )
        sys.exit(1)

    previous = storage.get_previous_scan(game, sources_list, time_range)
    previous_freq = previous["keyword_freq"] if previous else {}
    previous_summary = {
        "total": previous["total_posts"],
        "negative": previous["negative_posts"],
    } if previous else None

    watchlist = storage.get_watchlist()
    result = analyzer.analyze(posts, previous_freq=previous_freq, watchlist=watchlist)

    scanned_at = int(time.time())
    if not no_save:
        storage.save_scan(
            game=game,
            sources=sources_list,
            time_range=time_range,
            keyword_freq=result["keyword_freq"],
            total_posts=result["sentiment"]["total"],
            negative_posts=result["sentiment"]["negative"],
        )
        try:
            storage.save_cached_posts(game, posts)
        except Exception:
            pass

    display.render_result(result, game, sources_list, time_range, scanned_at, previous_summary)

    if previous:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(previous["scanned_at"]))
        click.echo()
        click.secho(f"💡 上一次巡检: {ts} (基于该基线计算变化与告警)", dim=True)
    else:
        click.echo()
        click.secho(f"ℹ️  首次运行（无基线）。再次运行相同参数将显示变化对比与关注告警。", dim=True)


@cli.group(help="⭐ 关注清单管理 (关键词异常波动时醒目提示)")
def watch():
    pass


@watch.command(name="list", help="列出所有关注关键词")
def watch_list():
    wl = storage.get_watchlist(enabled_only=False)
    display.render_watchlist(wl)


@watch.command(name="add", help="添加关键词到关注清单")
@click.argument("keyword")
@click.option("--threshold", default=1.5, show_default=True, type=float,
              help="触发告警的涨幅倍数阈值，如 1.5 表示上涨50%以上告警")
def watch_add(keyword, threshold):
    if not keyword.strip():
        display.render_error("关键词不能为空")
        sys.exit(1)
    ok = storage.add_watch_keyword(keyword, threshold)
    if ok:
        display.render_success(f"已添加关注: '{keyword}' (阈值 x{threshold})")
    else:
        display.render_error("添加失败，可能已存在")


@watch.command(name="remove", help="从关注清单移除关键词")
@click.argument("keyword")
def watch_remove(keyword):
    ok = storage.remove_watch_keyword(keyword)
    if ok:
        display.render_success(f"已移除关注: '{keyword}'")
    else:
        display.render_error(f"未找到关键词: '{keyword}'")


@watch.command(name="enable", help="启用某个关注关键词")
@click.argument("keyword")
def watch_enable(keyword):
    ok = storage.toggle_watch_keyword(keyword, True)
    if ok:
        display.render_success(f"已启用: '{keyword}'")
    else:
        display.render_error(f"未找到关键词: '{keyword}'")


@watch.command(name="disable", help="停用某个关注关键词 (不移除)")
@click.argument("keyword")
def watch_disable(keyword):
    ok = storage.toggle_watch_keyword(keyword, False)
    if ok:
        display.render_success(f"已停用: '{keyword}'")
    else:
        display.render_error(f"未找到关键词: '{keyword}'")


@cli.command(help="📋 显示历史巡检记录")
@click.option("-g", "--game", help="按游戏名过滤")
@click.option("-n", "--limit", default=10, show_default=True, type=int, help="显示最近N条")
def history(game, limit):
    import json as _json
    from datetime import datetime
    from rich.table import Table
    from rich.panel import Panel
    from rich import box

    with storage.get_conn() as conn:
        if game:
            cur = conn.execute(
                "SELECT * FROM scans WHERE game = ? ORDER BY scanned_at DESC LIMIT ?",
                (game, limit)
            )
        else:
            cur = conn.execute(
                "SELECT * FROM scans ORDER BY scanned_at DESC LIMIT ?",
                (limit,)
            )
        rows = cur.fetchall()

    if not rows:
        display.render_info("暂无巡检历史记录，运行 'scan' 命令开始吧~")
        return

    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    table.add_column("#", width=4, justify="center", style="dim")
    table.add_column("时间", width=16)
    table.add_column("游戏", style="bold yellow")
    table.add_column("来源")
    table.add_column("窗口", width=8)
    table.add_column("样本", justify="right")
    table.add_column("负面", justify="right", style="red")

    for i, r in enumerate(rows, 1):
        ts = datetime.fromtimestamp(r["scanned_at"]).strftime("%m-%d %H:%M")
        src = ", ".join(_json.loads(r["sources"]))
        neg = r["negative_posts"] or 0
        tot = r["total_posts"] or 1
        neg_pct = f"{neg} ({neg/tot*100:.0f}%)" if tot else str(neg)
        table.add_row(str(i), ts, r["game"], src, r["time_range"], str(tot), neg_pct)

    display.console.print(Panel(table, title="[bold]📋 巡检历史记录[/bold]",
                                border_style="cyan", box=box.ROUNDED))


@cli.command(help="🔧 显示当前配置和数据库位置")
def info():
    from .config import HOME_DIR, DB_PATH, DEFAULT_WATCHLIST, ALERT_CHANGE_THRESHOLD, ALERT_MIN_COUNT
    from rich.table import Table
    from rich.panel import Panel
    from rich import box

    table = Table(show_header=False, box=box.ROUNDED, expand=True)
    table.add_column("配置项", style="bold cyan")
    table.add_column("值")
    table.add_row("数据目录", str(HOME_DIR))
    table.add_row("数据库文件", str(DB_PATH))
    table.add_row("默认社区源", ", ".join(DEFAULT_SOURCES))
    table.add_row("默认时间窗口", ", ".join(DEFAULT_TIME_RANGES))
    table.add_row("告警涨幅阈值", f"x{ALERT_CHANGE_THRESHOLD}")
    table.add_row("告警最小次数", str(ALERT_MIN_COUNT))
    table.add_row("默认关注词", ", ".join(DEFAULT_WATCHLIST[:8]) + " ...")

    wl = storage.get_watchlist()
    table.add_row("已启用关注词数", str(len(wl)))

    with storage.get_conn() as conn:
        cur = conn.execute("SELECT COUNT(*) as c FROM scans")
        table.add_row("历史巡检次数", str(cur.fetchone()["c"]))
        cur = conn.execute("SELECT COUNT(*) as c FROM cached_posts")
        table.add_row("缓存帖子数", str(cur.fetchone()["c"]))

    display.console.print(Panel(table, title="[bold]🔧 配置 & 状态[/bold]",
                                border_style="cyan", box=box.ROUNDED))


def main():
    cli()


if __name__ == "__main__":
    main()
