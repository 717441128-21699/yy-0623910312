from datetime import datetime
from typing import Dict, List, Optional

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .config import DEFAULT_SOURCES


console = Console()


def _fmt_delta(delta: int) -> Text:
    if delta > 0:
        return Text(f"+{delta}", style="bold green")
    elif delta < 0:
        return Text(str(delta), style="bold red")
    return Text("~", style="dim")


def _fmt_ratio(ratio) -> Text:
    if isinstance(ratio, str):
        return Text(ratio, style="bold magenta")
    if ratio >= 3:
        return Text(f"x{ratio}", style="bold magenta")
    elif ratio >= 1.5:
        return Text(f"x{ratio}", style="bold yellow")
    elif ratio >= 1.0:
        return Text(f"x{ratio}", style="dim")
    else:
        return Text(f"x{ratio}", style="bold cyan")


def _sentiment_bar(avg: float, width: int = 20) -> Text:
    filled = max(0, min(width, int(avg * width)))
    bar = "█" * filled + "░" * (width - filled)
    if avg < 0.35:
        style = "red"
    elif avg < 0.65:
        style = "yellow"
    else:
        style = "green"
    return Text(f"[{bar}] {avg:.0%}", style=style)


def _delta_str(d: int) -> str:
    if d > 0:
        return f"+{d}"
    elif d < 0:
        return str(d)
    return "~"


def _ratio_str(r) -> str:
    if isinstance(r, str):
        return r
    if isinstance(r, (int, float)):
        if r == float("inf"):
            return "NEW"
        return f"x{round(r, 1)}"
    return str(r)


def render_header(game: str, sources: List[str], time_range: str, scanned_at: int, round_idx: int = None):
    ts = datetime.fromtimestamp(scanned_at).strftime("%Y-%m-%d %H:%M")
    src = ", ".join(sources) if sources else "ALL"
    header = Table.grid(expand=True)
    header.add_column(style="bold cyan")
    header.add_column(justify="right", style="dim")
    title_prefix = f"[round {round_idx}] " if round_idx is not None else ""
    header.add_row(
        f"🎮 {title_prefix}舆情巡检  |  游戏: [bold yellow]{game}[/bold yellow]",
        f"扫描时间 {ts}",
    )
    header.add_row(
        f"来源: {src}  |  窗口: {time_range}",
        "",
    )
    console.print(Panel(header, border_style="cyan", box=box.ROUNDED))


def render_sentiment(summary: Dict, previous_summary: Dict = None):
    t = summary["total"]
    neg = summary["negative"]
    neu = summary["neutral"]
    pos = summary["positive"]
    avg = summary["avg_sentiment"]

    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column()
    grid.add_column(justify="right")
    grid.add_row("📊 样本量", f"[bold]{t}[/bold] 条")
    neg_pct = (neg / t * 100) if t else 0
    pos_pct = (pos / t * 100) if t else 0
    neu_pct = (neu / t * 100) if t else 0
    grid.add_row(
        "😡 负面 / 😐 中性 / 😊 正面",
        f"[red]{neg}({neg_pct:.0f}%)[/red] / [yellow]{neu}({neu_pct:.0f}%)[/yellow] / [green]{pos}({pos_pct:.0f}%)[/green]",
    )
    grid.add_row("📈 平均情绪分", _sentiment_bar(avg))

    if previous_summary:
        prev_neg = previous_summary.get("negative", 0)
        prev_t = previous_summary.get("total", 0) or 1
        prev_neg_pct = prev_neg / prev_t * 100
        delta_pct = neg_pct - prev_neg_pct
        sign = "+" if delta_pct >= 0 else ""
        grid.add_row(
            "⚠️ 负面率 vs 上次",
            f"{neg_pct:.1f}% [dim](上次 {prev_neg_pct:.1f}%)[/dim]  {sign}{delta_pct:.1f}%",
        )

    console.print(Panel(grid, title="[bold]情绪概览[/bold]", border_style="blue", box=box.ROUNDED))


