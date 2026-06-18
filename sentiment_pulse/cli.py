import sys
import os
import io
import time
import signal

if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import click

from . import storage
from . import sources as source_module
from . import analyzer
from . import display
from .config import DEFAULT_SOURCES, DEFAULT_TIME_RANGES, WATCH_INTERVAL_MIN, WATCH_INTERVAL_DEFAULT


_watch_running = True


def _handle_signal(signum, frame):
    global _watch_running
    _watch_running = False
    click.echo()
    click.secho("⏹  正在停止观察模式，保存最后一轮后退出...", fg="yellow")


def _get_recent_scan_details(game, sources_list, time_range, limit=3):
    recent = storage.list_scans(game=game, sources=sources_list, time_range=time_range, limit=limit)
    details = []
    for s in recent:
        d = storage.get_scan_by_id(s["id"])
        if d:
            details.append(d)
    return details


def _do_single_scan(game, sources_list, time_range, per_source_limit, no_save,
                    watch_mode=False, round_idx=None):
    try:
        posts, statuses = source_module.fetch_all(game, sources_list, time_range,
                                                    per_source_limit=per_source_limit)
    except Exception as e:
        display.render_error(f"数据获取失败: {e}")
        return None, False

    if round_idx is None:
        recent_details = _get_recent_scan_details(game, sources_list, time_range, limit=3)
        health_warnings = display.detect_source_health(statuses, recent_details)
        display.render_source_statuses(statuses, health_warnings=health_warnings)

    ok_sources = [n for n, s in statuses.items() if s.get("ok") and s.get("count", 0) > 0]

    if not posts:
        if round_idx is not None:
            click.secho(f"  [#{round_idx:02d}] 窗口内无有效帖子", fg="yellow")
        else:
            display.render_error(
                f"指定时间窗口内没有帖子（窗口={time_range}）。"
                f"可尝试扩大窗口到 3d / 7d，或更换更热门的游戏关键词。"
            )
        return None, False

    previous = storage.get_previous_scan(game, sources_list, time_range)
    previous_freq = previous["keyword_freq"] if previous else {}
    previous_summary = {
        "total": previous["total_posts"],
        "negative": previous["negative_posts"],
    } if previous else None

    watchlist = storage.get_watchlist()
    synonym_groups = storage.get_synonym_groups()
    result = analyzer.analyze(posts, previous_freq=previous_freq,
                              watchlist=watchlist, synonym_groups=synonym_groups)

    scanned_at = int(time.time())
    if not no_save:
        storage.save_scan(
            game=game,
            sources=sources_list,
            time_range=time_range,
            keyword_freq=result["keyword_freq"],
            total_posts=result["sentiment"]["total"],
            negative_posts=result["sentiment"]["negative"],
            avg_sentiment=result["sentiment"]["avg_sentiment"],
            alerts=result["alerts"],
            top_keywords=result["top_keywords"],
            negative_snippets=result["negative_snippets"],
            top_links=result["top_links"],
            source_statuses=statuses,
            group_alerts=result["group_alerts"],
            watch_mode=watch_mode,
        )
        try:
            storage.save_cached_posts(game, posts)
        except Exception:
            pass

    result["_statuses"] = statuses
    result["_scanned_at"] = scanned_at
    result["_previous"] = previous
    return result, True


@click.group(help="🎮 SentimentPulse - 极简游戏社区舆情巡检工具")
def cli():
    storage.init_db()


@cli.command(help="执行一次舆情巡检（或开启观察模式定时轮询）")
@click.option("-g", "--game", required=True, help="游戏名称，如 '星露谷物语'")
@click.option("-s", "--source", "sources", multiple=True,
              type=click.Choice(DEFAULT_SOURCES),
              help=f"社区来源，可多选，默认全部。可选: {', '.join(DEFAULT_SOURCES)}")
@click.option("-t", "--time-range", "time_range", default="24h", show_default=True,
              type=click.Choice(DEFAULT_TIME_RANGES),
              help=f"巡检时间窗口，可选: {', '.join(DEFAULT_TIME_RANGES)}")
@click.option("--limit", default=150, show_default=True, type=int, help="每个来源最多抓取帖子数")
@click.option("--no-save", is_flag=True, help="不保存本次巡检记录到数据库")
@click.option("--watch", "watch_mode", is_flag=True,
              help="观察模式：持续定时轮询，Ctrl+C 停止")
@click.option("--interval", default=WATCH_INTERVAL_DEFAULT, show_default=True, type=int,
              help=f"观察模式下每次轮询间隔秒数，最少 {WATCH_INTERVAL_MIN} 秒")
