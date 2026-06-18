from datetime import datetime
from typing import Dict, List

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
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
    """渲染同义词组合并告警（置顶，更醒目）"""
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
        kw_style = "bold red" if a["watched"] else "bold"
        kw = Text(a["label"], style=kw_style)
        if a["watched"]:
            kw.append(" ★", style="yellow")
        type_style = "bold red" if a["type"] == "spike" else "bold magenta"
        type_txt = Text("突增" if a["type"] == "spike" else "新现", style=type_style)
        # 构成示例：闪退×3 + 崩溃×2
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
        # 代表原句
        reps = a.get("representative_posts", [])
        if reps:
            rep = reps[0]
            snippet = rep.get("content", "")[:80]
            if len(rep.get("content", "")) > 80:
                snippet += "…"
            src = rep.get("source", "")
            table.add_row(
                Text("  💬 代表原句", style="dim"),
                Text("", style="dim"),
                Text("", style="dim"),
                Text("", style="dim"),
                Text("", style="dim"),
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
            kw,
            type_txt,
            str(a["current"]),
            str(a["previous"]),
            _fmt_delta(a["delta"]),
            _fmt_ratio(a["ratio"]),
        )
    panel = Panel(table, title="[bold red]⚠️ 关注提醒 / 异常波动[/bold red]", border_style="red", box=box.ROUNDED)
    console.print(panel)


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


def render_source_statuses(statuses: Dict[str, Dict]):
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
        tu = str(st.get("time_unknown_count", 0))
        fo = str(st.get("filtered_out_by_time", 0))
    else:
        status = Text("不可用", style="bold red")
        count = Text("-", style="dim")
        raw = Text("-", style="dim")
        tu = Text("-", style="dim")
        fo = Text(f"[red]{st.get('reason', '未知')}[/red]", style="red")
    table.add_row(source_label, status, count, raw, tu, fo)


def render_watch_round_summary(
    round_idx: int,
    scanned_at: int,
    result: Dict,
    previous_result: Dict = None,
):
    """观察模式下每轮的简短摘要"""
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

    prev_neg_pct = None
    if previous_result:
        pt = previous_result.get("total", 0) or 1
        pn = previous_result.get("negative", 0)
        prev_neg_pct = pn / pt * 100

    summary.add_row(f"[#{round_idx:02d}] {ts}", f"样本 {t} 条 | 负面 {neg} ({neg_pct:.0f}%) | {alerts_label}")

    # 列出前3个告警或热词
    top_items = []
    for ga in result.get("group_alerts", [])[:2]:
        top_items.append(f"[red]🚨 {ga['label']} +{ga['delta']} ({ga['current']})[/red]")
    for a in result.get("alerts", [])[:3 - len(top_items)]:
        top_items.append(f"[yellow]⚠️ {a['keyword']} +{a['delta']} ({a['current']})[/yellow]")
    if top_items:
        summary.add_row("", "  " + "  ".join(top_items))

    console.print(Panel(summary, border_style="cyan", box=box.ROUNDED))


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
    """展开显示某次巡检的完整详情"""
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
    # 粗略估计中性/正面（因为没存全量）
    sent_summary["positive"] = max(0, total - neg)
    render_sentiment(sent_summary)
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
    """导出单次巡检为 Markdown 格式"""
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

    # 告警
    alerts = scan.get("alerts", [])
    group_alerts = []  # 旧数据可能没有
    if alerts or group_alerts:
        lines.append("## ⚠️ 异常波动")
        lines.append("")
        lines.append("| 关键词 | 类型 | 当前 | 上次 | 变化 | 涨幅 |")
        lines.append("|--------|------|------|------|------|------|")
        for a in alerts:
            delta = a.get("delta", 0)
            delta_str = f"+{delta}" if delta > 0 else str(delta)
            ratio = a.get("ratio", 1)
            if isinstance(ratio, (int, float)):
                ratio_str = f"x{ratio}"
            else:
                ratio_str = str(ratio)
            lines.append(f"| {a.get('keyword', '')} | {a.get('type', '')} | {a.get('current', 0)} | {a.get('previous', 0)} | {delta_str} | {ratio_str} |")
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
            delta_str = f"+{delta}" if delta > 0 else (str(delta) if delta < 0 else "~")
            ratio = kw.get("ratio", 1)
            if isinstance(ratio, (int, float)):
                ratio_str = f"x{ratio}"
            else:
                ratio_str = str(ratio)
            lines.append(f"| {kw.get('keyword', '')} | {kw.get('count', 0)} | {delta_str} | {ratio_str} |")
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


def export_report_markdown(
    scans: List[Dict],
    title: str = "舆情巡检报告",
) -> str:
    """导出多次巡检为 Markdown 报告（带趋势）"""
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"共 {len(scans)} 次巡检记录")
    lines.append("")

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
        lines.append(f"| {i} | {ts} | {s.get('game', '')} | {src} | {s.get('time_range', '')} | {total} | {neg} | {neg_pct} |")
    lines.append("")

    # 每次详情
    lines.append("## 各次详情")
    lines.append("")
    for idx, s in enumerate(scans, 1):
        lines.append(f"### 第 {idx} 次 - {datetime.fromtimestamp(s.get('scanned_at',0)).strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        prev = scans[idx] if idx < len(scans) else None
        lines.append(export_markdown(s, prev))
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