def render_group_alerts(group_alerts: List[Dict]):
    if not group_alerts:
        return
    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    table.add_column("问题组 ★", style="bold red", min_width=14)
    table.add_column("类型", width=8, justify="center")
    table.add_column("当前", justify="right")
    table.add_column("上次", justify="right")
    table.add_column("变化", justify="right")
    table.add_column("涨幅", justify="right")
    table.add_column("构成", style="dim")

    for a in group_alerts:
        kw_style = "bold red" if a.get("watched") else "bold"
        kw = Text(a.get("label", a.get("keyword", "")), style=kw_style)
        if a.get("watched"):
            kw.append(" ★", style="yellow")
        type_style = "bold red" if a["type"] == "spike" else "bold magenta"
        type_txt = Text("突增" if a["type"] == "spike" else "新现", style=type_style)
        breakdown_parts = []
        for w, c in sorted(a.get("breakdown", {}).items(), key=lambda x: -x[1]):
            breakdown_parts.append(f"{w}×{c}")
        breakdown_txt = " + ".join(breakdown_parts[:4])
        table.add_row(
            kw, type_txt,
            str(a["current"]),
            str(a["previous"]),
            _fmt_delta(a["delta"]),
            _fmt_ratio(a["ratio"]),
            breakdown_txt,
        )
        reps = a.get("representative_posts", [])
        if reps:
            rep = reps[0]
            snippet = rep.get("content", "")[:80]
            if len(rep.get("content", "")) > 80:
                snippet += "…"
            src = rep.get("source", "")
            table.add_row(
                Text("  💬 代表原句", style="dim"),
                Text("", style="dim"), Text("", style="dim"),
                Text("", style="dim"), Text("", style="dim"),
                Text("", style="dim"),
                Text(f"[{src}] {snippet}", style="dim italic"),
            )
    console.print(Panel(table, title="[bold red]🚨 同义词组告警（合并统计）[/bold red]",
                        border_style="red", box=box.ROUNDED))


def render_alerts(alerts: List[Dict]):
    if not alerts:
        t = Text("✅ 暂无需要特别关注的异常波动", style="green")
        console.print(Panel(t, title="[bold red]⚠️ 关注提醒[/bold red]", border_style="red", box=box.ROUNDED))
        return

    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    table.add_column("关键词", style="bold", min_width=10)
    table.add_column("类型", width=8, justify="center")
    table.add_column("当前", justify="right")
    table.add_column("上次", justify="right")
    table.add_column("变化", justify="right")
    table.add_column("涨幅", justify="right")

    for a in alerts:
        kw_style = "bold magenta" if a["watched"] else "bold"
        kw = Text(a["keyword"], style=kw_style)
        if a["watched"]:
            kw.append(" ★", style="yellow")
        type_style = "bold red" if a["type"] == "spike" else "bold magenta"
        type_txt = Text("突增" if a["type"] == "spike" else "新现", style=type_style)
        table.add_row(
            kw, type_txt,
            str(a["current"]),
            str(a["previous"]),
            _fmt_delta(a["delta"]),
            _fmt_ratio(a["ratio"]),
        )
    console.print(Panel(table, title="[bold red]⚠️ 关注提醒 / 异常波动[/bold red]",
                        border_style="red", box=box.ROUNDED))


def render_keywords(keywords: List[Dict]):
    cols = 2
    rows = []
    for i in range(0, len(keywords), cols):
        rows.append(keywords[i:i + cols])

    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    for col_idx in range(cols):
        table.add_column(f"热词 #{col_idx + 1}", style="bold", min_width=18)
        table.add_column("次数", justify="right", width=8)
        table.add_column("变化", justify="right", width=10)

    for row in rows:
        render_row = []
        for _ in range(cols):
            render_row.extend(["", "", ""])
        for idx, kw in enumerate(row):
            base = idx * 3
            k = kw["keyword"]
            if kw["watched"]:
                k = f"[magenta]{k}[/magenta][yellow]★[/yellow]"
            elif kw["is_new"]:
                k = f"[cyan]{k}[/cyan]"
            render_row[base] = k
            render_row[base + 1] = str(kw["count"])
            ratio_txt = _fmt_ratio(kw["ratio"])
            delta_txt = _fmt_delta(kw["delta"])
            render_row[base + 2] = f"{delta_txt} ({ratio_txt})"
        table.add_row(*render_row)

    console.print(Panel(table, title="[bold]🔥 新增高频词[/bold]", border_style="yellow", box=box.ROUNDED))