def scan(game, sources, time_range, limit, no_save, watch_mode, interval):
    if not sources:
        sources = tuple(DEFAULT_SOURCES)
    sources_list = sorted(set(sources))

    if not watch_mode:
        display.render_info(f"正在扫描社区... 游戏=[bold yellow]{game}[/bold yellow]  "
                            f"来源=[bold cyan]{', '.join(sources_list)}[/bold cyan]  "
                            f"窗口=[bold]{time_range}[/bold]")

        result, ok = _do_single_scan(game, sources_list, time_range, limit, no_save)
        if not ok or result is None:
            sys.exit(0 if result is not None else 1)

        previous_summary = None
        if result.get("_previous"):
            p = result["_previous"]
            previous_summary = {"total": p["total_posts"], "negative": p["negative_posts"]}
        display.render_result(result, game, sources_list, time_range,
                              result["_scanned_at"], previous_summary)

        if result.get("_previous"):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(result["_previous"]["scanned_at"]))
            click.echo()
            click.secho(f"💡 上一次巡检: {ts} (基于该基线计算变化与告警)", dim=True)
        else:
            click.echo()
            click.secho(f"ℹ️  首次运行（无基线）。再次运行相同参数将显示变化对比与关注告警。", dim=True)
        return

    # ============ 观察模式 ============
    if interval < WATCH_INTERVAL_MIN:
        interval = WATCH_INTERVAL_MIN
        display.render_info(f"间隔过短，已自动调整为 {WATCH_INTERVAL_MIN} 秒，避免给社区API造成压力")

    global _watch_running
    _watch_running = True
    if os.name != "nt":
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    display.render_info(
        f"🚀 进入观察模式  |  游戏: [bold yellow]{game}[/bold yellow]  "
        f"来源: [bold cyan]{', '.join(sources_list)}[/bold cyan]  "
        f"窗口: [bold]{time_range}[/bold]\n"
        f"   每 [bold]{interval}[/bold] 秒扫描一轮  |  按 Ctrl+C 停止"
    )
    click.echo()

    round_idx = 0
    try:
        while _watch_running:
            round_idx += 1

            if round_idx == 1:
                display.render_info(f"🔄 第 {round_idx} 轮扫描 (完整输出)...")
                result, ok = _do_single_scan(
                    game, sources_list, time_range, limit, no_save,
                    watch_mode=True, round_idx=None
                )
                if ok and result is not None:
                    previous_summary = None
                    if result.get("_previous"):
                        p = result["_previous"]
                        previous_summary = {"total": p["total_posts"], "negative": p["negative_posts"]}
                    display.render_result(result, game, sources_list, time_range,
                                          result["_scanned_at"], previous_summary,
                                          round_idx=round_idx)
                    click.echo()
                    click.secho(f"   💡 下一轮: {time.strftime('%H:%M:%S', time.localtime(time.time() + interval))}",
                                dim=True)
            else:
                result, ok = _do_single_scan(
                    game, sources_list, time_range, limit, no_save,
                    watch_mode=True, round_idx=round_idx
                )
                if ok and result is not None:
                    display.render_watch_round_summary(
                        round_idx, result["_scanned_at"], result,
                        result.get("_previous")
                    )
                    click.secho(f"   下一轮: {time.strftime('%H:%M:%S', time.localtime(time.time() + interval))}",
                                dim=True)

            if not _watch_running:
                break
            for _ in range(interval):
                if not _watch_running:
                    break
                time.sleep(1)

            if not _watch_running:
                break

    except KeyboardInterrupt:
        pass

    click.echo()

    # 观察模式结束后显示趋势摘要
    if round_idx >= 2:
        recent_details = _get_recent_scan_details(game, sources_list, time_range, limit=round_idx)
        if len(recent_details) >= 2:
            display.render_trend_summary(reversed(recent_details))
            click.echo()

    display.render_success(
        f"✅ 观察模式结束  |  共运行 [bold]{round_idx}[/bold] 轮  |  "
        f"游戏: [bold yellow]{game}[/bold yellow]  |  窗口: [bold]{time_range}[/bold]\n"
        f"   使用 'history -g \"{game}\"' 查看所有历史记录\n"
        f"   使用 'history compare <id1> <id2>' 对比任意两次巡检"
    )


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


@cli.group(help="📝 同义词组管理 (将多个相似词合并统计)")
def synonyms():
    pass


