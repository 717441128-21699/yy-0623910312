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


def render_header(game: str, sources: List[str], time_range: str, scanned_at: int):
    ts = datetime.fromtimestamp(scanned_at).strftime("%Y-%m-%d %H:%M")
    src = ", ".join(sources) if sources else "ALL"
    header = Table.grid(expand=True)
    header.add_column(style="bold cyan")
    header.add_column(justify="right", style="dim")
    header.add_row(
        f"🎮 舆情巡检  |  游戏: [bold yellow]{game}[/bold yellow]",
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


def render_result(result: Dict, game: str, sources: List[str], time_range: str,
                  scanned_at: int, previous_summary: Dict = None):
    render_header(game, sources, time_range, scanned_at)
    render_sentiment(result["sentiment"], previous_summary)
    console.print()
    render_alerts(result["alerts"])
    console.print()
    render_keywords(result["top_keywords"])
    console.print()
    render_negative_snippets(result["negative_snippets"])
    console.print()
    render_top_links(result["top_links"])


def render_error(msg: str):
    console.print(Panel(Text(msg, style="bold red"), title="[bold]❌ 错误[/bold]",
                        border_style="red", box=box.ROUNDED))


def render_info(msg: str):
    console.print(Panel(Text(msg, style="cyan"), title="[bold]ℹ️  提示[/bold]",
                        border_style="cyan", box=box.ROUNDED))


def render_success(msg: str):
    console.print(Panel(Text(msg, style="bold green"), title="[bold]✅ 完成[/bold]",
                        border_style="green", box=box.ROUNDED))