def render_negative_snippets(snippets: List[Dict]):
    if not snippets:
        msg = Text("🎉 未发现负面舆情，玩家情绪稳定~", style="green")
        console.print(Panel(msg, title="[bold]💬 负面原句摘录[/bold]", border_style="yellow", box=box.ROUNDED))
        return

    table = Table(show_header=False, box=box.ROUNDED, expand=True, show_lines=True)
    table.add_column("#", width=3, justify="center", style="dim")
    table.add_column("内容", style="white")
    table.add_column("来源", width=10, style="bold cyan")
    table.add_column("作者", width=16, style="dim")

    source_style = {
        "steam": "[bold deep_sky_blue1]Steam[/bold deep_sky_blue1]",
        "taptap": "[bold green]TapTap[/bold green]",
        "bilibili": "[bold pink]B站[/bold pink]",
        "tieba": "[bold blue]贴吧[/bold blue]",
    }

    for i, s in enumerate(snippets, 1):
        src = source_style.get(s["source"].lower(), s["source"])
        content = Text(s["content"], style="white")
        table.add_row(str(i), content, src, s["author"] or "-")

    console.print(Panel(table, title="[bold]💬 负面原句摘录 (已去重)[/bold]", border_style="yellow", box=box.ROUNDED))


def render_top_links(links: List[Dict]):
    if not links:
        return

    table = Table(show_header=False, box=box.ROUNDED, expand=True, show_lines=True)
    table.add_column("#", width=3, justify="center", style="dim")
    table.add_column("内容摘要", style="white")
    table.add_column("来源", width=10, style="bold cyan")
    table.add_column("链接", style="underline blue")

    source_style = {
        "steam": "[bold deep_sky_blue1]Steam[/bold deep_sky_blue1]",
        "taptap": "[bold green]TapTap[/bold green]",
        "bilibili": "[bold pink]B站[/bold pink]",
        "tieba": "[bold blue]贴吧[/bold blue]",
    }

    for i, l in enumerate(links, 1):
        src = source_style.get(l["source"].lower(), l["source"])
        sentiment_color = "red" if l["sentiment"] < 0.35 else ("yellow" if l["sentiment"] < 0.65 else "green")
        marker = {"red": "😡", "yellow": "😐", "green": "😊"}[sentiment_color]
        snippet = f"{marker} {l['snippet']}"
        table.add_row(str(i), snippet, src, l["url"])

    console.print(Panel(table, title="[bold]🔗 需要优先查看的链接[/bold]", border_style="green", box=box.ROUNDED))


def render_watchlist(watchlist: List[Dict]):
    if not watchlist:
        console.print(Panel(Text("关注清单为空，使用 watch add 添加关键词", style="dim"),
                            title="[bold]⭐ 关注清单[/bold]", border_style="magenta", box=box.ROUNDED))
        return
    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    table.add_column("关键词", style="bold")
    table.add_column("状态", width=8, justify="center")
    table.add_column("阈值", width=8, justify="right")
    table.add_column("添加时间", justify="right", style="dim")
    for w in watchlist:
        status = Text("启用", style="bold green") if w["enabled"] else Text("禁用", style="dim")
        ts = datetime.fromtimestamp(w["added_at"]).strftime("%Y-%m-%d %H:%M")
        table.add_row(w["keyword"], status, f"x{w['threshold']}", ts)
    console.print(Panel(table, title="[bold]⭐ 关注清单[/bold]", border_style="magenta", box=box.ROUNDED))


def render_source_statuses(statuses: Dict[str, Dict], health_warnings: List[str] = None):
    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    table.add_column("来源", style="bold", width=12)
    table.add_column("状态", width=10, justify="center")
    table.add_column("时间窗口内", justify="right", width=10)
    table.add_column("原始抓取", justify="right", width=10)
    table.add_column("时间不明", justify="right", width=10)
    table.add_column("被窗口过滤", justify="right", width=10)

    order = ["steam", "taptap", "bilibili", "tieba"]
    shown = set()
    for src_name in order:
        if src_name in statuses:
            _render_status_row(table, src_name, statuses[src_name])
            shown.add(src_name)
    for src_name, st in statuses.items():
        if src_name not in shown:
            _render_status_row(table, src_name, st)

    console.print(Panel(table, title="[bold]📡 来源抓取状态[/bold]", border_style="cyan", box=box.ROUNDED))

    if health_warnings:
        for w in health_warnings:
            console.print(Panel(w, title="[bold yellow]⚠️ 来源健康提醒[/bold yellow]",
                                border_style="yellow", box=box.ROUNDED, style="yellow"))


