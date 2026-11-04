"""
=============================================================
  Trading Bot - Live Dashboard
  لوحة التحكم المباشرة بالـ Terminal
=============================================================
"""
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.progress import Progress, BarColumn, TextColumn
    from rich.text import Text
    from rich.layout import Layout
    from rich.live import Live
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    logger.warning("rich not installed - using basic terminal output")


# ===== HELPERS =====

def _clr(val: float, pos_col: str = "green", neg_col: str = "red") -> str:
    """Return rich color tag based on value sign."""
    return pos_col if val >= 0 else neg_col


def _arrow(val: float) -> str:
    return "▲" if val > 0 else "▼" if val < 0 else "─"


def _signal_color(sig: str) -> str:
    colors = {"BUY": "green", "SELL": "red", "NEUTRAL": "yellow", "WAIT": "dim"}
    return colors.get(sig, "white")


def _progress_bar(pct: float, width: int = 20) -> str:
    """ASCII progress bar."""
    pct = max(0, min(100, pct))
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:.1f}%"


# ===== DASHBOARD CLASS =====

class Dashboard:
    """Live terminal dashboard for the trading bot."""

    def __init__(self):
        self.console   = Console() if RICH_AVAILABLE else None
        self.log_lines = []          # Last N log messages
        self.max_logs  = 25

    def add_log(self, msg: str, level: str = "INFO"):
        """Add a log line to the dashboard."""
        ts  = datetime.now().strftime("%H:%M:%S")
        col = {"INFO": "white", "BUY": "green", "SELL": "red",
               "WARN": "yellow", "ERROR": "bold red", "SUCCESS": "bold green"}.get(level, "white")
        self.log_lines.append((ts, level, msg, col))
        if len(self.log_lines) > self.max_logs:
            self.log_lines.pop(0)

    # ===== RENDER SECTIONS (rich) =====

    def _render_header(self, goal_status: dict, start_time: datetime, dry_run: bool) -> Panel:
        prog  = goal_status.get("progress", 0)
        status= goal_status.get("status", "ACTIVE")
        bal   = goal_status.get("current_balance", 0)
        profit= goal_status.get("total_profit", 0)
        target= goal_status.get("target_usd", 0)

        elapsed = str(datetime.now() - start_time).split(".")[0]
        mode_txt = "[bold yellow]DRY RUN[/]" if dry_run else "[bold green]LIVE[/]"

        bar_filled = int(20 * prog / 100)
        bar = "[green]" + "█" * bar_filled + "[/][dim]" + "░" * (20 - bar_filled) + "[/]"

        status_color = {"GOAL_ACHIEVED": "bold green", "STOP_LOSS": "bold red",
                        "DAILY_LIMIT": "yellow", "ACTIVE": "cyan"}.get(status, "white")

        txt = (
            f"  🤖 [bold cyan]MT5 Trading Bot[/]  |  Mode: {mode_txt}  |  "
            f"Status: [{status_color}]{status}[/]  |  Runtime: {elapsed}\n"
            f"  Balance: [bold]${bal:.2f}[/]  |  "
            f"P/L: [{_clr(profit)}]{_arrow(profit)} ${profit:+.2f}[/]  |  "
            f"Target: [bold]${target:.2f}[/]\n"
            f"  Progress: {bar} {prog:.1f}%  |  Remaining: [yellow]${goal_status.get('remaining', 0):.2f}[/]"
        )
        return Panel(txt, title="[bold white]⚡ TRADING BOT DASHBOARD ⚡[/]",
                     border_style="bold blue", padding=(0, 1))

    def _render_account(self, account: dict, goal: dict) -> Panel:
        from rich.table import Table
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        t.add_column("Key",   style="dim", width=18)
        t.add_column("Value", style="bold white")

        daily = goal.get("daily_profit", 0)
        daily_col = _clr(daily)

        t.add_row("Balance",      f"${account.get('balance', 0):.2f}")
        t.add_row("Equity",       f"${account.get('equity', 0):.2f}")
        t.add_row("Profit (open)",f"[{_clr(account.get('profit',0))}]${account.get('profit',0):+.2f}[/]")
        t.add_row("Daily P/L",    f"[{daily_col}]{_arrow(daily)} ${daily:+.2f}[/]")
        t.add_row("Free Margin",  f"${account.get('margin_free', 0):.2f}")
        t.add_row("Margin Level", f"{account.get('margin_level', 0):.0f}%")
        t.add_row("Leverage",     f"1:{account.get('leverage', 0)}")
        t.add_row("Account",      f"#{account.get('login', 'N/A')} | {account.get('server', 'N/A')}")
        return Panel(t, title="[bold]📊 Account[/]", border_style="blue")

    def _render_goal(self, goal: dict) -> Panel:
        from rich.table import Table
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        t.add_column("Key",   style="dim", width=18)
        t.add_column("Value", style="bold")

        p = goal.get("profit_pct", goal.get("total_profit_pct", 0))
        pbar_filled = int(20 * goal.get("progress", 0) / 100)
        pbar = "█" * pbar_filled + "░" * (20 - pbar_filled)

        t.add_row("Goal Target",   f"[green]${goal.get('target_usd', 0):.2f}[/]")
        t.add_row("Total Profit",  f"[{_clr(goal.get('total_profit',0))}]${goal.get('total_profit',0):+.2f} ({goal.get('total_profit_pct',0):.1f}%)[/]")
        t.add_row("Progress",      f"[green]{pbar}[/] {goal.get('progress',0):.1f}%")
        t.add_row("Remaining",     f"[yellow]${goal.get('remaining', 0):.2f}[/]")
        t.add_row("Daily Target",  f"${goal.get('daily_target_usd', 5):.2f}")
        t.add_row("Daily P/L",     f"[{_clr(goal.get('daily_profit',0))}]${goal.get('daily_profit',0):+.2f}[/]")
        t.add_row("Max Loss Limit",f"[red]${goal.get('max_loss', 0):.2f}[/]")
        return Panel(t, title="[bold]🎯 Goal Tracker[/]", border_style="green")

    def _render_market(self, analyses: dict) -> Panel:
        t = Table(box=box.SIMPLE_HEAD, show_header=True)
        t.add_column("Symbol",     style="bold cyan",   width=12)
        t.add_column("Price",      style="white",        width=12)
        t.add_column("RSI",        style="white",        width=7)
        t.add_column("MACD",       style="white",        width=8)
        t.add_column("EMA Trend",  style="white",        width=12)
        t.add_column("ADX",        style="white",        width=7)
        t.add_column("BB %B",      style="white",        width=8)
        t.add_column("Score",      style="white",        width=8)
        t.add_column("Signal",     style="bold",         width=10)
        t.add_column("Conf%",      style="white",        width=7)
        t.add_column("Action",     style="bold",         width=8)

        for sym, data in analyses.items():
            if not data:
                continue
            ind   = data.get("indicators", {})
            rsi_v = ind.get("rsi", {}).get("value", 0) or 0
            macd_h= ind.get("macd", {}).get("hist", 0) or 0
            ema_s = ind.get("ema", {}).get("signal", "?")
            adx_v = ind.get("adx", {}).get("adx", 0) or 0
            pct_b = ind.get("bollinger", {}).get("pct_b", 0.5) or 0.5
            score = data.get("overall_score", 0)
            conf  = data.get("confidence", 0)
            action= data.get("action", "WAIT")
            price = data.get("current_price", 0)
            sig   = data.get("action", "WAIT")

            rsi_col = "red" if rsi_v > 70 else "green" if rsi_v < 30 else "white"
            macd_col = "green" if macd_h > 0 else "red"
            score_col = "green" if score > 10 else "red" if score < -10 else "yellow"
            act_col = _signal_color(action)

            t.add_row(
                sym,
                f"{price:.5f}" if price < 1000 else f"{price:.2f}",
                f"[{rsi_col}]{rsi_v:.0f}[/]",
                f"[{macd_col}]{macd_h:+.5f}[/]" if abs(macd_h) < 1 else f"[{macd_col}]{macd_h:+.2f}[/]",
                f"[{_signal_color(ema_s)}]{ema_s}[/]",
                f"{adx_v:.0f}",
                f"{pct_b:.2f}",
                f"[{score_col}]{score:+.0f}[/]",
                f"[{_signal_color(sig)}]{sig}[/]",
                f"{conf:.0f}%",
                f"[bold {act_col}]{action}[/]",
            )
        return Panel(t, title="[bold]📈 Market Analysis[/]", border_style="blue")

    def _render_indicator_detail(self, symbol: str, data: dict) -> Panel:
        """Detailed indicator breakdown for one symbol."""
        if not data:
            return Panel("No data", title="Indicators Detail")
        ind = data.get("indicators", {})
        t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        t.add_column("Indicator",  style="dim",   width=18)
        t.add_column("Value",      style="white",  width=20)
        t.add_column("Signal",     style="bold",   width=10)

        def row(name, detail, sig):
            col = _signal_color(sig)
            t.add_row(name, detail or "-", f"[{col}]{sig}[/]")

        ema  = ind.get("ema", {})
        row("EMA 20/50/200",
            f"{ema.get('ema20',0):.5f} / {ema.get('ema50',0):.5f} / {ema.get('ema200',0):.5f}" if ema.get('ema20') else "N/A",
            ema.get("signal","?"))

        ich = ind.get("ichimoku", {})
        row("Ichimoku",
            f"T={ich.get('tenkan',0):.5f} K={ich.get('kijun',0):.5f}" if ich.get('tenkan') else "N/A",
            ich.get("signal","?"))

        rsi = ind.get("rsi", {})
        row("RSI(14)",   f"{rsi.get('value',0):.1f}", rsi.get("signal","?"))

        macd = ind.get("macd", {})
        row("MACD",
            f"M={macd.get('macd',0):.5f} S={macd.get('signal_line',0):.5f} H={macd.get('hist',0):.5f}" if macd.get('macd') else "N/A",
            macd.get("signal","?"))

        st = ind.get("stochastic", {})
        row("Stochastic", f"K={st.get('k',0):.1f} D={st.get('d',0):.1f}", st.get("signal","?"))

        cci = ind.get("cci", {})
        row("CCI(20)",   f"{cci.get('value',0):.1f}", cci.get("signal","?"))

        wil = ind.get("williams", {})
        row("Williams %R", f"{wil.get('value',0):.1f}", wil.get("signal","?"))

        mfi = ind.get("mfi", {})
        row("MFI(14)",   f"{mfi.get('value',0):.1f}", mfi.get("signal","?"))

        roc = ind.get("roc", {})
        row("ROC(10)",   f"{roc.get('value',0):.2f}%", roc.get("signal","?"))

        bb = ind.get("bollinger", {})
        row("Bollinger",
            f"U={bb.get('upper',0):.5f} M={bb.get('mid',0):.5f} L={bb.get('lower',0):.5f}" if bb.get('upper') else "N/A",
            bb.get("signal","?"))

        atr = ind.get("atr", {})
        row("ATR(14)",   f"{atr.get('value',0):.5f} ({atr.get('pct',0):.2f}%)", "NEUTRAL")

        kelt = ind.get("keltner", {})
        row("Keltner",   f"U={kelt.get('upper',0):.5f} L={kelt.get('lower',0):.5f}" if kelt.get('upper') else "N/A", kelt.get("signal","?"))

        don = ind.get("donchian", {})
        row("Donchian",  f"H={don.get('upper',0):.5f} L={don.get('lower',0):.5f}" if don.get('upper') else "N/A", don.get("signal","?"))

        adx = ind.get("adx", {})
        row("ADX",       adx.get("detail","N/A"), adx.get("signal","?"))

        aroon = ind.get("aroon", {})
        row("Aroon",     aroon.get("detail","N/A"), aroon.get("signal","?"))

        obv = ind.get("obv", {})
        row("OBV",       f"{obv.get('value',0):.0f}", obv.get("signal","?"))

        pat = ind.get("patterns", {})
        row("Patterns",  pat.get("detail","None"), pat.get("signal","?"))

        sr = ind.get("sr", {})
        row("S/R Levels",
            f"Res={sr.get('nearest_resistance',0):.5f} Sup={sr.get('nearest_support',0):.5f}" if sr.get('nearest_resistance') else "N/A",
            sr.get("signal","?"))

        return Panel(t, title=f"[bold]🔬 Indicator Detail: {symbol}[/]", border_style="cyan")

    def _render_positions(self, positions: list) -> Panel:
        t = Table(box=box.SIMPLE_HEAD, show_header=True)
        t.add_column("Ticket",  style="dim",    width=10)
        t.add_column("Symbol",  style="cyan",   width=12)
        t.add_column("Type",    style="bold",   width=6)
        t.add_column("Lots",    style="white",  width=6)
        t.add_column("Open",    style="white",  width=12)
        t.add_column("Current", style="white",  width=12)
        t.add_column("SL",      style="red",    width=12)
        t.add_column("TP",      style="green",  width=12)
        t.add_column("P/L",     style="bold",   width=10)
        t.add_column("Time",    style="dim",    width=12)

        if not positions:
            t.add_row("-", "No open positions", "", "", "", "", "", "", "", "")
        else:
            for p in positions:
                pl = p.get("profit", 0)
                pl_col = _clr(pl)
                type_col = "green" if p["type"] == "BUY" else "red"
                t.add_row(
                    str(p["ticket"]),
                    p["symbol"],
                    f"[{type_col}]{p['type']}[/]",
                    str(p["volume"]),
                    f"{p['open_price']:.5f}",
                    f"{p['current_price']:.5f}",
                    f"{p['sl']:.5f}" if p["sl"] else "-",
                    f"{p['tp']:.5f}" if p["tp"] else "-",
                    f"[{pl_col}]{_arrow(pl)} ${pl:+.2f}[/]",
                    p["open_time"].strftime("%H:%M") if p.get("open_time") else "-",
                )
        return Panel(t, title=f"[bold]💼 Open Positions ({len(positions)})[/]", border_style="yellow")

    def _render_history(self, trades: list) -> Panel:
        t = Table(box=box.SIMPLE_HEAD, show_header=True)
        t.add_column("Time",   style="dim",   width=12)
        t.add_column("Symbol", style="cyan",  width=12)
        t.add_column("Type",   style="bold",  width=6)
        t.add_column("Lots",   style="white", width=6)
        t.add_column("Price",  style="white", width=12)
        t.add_column("P/L",    style="bold",  width=10)

        recent = trades[:10] if trades else []
        if not recent:
            t.add_row("-", "No trade history", "", "", "", "")
        else:
            for tr in recent:
                pl = tr.get("profit", 0)
                pl_col = _clr(pl)
                type_col = "green" if tr["type"] == "BUY" else "red"
                t.add_row(
                    tr["time"].strftime("%m/%d %H:%M") if tr.get("time") else "-",
                    tr["symbol"],
                    f"[{type_col}]{tr['type']}[/]",
                    str(tr["volume"]),
                    f"{tr['price']:.5f}",
                    f"[{pl_col}]{_arrow(pl)} ${pl:+.2f}[/]",
                )
        return Panel(t, title="[bold]📜 Trade History (Last 10)[/]", border_style="dim")

    def _render_logs(self) -> Panel:
        from rich.text import Text
        txt = Text()
        for ts, level, msg, col in self.log_lines[-15:]:
            txt.append(f"[{ts}] ", style="dim")
            txt.append(f"{level:<7} ", style=col)
            txt.append(f"{msg}\n", style="white")
        return Panel(txt, title="[bold]📝 Event Log[/]", border_style="dim")

    # ===== MAIN RENDER =====

    def render(
        self,
        account:    dict,
        goal:       dict,
        analyses:   dict,
        positions:  list,
        trades:     list,
        start_time: datetime,
        dry_run:    bool = False,
        best_symbol:str = None,
    ):
        """Full dashboard render."""
        if not RICH_AVAILABLE:
            self._render_basic(account, goal, analyses, positions)
            return

        self.console.clear()
        self.console.print(self._render_header(goal, start_time, dry_run))

        # Row 1: Account + Goal
        self.console.print(
            Columns([
                self._render_account(account, goal),
                self._render_goal(goal),
            ])
        )

        # Row 2: Market analysis table
        self.console.print(self._render_market(analyses))

        # Row 3: Best opportunity detail
        if best_symbol and best_symbol in analyses:
            self.console.print(self._render_indicator_detail(best_symbol, analyses[best_symbol]))

        # Row 4: Positions + History
        self.console.print(
            Columns([
                self._render_positions(positions),
                self._render_history(trades),
            ])
        )

        # Row 5: Logs
        self.console.print(self._render_logs())

    # ===== FALLBACK: BASIC PRINT =====

    def _render_basic(self, account, goal, analyses, positions):
        os.system("cls" if os.name == "nt" else "clear")
        sep = "=" * 70
        print(sep)
        print(f"  MT5 TRADING BOT  |  Balance: ${account.get('balance',0):.2f}")
        print(f"  Profit: ${goal.get('total_profit',0):+.2f}  |  Progress: {goal.get('progress',0):.1f}%")
        print(sep)
        print(f"{'Symbol':<12} {'Price':>12} {'RSI':>6} {'Score':>8} {'Action':>8}")
        print("-" * 70)
        for sym, data in analyses.items():
            if data:
                print(
                    f"{sym:<12} {data.get('current_price',0):>12.5f} "
                    f"{data.get('indicators',{}).get('rsi',{}).get('value',0):>6.1f} "
                    f"{data.get('overall_score',0):>8.1f} "
                    f"{data.get('action','WAIT'):>8}"
                )
        print(sep)
        print(f"Open Positions: {len(positions)}")
        for p in positions:
            print(f"  {p['symbol']} {p['type']} {p['volume']} lots | P/L: ${p['profit']:+.2f}")
        print(sep)
        for ts, level, msg, _ in self.log_lines[-8:]:
            print(f"[{ts}] {level}: {msg}")
