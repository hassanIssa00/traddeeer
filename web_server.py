"""
Trading Bot Web Server
سيرفر الويب التفاعلي لمتابعة الشارت والمؤشرات وتشغيل البوت الآلي
"""

import json
import logging
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import dashboard_service as ds

ROOT = Path(__file__).parent
HTML_PATH = ROOT / "dashboard.html"

PORT = 8050

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("web_server")


class TradingBotHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html_text: str):
        body = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            if HTML_PATH.exists():
                self._send_html(200, HTML_PATH.read_text(encoding="utf-8"))
            else:
                self._send_json(500, {"success": False, "error": "ملف dashboard.html غير موجود"})
            return

        elif path == "/api/status":
            goal_acc = ds.get_goal_and_account_status()
            self._send_json(200 if goal_acc.get("success") else 500, goal_acc)
            return

        elif path == "/api/analysis":
            sym = str(query.get("symbol", ["XAUUSDm"])[0])
            tf = str(query.get("timeframe", ["H1"])[0])
            data = ds.analyze_symbol(sym, tf)
            self._send_json(200 if data.get("success") else 500, data)
            return

        elif path == "/api/goal":
            data = ds.get_goal_and_account_status()
            self._send_json(200 if data.get("success") else 500, data)
            return

        elif path == "/api/bot/status":
            data = ds.get_bot_status()
            self._send_json(200, data)
            return

        else:
            self._send_json(404, {"success": False, "error": "الصفحة أو المسار غير موجود"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            body = json.loads(raw_body)
        except Exception as e:
            self._send_json(400, {"success": False, "error": f"JSON غير صالح: {e}"})
            return

        if path == "/api/order":
            sym = str(body.get("symbol", "XAUUSDm"))
            action = str(body.get("action", "BUY"))
            lot = float(body.get("lot", 0.01))
            sl = float(body.get("sl", 0.0))
            tp = float(body.get("tp", 0.0))
            res = ds.execute_order(sym, action, lot, sl, tp)
            self._send_json(200 if res.get("success") else 400, res)

        elif path == "/api/close":
            ticket = body.get("ticket")
            close_all = body.get("close_all", False)
            if close_all:
                res = ds.close_all_positions()
            else:
                res = ds.close_position(int(ticket))
            self._send_json(200 if res.get("success") else 400, res)

        elif path == "/api/update-goal":
            if "target_profit_usd" in body:
                ds.GOAL_STATE["target_profit_usd"] = float(body["target_profit_usd"])
            if "max_loss_usd" in body:
                ds.GOAL_STATE["max_loss_usd"] = float(body["max_loss_usd"])
            if "daily_target_usd" in body:
                ds.GOAL_STATE["daily_target_usd"] = float(body["daily_target_usd"])
            ds.save_goal_state(ds.GOAL_STATE)
            self._send_json(200, {"success": True, "goal": ds.GOAL_STATE})

        elif path == "/api/bot/start":
            res = ds.start_bot()
            self._send_json(200, res)

        elif path == "/api/bot/stop":
            res = ds.stop_bot()
            self._send_json(200, res)

        elif path == "/api/bot/config":
            res = ds.update_bot_config(body)
            self._send_json(200, res)

        elif path == "/api/bot/test-trade":
            sym = str(body.get("symbol", "XAUUSDm"))
            act = str(body.get("action", "BUY"))
            res = ds.execute_test_trade(sym, act)
            self._send_json(200 if res.get("success") else 400, res)

        else:
            self._send_json(404, {"success": False, "error": "المسار غير موجود"})

    def log_message(self, format, *args):
        pass  # Suppress default noisy console logs


def run_server(port=PORT, open_browser=False):
    print("=" * 60)
    print("  🤖 MT5 Trading Bot - Web Dashboard & Auto-Trader")
    print(f"  🌐 Listening at: http://127.0.0.1:{port}/")
    print("=" * 60)

    server = ThreadingHTTPServer(("0.0.0.0", port), TradingBotHandler)

    if open_browser:
        def _open():
            time.sleep(1.2)
            webbrowser.open(f"http://127.0.0.1:{port}/")
        threading.Thread(target=_open, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    p = PORT
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        p = int(sys.argv[1])
    run_server(port=p)
