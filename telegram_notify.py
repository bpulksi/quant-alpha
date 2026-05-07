"""
Telegram Bot Notification for Trading Signals
Setup:
  1. Message @BotFather on Telegram, /newbot, name it
  2. Copy the token to .env as TELEGRAM_BOT_TOKEN
  3. Message your bot once, then run: python telegram_notify.py setup
  4. It will find your chat_id and save to .env as TELEGRAM_CHAT_ID
"""
import os, sys, json, urllib.request, urllib.parse
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_message(text, parse_mode="Markdown"):
    if not BOT_TOKEN or not CHAT_ID:
        print("[!] Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
    }).encode()
    try:
        req = urllib.request.Request(url, data=data)
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if result.get("ok"):
            print("[OK] Telegram message sent")
            return True
        else:
            print(f"[!] Telegram error: {result}")
            return False
    except Exception as e:
        print(f"[!] Telegram send failed: {e}")
        return False

def get_chat_id():
    """Get chat ID from recent messages to the bot."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        if data.get("ok") and data.get("result"):
            for update in data["result"]:
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                username = chat.get("username", "unknown")
                print(f"  Found chat_id: {chat_id} (user: @{username})")
                return str(chat_id)
        print("  No messages found. Send any message to your bot first, then run this again.")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None

def format_scan_report(scan_results):
    """Format scan results into a Telegram message with buy/sell recommendations."""
    buys = []
    sells = []
    holds = []

    for r in scan_results:
        symbol = r.get("symbol", "?")
        price = r.get("price", 0)
        regime = r.get("regime", "?")
        action = r.get("signal", {}).get("action", "HOLD")
        confidence = r.get("signal", {}).get("confidence", 0)
        pred = r.get("predicted_return_pct", 0)
        reason = r.get("signal", {}).get("reason", "")

        entry = f"  `{symbol:12s}` ${price:>10,.2f} | {regime} | {pred:+.2f}%"

        if action == "BUY" and confidence > 0.5:
            buys.append((symbol, price, confidence, pred, reason))
        elif action == "SELL" and confidence > 0.5:
            sells.append((symbol, price, confidence, pred, reason))
        else:
            holds.append(entry)

    lines = ["*Trading Bot Scan Report*\n"]

    if buys:
        lines.append("*BUY Signals:*")
        for sym, price, conf, pred, reason in buys:
            lines.append(f"  `{sym}` @ ${price:,.2f} ({conf:.0%} conf, pred {pred:+.2f}%)")
            if reason: lines.append(f"    _{reason}_")

    if sells:
        lines.append("\n*SELL Signals:*")
        for sym, price, conf, pred, reason in sells:
            lines.append(f"  `{sym}` @ ${price:,.2f} ({conf:.0%} conf, pred {pred:+.2f}%)")
            if reason: lines.append(f"    _{reason}_")

    if not buys and not sells:
        lines.append("No actionable signals right now.")
        lines.append("\n*Top predicted movers:*")
        # Show top 5 by predicted return
        all_items = []
        for r in scan_results:
            all_items.append((r.get("symbol",""), r.get("price",0),
                            r.get("predicted_return_pct",0), r.get("regime","")))
        all_items.sort(key=lambda x: x[2], reverse=True)
        for sym, price, pred, regime in all_items[:5]:
            emoji = "+" if pred > 0 else ""
            lines.append(f"  `{sym:12s}` ${price:>10,.2f} | {regime} | {emoji}{pred:.2f}%")
        lines.append("\n*Worst predicted:*")
        for sym, price, pred, regime in all_items[-3:]:
            lines.append(f"  `{sym:12s}` ${price:>10,.2f} | {regime} | {pred:+.2f}%")

    from datetime import datetime
    lines.append(f"\n_Scan time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        print("=== Telegram Bot Setup ===")
        if not BOT_TOKEN:
            print("Set TELEGRAM_BOT_TOKEN in .env first!")
            print("Get one from @BotFather on Telegram")
            sys.exit(1)
        print("Looking for your chat ID...")
        chat_id = get_chat_id()
        if chat_id:
            print(f"\nAdd this to your .env file:")
            print(f"TELEGRAM_CHAT_ID={chat_id}")
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        send_message("*Test message from Trading Bot*\nTelegram integration working!")
    elif len(sys.argv) > 2 and sys.argv[1] == "send_file":
        # Read message from file (avoids shell quoting issues)
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            text = f.read()
        ok = send_message(text)
        import os; os.remove(sys.argv[2])
    else:
        print("Usage: python telegram_notify.py [setup|test|send_file <path>]")
