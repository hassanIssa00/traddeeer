"""
=============================================================
  Trading Bot - Main Engine
  المحرك الرئيسي للبوت
=============================================================
  Usage:
    python trading_bot.py                        # Default run
    python trading_bot.py --goal 20              # $20 profit target
    python trading_bot.py --goal-pct 20          # 20% profit target
    python trading_bot.py --dry-run              # Analyze only, no trades
    python trading_bot.py --risk 1.5             # 1.5% risk per trade
    python trading_bot.py --symbols EURUSD,GOLD  # Custom symbols
    python trading_bot.py --interval 30          # Scan every 30 seconds
=============================================================
"""
import argparse
import json
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

# ===== LOCAL IMPORTS =====
from config import GOAL, TRADING, LOG
import mt5_connector as mt5c
import indicators as ind_engine
import strategy as strat_engine
import risk_manager as rm
from dashboard import Dashboard

# ===== LOGGING SETUP =====

def setup_logging(log_dir: str = "logs") -> logging.Logger:
    Path(log_dir).mkdir(exist_ok=True)
    today    = date.today().strftime("%Y%m%d")
    log_file = os.path.join(log_dir, f"{LOG['file_prefix']}_{today}.log")

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG["level"], logging.INFO))

    # File handler (rotating)
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=LOG["max_bytes"],
        backupCount=LOG["backup_count"],
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    # Console handler (errors only - dashboard handles display)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.ERROR)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(ch)

    return logging.getLogger(__name__)


# ===== STATE PERSISTENCE =====

STATE_FILE = "bot_state.json"

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logging.getLogger(__name__).error(f"Could not save state: {e}")


# ===== ARGUMENT PARSING =====