@synonyms.command(name="list", help="列出所有同义词组")
def synonyms_list():
    groups = storage.get_synonym_groups(enabled_only=False)
    if not groups:
        display.render_info("同义词组为空，使用 'synonyms add' 添加")
        return
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    table.add_column("组名", style="bold magenta", min_width=14)
    table.add_column("状态", width=8, justify="center")
    table.add_column("包含词", style="dim")
    for g in groups:
        status = "启用" if g["enabled"] else "禁用"
        status_style = "bold green" if g["enabled"] else "dim"
        words_str = ", ".join(g["words"][:6])
        if len(g["words"]) > 6:
            words_str += f" 等 {len(g['words'])} 个"
        table.add_row(g["label"], f"[{status_style}]{status}[/{status_style}]", words_str)
    display.console.print(Panel(table, title="[bold]📝 同义词组[/bold]",
                                 border_style="magenta", box=box.ROUNDED))


@synonyms.command(name="add", help="添加同义词组（用逗号分隔多个词）")
@click.argument("label")
@click.argument("words")
@click.option("--enabled/--disabled", default=True, help="是否默认启用")
def synonyms_add(label, words, enabled):
    word_list = [w.strip() for w in words.split(",") if w.strip()]
    if not label.strip():
        display.render_error("组名不能为空")
        sys.exit(1)
    if len(word_list) < 2:
        display.render_error("至少需要 2 个同义词，用英文逗号分隔")
        sys.exit(1)
    ok = storage.add_synonym_group(label, word_list)
    if ok:
        display.render_success(f"已添加同义词组: '{label}' ({len(word_list)} 个词)")
    else:
        display.render_error("添加失败，可能组名已存在")


@synonyms.command(name="remove", help="删除同义词组")
@click.argument("label")
def synonyms_remove(label):
    ok = storage.remove_synonym_group(label)
    if ok:
        display.render_success(f"已删除同义词组: '{label}'")
    else:
        display.render_error(f"未找到同义词组: '{label}'")


@cli.group(help="📋 历史巡检记录（可筛选、对比、查看详情、导出Markdown）", invoke_without_command=True)
@click.option("-g", "--game", help="按游戏名过滤")
@click.option("-s", "--source", "sources", multiple=True,
              type=click.Choice(DEFAULT_SOURCES),
              help="按来源过滤（需完整匹配所选来源集合）")
@click.option("-t", "--time-range", "time_range",
              type=click.Choice(DEFAULT_TIME_RANGES),
              help="按时间窗口过滤")
@click.option("-n", "--limit", default=10, show_default=True, type=int, help="显示最近N条")
@click.pass_context
def history(ctx, game, sources, time_range, limit):
    if ctx.invoked_subcommand is not None:
        return
    sources_list = sorted(set(sources)) if sources else None
    scans = storage.list_scans(game=game, sources=sources_list, time_range=time_range, limit=limit)

    if not scans:
        display.render_info("暂无巡检历史记录，运行 'scan' 命令开始吧~")
        return

    from rich.table import Table
    from rich.panel import Panel
    from datetime import datetime

    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    table.add_column("ID", width=6, justify="center", style="dim")
    table.add_column("时间", width=16)
    table.add_column("游戏", style="bold yellow")
    table.add_column("来源")
    table.add_column("窗口", width=8)
    table.add_column("样本", justify="right")
    table.add_column("负面", justify="right", style="red")
    table.add_column("模式", width=8, justify="center")

    for s in scans:
        ts = datetime.fromtimestamp(s["scanned_at"]).strftime("%m-%d %H:%M")
        src = ", ".join(s["sources"])
        if len(src) > 20:
            src = src[:18] + "…"
        neg = s.get("negative_posts", 0)
        tot = s.get("total_posts", 1) or 1
        neg_pct = f"{neg} ({neg/tot*100:.0f}%)"
        mode = "👁 观察" if s.get("watch_mode") else "单次"
        table.add_row(str(s["id"]), ts, s["game"], src, s["time_range"],
                      str(tot), neg_pct, mode)

    filter_info = []
    if game:
        filter_info.append(f"游戏={game}")
    if sources_list:
        filter_info.append(f"来源={','.join(sources_list)}")
    if time_range:
        filter_info.append(f"窗口={time_range}")
    subtitle = f"[dim]过滤: {', '.join(filter_info)}[/dim]" if filter_info else ""

    panel_title = f"[bold]📋 巡检历史记录 ({len(scans)} 条)[/bold]"
    if subtitle:
        panel_title += f"\n{subtitle}"
    display.console.print(Panel(table, title=panel_title, border_style="cyan", box=box.ROUNDED))
    click.secho("💡 查看详情: pulse history show <id>   |   对比: pulse history compare <id1> <id2>   |   导出: pulse history export -o report.md",
                dim=True)