def _render_status_row(table, src_name: str, st: Dict):
    source_label = {
        "steam": "[bold deep_sky_blue1]Steam[/bold deep_sky_blue1]",
        "taptap": "[bold green]TapTap[/bold green]",
        "bilibili": "[bold pink]B站[/bold pink]",
        "tieba": "[bold blue]贴吧[/bold blue]",
    }.get(src_name.lower(), src_name)
    if st.get("ok"):
        status = Text("成功", style="bold green")
        count = str(st.get("count", 0))
        raw = str(st.get("raw_count", st.get("count", 0)))
        tu_count = st.get("time_unknown_count", 0)
        raw_count = st.get("raw_count", st.get("count", 0)) or 1
        tu_pct = tu_count / raw_count * 100 if raw_count > 0 else 0
        tu = f"{tu_count} ({tu_pct:.0f}%)" if tu_count > 0 else "0"
        fo = str(st.get("filtered_out_by_time", 0))
    else:
        status = Text("不可用", style="bold red")
        count = Text("-", style="dim")
        raw = Text("-", style="dim")
        tu = Text("-", style="dim")
        fo = Text(f"[red]{st.get('reason', '未知')}[/red]", style="red")
    table.add_row(source_label, status, count, raw, tu, fo)


def detect_source_health(statuses: Dict[str, Dict], recent_scans: List[Dict] = None) -> List[str]:
    """检测来源持续问题：连续不可用/时间未知过高/样本归零"""
    warnings = []
    for src_name, st in statuses.items():
        if not st.get("ok"):
            fail_count = 1
            if recent_scans:
                for s in recent_scans:
                    ss = s.get("source_statuses", {})
                    if src_name in ss and not ss[src_name].get("ok", True):
                        fail_count += 1
            if fail_count >= 2:
                warnings.append(f"🔴 {src_name} 已连续 {fail_count} 次不可用，建议检查网络或换来源")
            elif fail_count == 1:
                warnings.append(f"🟡 {src_name} 当前不可用: {st.get('reason', '未知')}")
        else:
            tu_count = st.get("time_unknown_count", 0)
            raw = st.get("raw_count", st.get("count", 0)) or 1
            if raw > 0 and tu_count / raw > 0.5:
                warnings.append(f"🟡 {src_name} 时间不明占比 {tu_count/raw*100:.0f}%，短窗口统计可能不准确")
            if st.get("count", 0) == 0 and raw > 0:
                warnings.append(f"🟡 {src_name} 窗口内 0 条帖子（原始 {raw} 条），考虑扩大时间窗口")
            if recent_scans and len(recent_scans) >= 2:
                prev_ss = recent_scans[0].get("source_statuses", {})
                prev_count = prev_ss.get(src_name, {}).get("count", -1)
                cur_count = st.get("count", 0)
                if prev_count > 10 and cur_count == 0:
                    warnings.append(f"🔴 {src_name} 样本从 {prev_count} 突然归零，可能API异常或被封")
    return warnings


def render_watch_round_summary(
    round_idx: int,
    scanned_at: int,
    result: Dict,
    previous_result: Dict = None,
):
    ts = datetime.fromtimestamp(scanned_at).strftime("%H:%M:%S")
    sent = result["sentiment"]
    t = sent["total"]
    neg = sent["negative"]
    neg_pct = (neg / t * 100) if t else 0

    summary = Table.grid(expand=True)
    summary.add_column(style="bold cyan", width=10)
    summary.add_column()

    alerts_cnt = len(result.get("alerts", [])) + len(result.get("group_alerts", []))
    alerts_label = f"[bold red]{alerts_cnt} 条告警[/bold red]" if alerts_cnt > 0 else "[green]无告警[/green]"

    summary.add_row(f"[#{round_idx:02d}] {ts}", f"样本 {t} 条 | 负面 {neg} ({neg_pct:.0f}%) | {alerts_label}")

    top_items = []
    for ga in result.get("group_alerts", [])[:2]:
        top_items.append(f"[red]🚨 {ga['label']} +{ga['delta']} ({ga['current']})[/red]")
    for a in result.get("alerts", [])[:3 - len(top_items)]:
        top_items.append(f"[yellow]⚠️ {a['keyword']} +{a['delta']} ({a['current']})[/yellow]")
    if top_items:
        summary.add_row("", "  " + "  ".join(top_items))

    console.print(Panel(summary, border_style="cyan", box=box.ROUNDED))


