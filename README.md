# 🤖 MT5 Auto-Trading Bot — traddeeer v1

بوت تداول آلي متكامل لمنصة MetaTrader 5 مع لوحة تحكم ويب احترافية.

---

## 🚀 المميزات

- **4 استراتيجيات** للتداول الآلي (Scalping, Swing, Breakout, Smart Money)
- **19 مؤشر فني** (RSI, MACD, Bollinger, ATR, ADX, Aroon, OBV, Donchian, Heiken Ashi, Patterns, وغيرها)
- **إدارة مخاطر ذكية**: ATR sizing, 1:2 R:R, drawdown stop
- **نظام أهداف**: هدف يومي، حماية رأس المال، trailing stop تلقائي
- **لوحة تحكم ويب** (Flask) على المنفذ 8050
- **3 تبويبات**: التحليل الفني | لوحة البوت | الأهداف والمراكز المفتوحة

---

## 📁 هيكل الملفات

```
├── config.py              # الإعدادات والرموز والأطر الزمنية
├── indicators.py          # 19 مؤشر فني
├── strategy.py            # 4 استراتيجيات مع Confidence %
├── risk_manager.py        # إدارة المخاطر وحجم اللوت
├── mt5_connector.py       # الاتصال بـ MT5
├── dashboard_service.py   # خدمة البيانات + خيط البوت الآلي
├── web_server.py          # Flask API + Static files
├── dashboard.html         # واجهة المستخدم
├── trading_bot.py         # CLI bot loop
├── Start_Dashboard.bat    # تشغيل لوحة التحكم
├── Start_Bot.bat          # تشغيل البوت CLI
└── Start_DryRun.bat       # تشغيل تجريبي
```

---

## ⚡ التشغيل السريع

1. **تثبيت المتطلبات:**
   ```bash
   pip install MetaTrader5 flask pandas ta numpy
   ```

2. **تشغيل لوحة التحكم:**
   ```
   Start_Dashboard.bat
   ```
   ثم افتح: [http://localhost:8050](http://localhost:8050)

3. **أو تشغيل البوت CLI:**
   ```
   Start_Bot.bat
   ```

---

## ⚙️ الإعدادات الرئيسية (`config.py`)

| المتغير | القيمة الافتراضية | الوصف |
|---------|------------------|-------|
| `SYMBOLS` | XAUUSDm, BTCUSDm, ETHUSDm | الرموز المتداولة |
| `GOAL_TARGET` | 20$ | هدف الربح |
| `MAX_LOSS` | 10$ | أقصى خسارة |
| `DAILY_GOAL` | 5$ | الهدف اليومي |
| `RISK_PER_TRADE` | 1% | المخاطرة لكل صفقة |

---

## 🏦 المتطلبات

- Python 3.9+
- MetaTrader 5 (Exness أو أي وسيط)
- حساب demo أو real

---

## 📌 الإصدار الحالي

**v1** — النسخة الأولى الكاملة مع لوحة التحكم والبوت الآلي المتكامل.

---

> ⚠️ **تنبيه**: هذا البوت للأغراض التعليمية. التداول ينطوي على مخاطر. استخدم حساب تجريبي أولاً.