@history.command(name="show", help="展开显示某次巡检的完整详情")
@click.argument("scan_id", type=int)
def history_show(scan_id):
    scan = storage.get_scan_by_id(scan_id)
    if not scan:
        display.render_error(f"未找到 ID 为 {scan_id} 的巡检记录")
        sys.exit(1)
    display.render_scan_detail(scan)


@history.command(name="compare", help="对比两次巡检的差异（补丁前后看变化）")
@click.argument("scan_id_a", type=int)
@click.argument("scan_id_b", type=int)
def history_compare(scan_id_a, scan_id_b):
    scan_a = storage.get_scan_by_id(scan_id_a)
    scan_b = storage.get_scan_by_id(scan_id_b)
    if not scan_a:
        display.render_error(f"未找到 ID 为 {scan_id_a} 的巡检记录")
        sys.exit(1)
    if not scan_b:
        display.render_error(f"未找到 ID 为 {scan_id_b} 的巡检记录")
        sys.exit(1)

    if scan_a["scanned_at"] > scan_b["scanned_at"]:
        scan_a, scan_b = scan_b, scan_a

    display.render_compare(scan_a, scan_b)


@history.command(name="export", help="导出筛选后的历史记录为 Markdown 报告")
@click.option("-o", "--output", "output", default="pulse_report.md", show_default=True,
              help="输出文件路径")
@click.option("-g", "--game", help="按游戏名过滤")
@click.option("-s", "--source", "sources", multiple=True,
              type=click.Choice(DEFAULT_SOURCES),
              help="按来源过滤（需完整匹配所选来源集合）")
@click.option("-t", "--time-range", "time_range",
              type=click.Choice(DEFAULT_TIME_RANGES),
              help="按时间窗口过滤")
@click.option("-n", "--limit", default=10, show_default=True, type=int, help="包含最近N条")
@click.option("--title", default="舆情巡检报告", help="报告标题")
def history_export(output, game, sources, time_range, limit, title):
    sources_list = sorted(set(sources)) if sources else None
    scans = storage.list_scans(game=game, sources=sources_list, time_range=time_range, limit=limit)
    if not scans:
        display.render_error("没有符合条件的巡检记录可导出")
        sys.exit(1)

    full_scans = []
    for s in scans:
        detail = storage.get_scan_by_id(s["id"])
        if detail:
            full_scans.append(detail)

    if not full_scans:
        display.render_error("获取详细数据失败")
        sys.exit(1)

    md = display.export_report_markdown(full_scans, title=title)
    try:
        with open(output, "w", encoding="utf-8") as f:
            f.write(md)
        display.render_success(
            f"已导出 {len(full_scans)} 条记录到 [bold]{output}[/bold]\n"
            f"   总字数: {len(md)} 字"
        )
    except Exception as e:
        display.render_error(f"导出失败: {e}")
        sys.exit(1)


@cli.command(help="🔧 显示当前配置和数据库位置")
def info():
    from .config import HOME_DIR, DB_PATH, DEFAULT_WATCHLIST, ALERT_CHANGE_THRESHOLD, ALERT_MIN_COUNT
    from rich.table import Table
    from rich.panel import Panel

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
    table.add_row("默认观察间隔", f"{WATCH_INTERVAL_DEFAULT} 秒")

    wl = storage.get_watchlist()
    table.add_row("已启用关注词数", str(len(wl)))

    sg = storage.get_synonym_groups()
    table.add_row("已启用同义词组数", str(len(sg)))

    with storage.get_conn() as conn:
        cur = conn.execute("SELECT COUNT(*) as c FROM scans")
        table.add_row("历史巡检次数", str(cur.fetchone()["c"]))
        cur = conn.execute("SELECT COUNT(*) as c FROM scans WHERE watch_mode = 1")
        table.add_row("观察模式轮次", str(cur.fetchone()["c"]))
        cur = conn.execute("SELECT COUNT(*) as c FROM cached_posts")
        table.add_row("缓存帖子数", str(cur.fetchone()["c"]))

    display.console.print(Panel(table, title="[bold]🔧 配置 & 状态[/bold]",
                                border_style="cyan", box=box.ROUNDED))


def main():
    cli()


if __name__ == "__main__":
    main()