def render_trend_summary(scans: List[Dict]):
    """渲染观察模式的趋势摘要（最近N轮）"""
    if len(scans) < 2:
        return

    table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    table.add_column("轮次", style="bold", width=8)
    table.add_column("时间", width=10)
    table.add_column("样本", justify="right", width=6)
    table.add_column("负面率", justify="right", width=8)
    table.add_column("情绪", justify="right", width=6)
    table.add_column("告警", justify="center", width=10)
    table.add_column("问题组趋势", style="dim")

    for s in scans:
        ts = datetime.fromtimestamp(s["scanned_at"]).strftime("%H:%M")
        total = s.get("total_posts", 0)
        neg = s.get("negative_posts", 0)
        neg_pct = f"{neg/total*100:.1f}%" if total else "0%"
        avg = s.get("avg_sentiment", 0)
        avg_str = f"{avg:.2f}"
        if avg < 0.35:
            avg_str = f"[red]{avg_str}[/red]"
        elif avg < 0.65:
            avg_str = f"[yellow]{avg_str}[/yellow]"
        else:
            avg_str = f"[green]{avg_str}[/green]"

        alerts = s.get("alerts", [])
        group_alerts = s.get("group_alerts", [])
        alert_cnt = len(alerts) + len(group_alerts)
        alert_str = f"[red]{alert_cnt}[/red]" if alert_cnt > 0 else "[green]0[/green]"

        group_trends = []
        for ga in group_alerts[:3]:
            label = ga.get("label", "")
            delta = ga.get("delta", 0)
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            color = "red" if delta > 0 else ("green" if delta < 0 else "dim")
            group_trends.append(f"[{color}]{label} {arrow}{delta}[/{color}]")
        group_str = "  ".join(group_trends) if group_trends else "-"

        table.add_row(f"#{s.get('id', '?')}", ts, str(total), neg_pct, avg_str, alert_str, group_str)

    console.print(Panel(table, title="[bold]📈 观察趋势摘要[/bold]", border_style="magenta", box=box.ROUNDED))