def parse_args():
    parser = argparse.ArgumentParser(
        description="MT5 Trading Bot - بوت التداول الآلي",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--goal",      type=float, help="Profit target in USD (e.g. 20)")
    parser.add_argument("--goal-pct",  type=float, help="Profit target as percentage (e.g. 20)")
    parser.add_argument("--dry-run",   action="store_true", help="Analyze only - no trades")
    parser.add_argument("--risk",      type=float, help="Risk per trade in %% (e.g. 1.5)")
    parser.add_argument("--symbols",   type=str,   help="Comma-separated symbols (e.g. EURUSDm,XAUUSDm)")
    parser.add_argument("--interval",  type=int,   help="Scan interval in seconds (default 60)")
    parser.add_argument("--max-pos",   type=int,   help="Max open positions (default 3)")
    parser.add_argument("--close-all", action="store_true", help="Close all open positions and exit")
    return parser.parse_args()


# ===== MAIN BOT CLASS =====

class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self, args):
        self.args       = args
        self.dry_run    = args.dry_run
        self.logger     = logging.getLogger(self.__class__.__name__)
        self.dashboard  = Dashboard()
        self.start_time = datetime.now()

        # Apply arg overrides to config
        if args.goal:        GOAL["target_profit_usd"] = args.goal
        if args.goal_pct:    GOAL["target_profit_pct"] = args.goal_pct
        if args.risk:        TRADING["risk_per_trade_pct"] = args.risk
        if args.interval:    TRADING["scan_interval_sec"] = args.interval
        if args.max_pos:     TRADING["max_positions"] = args.max_pos
        if args.symbols:
            TRADING["symbols"] = [s.strip() for s in args.symbols.split(",")]

        # State
        state              = load_state()
        self.start_balance = state.get("start_balance", None)
        self.daily_start   = state.get("daily_start_balance", None)
        self.last_day      = state.get("last_day", str(date.today()))
        self.trade_count   = state.get("trade_count", 0)
        self.total_profit  = state.get("total_profit", 0.0)

        # Runtime data
        self.analyses:   dict = {}
        self.positions:  list = []
        self.trades:     list = []
        self.account:    dict = {}
        self.symbols:    list = []
        self.goal_status:dict = {}
        self.daily_profit: float = 0.0
        self.best_symbol: str = None

    # ===== INITIALIZATION =====

    def initialize(self) -> bool:
        """Connect to MT5 and validate symbols."""
        self.dashboard.add_log("Connecting to MetaTrader 5...", "INFO")

        if not mt5c.connect():
            self.dashboard.add_log("❌ Failed to connect to MT5!", "ERROR")
            return False

        self.account = mt5c.get_account_info()
        if not self.account:
            self.dashboard.add_log("❌ Failed to get account info!", "ERROR")
            return False

        # Initialize start balance
        if self.start_balance is None:
            self.start_balance = self.account["balance"]
            self.logger.info(f"Start balance set: ${self.start_balance:.2f}")

        # Initialize daily balance
        today_str = str(date.today())
        if self.daily_start is None or self.last_day != today_str:
            self.daily_start = self.account["balance"]
            self.last_day    = today_str
            self.logger.info(f"Daily start balance: ${self.daily_start:.2f}")

        # Validate and filter symbols
        self.symbols = mt5c.check_symbols(TRADING["symbols"])
        if not self.symbols:
            self.dashboard.add_log("❌ No valid symbols found!", "ERROR")
            return False

        self.dashboard.add_log(
            f"✅ Connected | Account: #{self.account['login']} | "
            f"Balance: ${self.account['balance']:.2f} | Symbols: {', '.join(self.symbols)}",
            "SUCCESS"
        )
        return True

    # ===== MAIN LOOP STEPS =====

    def update_account(self):
        """Refresh account and position data."""
        self.account   = mt5c.get_account_info()
        self.positions = mt5c.get_open_positions(magic=TRADING["magic_number"])
        self.trades    = mt5c.get_trade_history(days=7)
        self.daily_profit = self.account.get("balance", 0) - (self.daily_start or 0)

    def check_goal(self) -> str:
        """Check goal status and return status string."""
        self.goal_status = rm.check_goal_status(
            self.account,
            self.start_balance,
            self.daily_profit,
        )
        status = self.goal_status.get("status", "ACTIVE")

        if status == "GOAL_ACHIEVED":
            self.dashboard.add_log(
                f"🎉 GOAL ACHIEVED! Profit=${self.goal_status['total_profit']:.2f} "
                f"({self.goal_status['total_profit_pct']:.1f}%)", "SUCCESS"
            )
        elif status == "STOP_LOSS":
            self.dashboard.add_log(
                f"🛑 MAX LOSS HIT! Loss=${self.goal_status['total_profit']:.2f}", "ERROR"
            )
        elif status == "DAILY_LIMIT":
            self.dashboard.add_log(
                f"⚠️ Daily loss limit reached: ${self.daily_profit:.2f}", "WARN"
            )
        return status

    def analyze_markets(self):
        """Run technical analysis on all symbols."""
        best_score = 0
        self.best_symbol = None

        for symbol in self.symbols:
            try:
                # Get H1 data (primary)
                df_h1 = mt5c.get_ohlcv(symbol, TRADING["primary_timeframe"], bars=500)
                if df_h1 is None or len(df_h1) < 210:
                    self.logger.warning(f"Insufficient H1 data for {symbol}")
                    continue

                analysis = ind_engine.analyze(df_h1)
                self.analyses[symbol] = analysis

                score = abs(analysis.get("overall_score", 0))
                if score > best_score and analysis.get("action") != "WAIT":
                    best_score     = score
                    self.best_symbol = symbol

                self.logger.debug(
                    f"{symbol}: score={analysis['overall_score']:.1f} "
                    f"conf={analysis['confidence']:.0f}% action={analysis['action']}"
                )

            except Exception as e:
                self.logger.error(f"Analysis error for {symbol}: {e}")
                self.analyses[symbol] = None

    def check_and_trade(self):
        """Run strategy engine and execute trades."""
        # Check if trading is allowed
        can_trade, reason = rm.should_trade(
            self.account, self.positions, self.daily_profit, self.start_balance
        )

        if not can_trade:
            self.logger.info(f"Trading blocked: {reason}")
            self.dashboard.add_log(f"⛔ {reason}", "WARN")
            return

        for symbol in self.symbols:
            analysis = self.analyses.get(symbol)
            if not analysis or analysis.get("action") == "WAIT":
                continue

            # Get symbol info
            sym_info = mt5c.get_symbol_info(symbol)
            if sym_info is None:
                continue

            # Get M15 data for entry timing
            df_entry = mt5c.get_ohlcv(symbol, TRADING["entry_timeframe"], bars=200)
            if df_entry is None:
                df_entry = mt5c.get_ohlcv(symbol, TRADING["primary_timeframe"], bars=500)

            # Run strategy engine
            signal = strat_engine.get_signal(
                symbol,
                df_entry if df_entry is not None else mt5c.get_ohlcv(symbol, "H1", 500),
                analysis["indicators"],
                sym_info,
            )

            if signal["action"] == "WAIT":
                continue

            # Check if already have position in this symbol
            sym_positions = [p for p in self.positions if p["symbol"] == symbol]
            if sym_positions:
                self.logger.debug(f"Already have position in {symbol}, skipping")
                continue

            # Double-check overall capacity
            can_trade2, reason2 = rm.should_trade(
                self.account, self.positions, self.daily_profit, self.start_balance
            )
            if not can_trade2:
                break

            # Calculate SL/TP from strategy
            entry = signal["entry"]
            sl    = signal["sl"]
            tp    = signal["tp"]

            # Fallback: use ATR-based SL/TP if strategy didn't set them
            atr = analysis["indicators"].get("atr", {}).get("value", entry * 0.001) or entry * 0.001
            if sl == 0 or tp == 0:
                sl, tp = rm.calculate_sl_tp(sym_info, signal["action"], entry, atr)

            # Calculate lot size
            sl_dist = abs(entry - sl)
            lot = rm.calculate_lot_size(
                sym_info,
                self.account["balance"],
                sl_dist,
                TRADING["risk_per_trade_pct"],
            )

            log_msg = (
                f"🔔 {signal['action']} {symbol} | Strategy: {signal['strategy']} | "
                f"Conf: {signal['confidence']:.0f}% | Lot: {lot} | "
                f"Entry: {entry:.5f} | SL: {sl:.5f} | TP: {tp:.5f}"
            )
            self.logger.info(log_msg)
            self.dashboard.add_log(log_msg, signal["action"])

            if self.dry_run:
                self.dashboard.add_log(f"[DRY RUN] Would place: {signal['action']} {lot} {symbol}", "WARN")
                continue

            # Execute trade
            result = mt5c.place_order(
                symbol     = symbol,
                order_type = signal["action"],
                lot        = lot,
                sl         = sl,
                tp         = tp,
                comment    = f"{signal['strategy'][:8]}_{signal['confidence']:.0f}%",
                magic      = TRADING["magic_number"],
            )

            if result["success"]:
                self.trade_count += 1
                self.dashboard.add_log(
                    f"✅ Trade placed! Ticket #{result['ticket']} | "
                    f"{signal['action']} {lot} {symbol} @ {result['price']:.5f}",
                    "SUCCESS"
                )
            else:
                self.dashboard.add_log(
                    f"❌ Order failed: {result.get('error','?')} | {symbol}",
                    "ERROR"
                )

    def manage_positions(self):
        """Apply trailing stops and manage open positions."""
        for pos in self.positions:
            try:
                symbol   = pos["symbol"]
                analysis = self.analyses.get(symbol)
                if not analysis:
                    continue

                sym_info = mt5c.get_symbol_info(symbol)
                if not sym_info:
                    continue

                atr = analysis["indicators"].get("atr", {}).get("value") or 0

                # Trailing stop
                new_sl = rm.apply_trailing_stop(pos, sym_info, atr, trail_multiplier=1.2)
                if new_sl and not self.dry_run:
                    if mt5c.modify_sl_tp(pos["ticket"], new_sl, pos["tp"]):
                        self.dashboard.add_log(
                            f"📍 Trailing stop moved: {symbol} ticket#{pos['ticket']} SL→{new_sl:.5f}",
                            "INFO"
                        )

                # Check reversal signal vs open position
                action = analysis.get("action", "WAIT")
                confidence = analysis.get("confidence", 0)
                if (pos["type"] == "BUY" and action == "SELL" and confidence > 75 and
                        pos["profit"] > 0):
                    self.dashboard.add_log(
                        f"↩️ Closing {pos['symbol']} BUY (reversal signal) P/L=${pos['profit']:.2f}",
                        "WARN"
                    )
                    if not self.dry_run:
                        mt5c.close_position(pos["ticket"])

                elif (pos["type"] == "SELL" and action == "BUY" and confidence > 75 and
                      pos["profit"] > 0):
                    self.dashboard.add_log(
                        f"↩️ Closing {pos['symbol']} SELL (reversal signal) P/L=${pos['profit']:.2f}",
                        "WARN"
                    )
                    if not self.dry_run:
                        mt5c.close_position(pos["ticket"])

            except Exception as e:
                self.logger.error(f"Position management error for {pos.get('symbol','?')}: {e}")

    def save_current_state(self):
        """Persist bot state to disk."""
        save_state({
            "start_balance":       self.start_balance,
            "daily_start_balance": self.daily_start,
            "last_day":            self.last_day,
            "trade_count":         self.trade_count,
            "total_profit":        self.goal_status.get("total_profit", 0),
            "last_updated":        str(datetime.now()),
            "goal_status":         self.goal_status.get("status", "ACTIVE"),
        })

    # ===== MAIN RUN LOOP =====

    def run(self):
        """Main bot loop."""
        self.logger.info("=" * 60)
        self.logger.info("  Trading Bot Starting")
        self.logger.info(f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.logger.info(f"  Goal: ${GOAL['target_profit_usd']:.2f}")
        self.logger.info(f"  Symbols: {TRADING['symbols']}")
        self.logger.info("=" * 60)

        if not self.initialize():
            print("❌ Initialization failed. Check MT5 connection.")
            return

        scan_interval = TRADING["scan_interval_sec"]
        cycle = 0

        while True:
            try:
                cycle += 1
                self.logger.debug(f"Cycle #{cycle} started")

                # 1. Update data
                self.update_account()

                # 2. Check goal
                goal_status = self.check_goal()

                # 3. Run analysis
                self.analyze_markets()

                # 4. Trade (if not stopped)
                if goal_status == "ACTIVE":
                    self.check_and_trade()

                # 5. Manage open positions
                self.manage_positions()

                # 6. Update dashboard
                goal_data = dict(self.goal_status)
                goal_data["daily_target_usd"] = GOAL["daily_target_usd"]
                self.dashboard.render(
                    account     = self.account,
                    goal        = goal_data,
                    analyses    = self.analyses,
                    positions   = self.positions,
                    trades      = self.trades,
                    start_time  = self.start_time,
                    dry_run     = self.dry_run,
                    best_symbol = self.best_symbol,
                )

                # 7. Save state
                self.save_current_state()

                # 8. Countdown
                self.dashboard.add_log(
                    f"Cycle #{cycle} done | Next scan in {scan_interval}s | "
                    f"Trades: {self.trade_count} | Positions: {len(self.positions)}",
                    "INFO"
                )

                # Sleep with reconnect check
                for i in range(scan_interval):
                    time.sleep(1)
                    if i == scan_interval - 5 and not mt5c.is_connected():
                        self.logger.warning("MT5 disconnected, reconnecting...")
                        mt5c.connect()

            except KeyboardInterrupt:
                print("\n\n⏹️  Bot stopped by user (Ctrl+C)")
                self.logger.info("Bot stopped by user")
                break

            except Exception as e:
                self.logger.error(f"Main loop error: {e}", exc_info=True)
                self.dashboard.add_log(f"❌ Error: {e}", "ERROR")
                time.sleep(10)

        # Cleanup
        mt5c.disconnect()
        self.save_current_state()
        print(f"\nFinal P/L: ${self.goal_status.get('total_profit', 0):.2f}")
        print(f"Total trades: {self.trade_count}")


# ===== ENTRY POINT =====

def main():
    args   = parse_args()
    logger = setup_logging()

    # Print banner
    print("""
╔══════════════════════════════════════════════════════╗
║           🤖 MT5 AUTOMATED TRADING BOT 🤖            ║
║          بوت التداول الآلي - MetaTrader 5             ║
╠══════════════════════════════════════════════════════╣
║  Strategies: Trend / Mean Reversion / Breakout       ║
║              MACD Divergence                          ║
║  Indicators: RSI, MACD, EMA, BB, ATR, ADX,           ║
║              Stochastic, CCI, Williams%R, MFI,        ║
║              Ichimoku, Donchian, Keltner, OBV,        ║
║              Aroon, Patterns, S/R Levels              ║
╚══════════════════════════════════════════════════════╝
""")

    # Close all and exit
    if args.close_all:
        if mt5c.connect():
            n = mt5c.close_all_positions()
            print(f"Closed {n} positions")
            mt5c.disconnect()
        return

    mode = "DRY RUN (no trades)" if args.dry_run else "LIVE TRADING"
    goal = args.goal or GOAL["target_profit_usd"]
    print(f"Mode   : {mode}")
    print(f"Goal   : ${goal:.2f} profit target")
    print(f"Risk   : {args.risk or TRADING['risk_per_trade_pct']:.1f}% per trade")
    print(f"Symbols: {args.symbols or ', '.join(TRADING['symbols'])}")
    print("\nStarting in 3 seconds... (Ctrl+C to cancel)")
    time.sleep(3)

    bot = TradingBot(args)
    bot.run()


if __name__ == "__main__":
    main()