def render_compare(scan_a: Dict, scan_b: Dict):
    """对比两次巡检，A=旧 B=新"""
    ts_a = datetime.fromtimestamp(scan_a["scanned_at"]).strftime("%m-%d %H:%M")
    ts_b = datetime.fromtimestamp(scan_b["scanned_at"]).strftime("%m-%d %H:%M")

    # 情绪对比
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column()
    grid.add_column(justify="right", style="bold cyan")
    grid.add_column(justify="right", style="bold yellow")

    t_a = scan_a.get("total_posts", 0) or 1
    t_b = scan_b.get("total_posts", 0) or 1
    neg_a = scan_a.get("negative_posts", 0)
    neg_b = scan_b.get("negative_posts", 0)
    pct_a = neg_a / t_a * 100
    pct_b = neg_b / t_b * 100
    avg_a = scan_a.get("avg_sentiment", 0)
    avg_b = scan_b.get("avg_sentiment", 0)

    grid.add_row("", f"[cyan]A ({ts_a})[/cyan]", f"[yellow]B ({ts_b})[/yellow]")
    grid.add_row("样本量", str(t_a), str(t_b))
    grid.add_row("负面率", f"{pct_a:.1f}%", f"{pct_b:.1f}%")
    neg_delta = pct_b - pct_a
    grid.add_row("负面率变化", "", f"{'+' if neg_delta >= 0 else ''}{neg_delta:.1f}%")
    grid.add_row("平均情绪", f"{avg_a:.2f}", f"{avg_b:.2f}")
    console.print(Panel(grid, title="[bold]📊 对比概览  A(旧) vs B(新)[/bold]",
                        border_style="magenta", box=box.ROUNDED))
    console.print()

    # 热词对比
    kw_a = {k["keyword"]: k for k in scan_a.get("top_keywords", [])}
    kw_b = {k["keyword"]: k for k in scan_b.get("top_keywords", [])}
    all_kw = sorted(set(kw_a.keys()) | set(kw_b.keys()),
                    key=lambda k: -(kw_b.get(k, {}).get("count", 0) + kw_a.get(k, {}).get("count", 0)))

    kw_table = Table(show_header=True, header_style="bold", box=box.ROUNDED, expand=True)
    kw_table.add_column("热词", style="bold", min_width=12)
    kw_table.add_column("A次数", justify="right")
    kw_table.add_column("B次数", justify="right")
    kw_table.add_column("变化", justify="right")

    shown = 0
    for k in all_kw:
        ca = kw_a.get(k, {}).get("count", 0)
        cb = kw_b.get(k, {}).get("count", 0)
        if ca == 0 and cb == 0:
            continue
        delta = cb - ca
        if ca > 0:
            ratio = cb / ca
        else:
            ratio = float("inf") if cb > 0 else 1.0
        style = "red" if delta > 3 else ("green" if delta < -3 else "")
        delta_str = _delta_str(delta)
        ratio_str = _ratio_str(ratio) if ratio != 1.0 else ""
        change = f"{delta_str} {ratio_str}".strip()
        kw_table.add_row(k, str(ca), str(cb), f"[{style}]{change}[/{style}]" if style else change)
        shown += 1
        if shown >= 20:
            break

    console.print(Panel(kw_table, title="[bold]🔥 热词对比[/bold]", border_style="yellow", box=box.ROUNDED))
    console.print()

    # 告警对比
    alerts_b = scan_b.get("alerts", [])
    group_alerts_b = scan_b.get("group_alerts", [])
    if group_alerts_b:
        render_group_alerts(group_alerts_b)
        console.print()
    if alerts_b:
        render_alerts(alerts_b)
        console.print()

    # 链接对比：B的新增链接
    links_a = {l["url"] for l in scan_a.get("top_links", [])}
    links_b = scan_b.get("top_links", [])
    new_links = [l for l in links_b if l["url"] not in links_a]
    if new_links:
        render_top_links(new_links)
        console.print()


def render_result(result: Dict, game: str, sources: List[str], time_range: str,
                  scanned_at: int, previous_summary: Dict = None, round_idx: int = None):
    render_header(game, sources, time_range, scanned_at, round_idx)
    render_sentiment(result["sentiment"], previous_summary)
    console.print()
    if result.get("group_alerts"):
        render_group_alerts(result["group_alerts"])
        console.print()
    render_alerts(result["alerts"])
    console.print()
    render_keywords(result["top_keywords"])
    console.print()
    render_negative_snippets(result["negative_snippets"])
    console.print()
    render_top_links(result["top_links"])


def render_scan_detail(scan: Dict):
    game = scan.get("game", "")
    sources = scan.get("sources", [])
    time_range = scan.get("time_range", "")
    scanned_at = scan.get("scanned_at", 0)
    render_header(game, sources, time_range, scanned_at)

    sent_summary = {
        "total": scan.get("total_posts", 0),
        "negative": scan.get("negative_posts", 0),
        "neutral": 0,
        "positive": 0,
        "avg_sentiment": scan.get("avg_sentiment", 0),
    }
    total = sent_summary["total"]
    neg = sent_summary["negative"]
    sent_summary["positive"] = max(0, total - neg)
    render_sentiment(sent_summary)
    console.print()

    group_alerts = scan.get("group_alerts", [])
    if group_alerts:
        render_group_alerts(group_alerts)
        console.print()

    alerts = scan.get("alerts", [])
    if alerts:
        render_alerts(alerts)
        console.print()

    top_keywords = scan.get("top_keywords", [])
    if top_keywords:
        render_keywords(top_keywords)
        console.print()

    negative_snippets = scan.get("negative_snippets", [])
    if negative_snippets:
        render_negative_snippets(negative_snippets)
        console.print()

    top_links = scan.get("top_links", [])
    if top_links:
        render_top_links(top_links)
        console.print()

    source_statuses = scan.get("source_statuses", {})
    if source_statuses:
        render_source_statuses(source_statuses)


def export_markdown(
    scan: Dict,
    previous_scan: Dict = None,
) -> str:
    lines = []
    game = scan.get("game", "")
    sources = ", ".join(scan.get("sources", []))
    time_range = scan.get("time_range", "")
    ts = datetime.fromtimestamp(scan.get("scanned_at", 0)).strftime("%Y-%m-%d %H:%M:%S")

    lines.append(f"# 舆情巡检报告 - {game}")
    lines.append("")
    lines.append(f"- **扫描时间**: {ts}")
    lines.append(f"- **来源**: {sources}")
    lines.append(f"- **时间窗口**: {time_range}")
    lines.append(f"- **样本量**: {scan.get('total_posts', 0)} 条")
    lines.append(f"- **负面帖**: {scan.get('negative_posts', 0)} 条")
    avg = scan.get("avg_sentiment", 0)
    lines.append(f"- **平均情绪分**: {avg:.2f}")
    lines.append("")

    # 同义词组告警
    group_alerts = scan.get("group_alerts", [])
    if group_alerts:
        lines.append("## 🚨 同义词组告警（合并统计）")
        lines.append("")
        lines.append("| 问题组 | 类型 | 当前 | 上次 | 变化 | 涨幅 | 构成 |")
        lines.append("|--------|------|------|------|------|------|------|")
        for ga in group_alerts:
            delta = ga.get("delta", 0)
            ratio = ga.get("ratio", 1)
            breakdown_parts = [f"{w}×{c}" for w, c in sorted(ga.get("breakdown", {}).items(), key=lambda x: -x[1])]
            bd = " + ".join(breakdown_parts[:4])
            lines.append(f"| {ga.get('label','')} | {ga.get('type','')} | {ga.get('current',0)} | "
                         f"{ga.get('previous',0)} | {_delta_str(delta)} | {_ratio_str(ratio)} | {bd} |")
            reps = ga.get("representative_posts", [])
            if reps:
                for rep in reps[:2]:
                    snippet = rep.get("content", "")[:100]
                    src = rep.get("source", "")
                    lines.append(f"  - 💬 [{src}] {snippet}")
        lines.append("")

    # 普通告警
    alerts = scan.get("alerts", [])
    if alerts:
        lines.append("## ⚠️ 异常波动")
        lines.append("")
        lines.append("| 关键词 | 类型 | 当前 | 上次 | 变化 | 涨幅 |")
        lines.append("|--------|------|------|------|------|------|")
        for a in alerts:
            delta = a.get("delta", 0)
            ratio = a.get("ratio", 1)
            lines.append(f"| {a.get('keyword', '')} | {a.get('type', '')} | {a.get('current', 0)} | "
                         f"{a.get('previous', 0)} | {_delta_str(delta)} | {_ratio_str(ratio)} |")
        lines.append("")

    # 高频词
    top_kw = scan.get("top_keywords", [])
    if top_kw:
        lines.append("## 🔥 高频词")
        lines.append("")
        lines.append("| 关键词 | 次数 | 变化 | 涨幅 |")
        lines.append("|--------|------|------|------|")
        for kw in top_kw[:20]:
            delta = kw.get("delta", 0)
            ratio = kw.get("ratio", 1)
            lines.append(f"| {kw.get('keyword', '')} | {kw.get('count', 0)} | "
                         f"{_delta_str(delta)} | {_ratio_str(ratio)} |")
        lines.append("")

    # 负面原句
    snippets = scan.get("negative_snippets", [])
    if snippets:
        lines.append("## 💬 负面原句摘录")
        lines.append("")
        for i, s in enumerate(snippets, 1):
            lines.append(f"{i}. **[{s.get('source', '')}]** {s.get('content', '')}")
            lines.append(f"   - 作者: {s.get('author', '-')}")
            lines.append(f"   - 链接: {s.get('url', '')}")
            lines.append("")

    # 优先链接
    links = scan.get("top_links", [])
    if links:
        lines.append("## 🔗 优先查看链接")
        lines.append("")
        for i, l in enumerate(links, 1):
            lines.append(f"{i}. [{l.get('snippet', '')}]({l.get('url', '')}) _({l.get('source', '')})_")
        lines.append("")

    return "\n".join(lines)


def export_trend_markdown(scans: List[Dict]) -> str:
    """导出趋势摘要为 Markdown"""
    if len(scans) < 2:
        return ""
    lines = []
    lines.append("## 📈 观察趋势摘要")
    lines.append("")
    lines.append("| # | 时间 | 样本量 | 负面率 | 情绪分 | 告警 | 问题组趋势 |")
    lines.append("|---|------|--------|--------|--------|------|------------|")
    for i, s in enumerate(scans, 1):
        ts = datetime.fromtimestamp(s.get("scanned_at", 0)).strftime("%H:%M")
        total = s.get("total_posts", 0)
        neg = s.get("negative_posts", 0)
        neg_pct = f"{neg/total*100:.1f}%" if total else "0%"
        avg = s.get("avg_sentiment", 0)
        alerts = s.get("alerts", [])
        group_alerts = s.get("group_alerts", [])
        alert_cnt = len(alerts) + len(group_alerts)
        trends = []
        for ga in group_alerts[:3]:
            label = ga.get("label", "")
            delta = ga.get("delta", 0)
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            trends.append(f"{label} {arrow}{delta}")
        trend_str = ", ".join(trends) if trends else "-"
        lines.append(f"| {i} | {ts} | {total} | {neg_pct} | {avg:.2f} | {alert_cnt} | {trend_str} |")
    lines.append("")

    # 简短总结
    first = scans[0]
    last = scans[-1]
    t_first = first.get("total_posts", 0) or 1
    t_last = last.get("total_posts", 0) or 1
    pct_first = first.get("negative_posts", 0) / t_first * 100
    pct_last = last.get("negative_posts", 0) / t_last * 100
    neg_trend = "下降 ↓" if pct_last < pct_first else ("上升 ↑" if pct_last > pct_first else "持平 →")
    lines.append(f"**趋势总结**: 负面率从 {pct_first:.1f}% → {pct_last:.1f}% ({neg_trend})，"
                 f"样本量 {t_first} → {t_last}")
    lines.append("")

    return "\n".join(lines)


def export_report_markdown(
    scans: List[Dict],
    title: str = "舆情巡检报告",
) -> str:
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"共 {len(scans)} 次巡检记录")
    lines.append("")

    # 趋势摘要（如果有2+条记录）
    if len(scans) >= 2:
        reversed_scans = list(reversed(scans))
        lines.append(export_trend_markdown(reversed_scans))

    # 概览表
    lines.append("## 巡检概览")
    lines.append("")
    lines.append("| # | 时间 | 游戏 | 来源 | 窗口 | 样本量 | 负面数 | 负面率 |")
    lines.append("|---|------|------|------|------|--------|--------|--------|")
    for i, s in enumerate(scans, 1):
        ts = datetime.fromtimestamp(s.get("scanned_at", 0)).strftime("%m-%d %H:%M")
        src = ", ".join(s.get("sources", []))
        if len(src) > 20:
            src = src[:18] + "…"
        total = s.get("total_posts", 0)
        neg = s.get("negative_posts", 0)
        neg_pct = f"{(neg/total*100):.1f}%" if total else "0%"
        lines.append(f"| {i} | {ts} | {s.get('game', '')} | {src} | "
                     f"{s.get('time_range', '')} | {total} | {neg} | {neg_pct} |")
    lines.append("")

    # 每次详情
    lines.append("## 各次详情")
    lines.append("")
    for idx, s in enumerate(scans, 1):
        lines.append(f"### 第 {idx} 次 - "
                     f"{datetime.fromtimestamp(s.get('scanned_at',0)).strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append(export_markdown(s))
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def render_error(msg: str):
    console.print(Panel(msg, title="[bold]❌ 错误[/bold]",
                        border_style="red", box=box.ROUNDED, style="bold red"))


def render_info(msg: str):
    console.print(Panel(msg, title="[bold]ℹ️  提示[/bold]",
                        border_style="cyan", box=box.ROUNDED, style="cyan"))


def render_success(msg: str):
    console.print(Panel(msg, title="[bold]✅ 完成[/bold]",
                        border_style="green", box=box.ROUNDED, style="bold green"))
