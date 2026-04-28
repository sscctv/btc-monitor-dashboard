#!/usr/bin/env python3
"""
OKX数据采集器 - V3.1 增强版（收割预警模块）
新增功能：
1. OI（未平仓合约量）+ 价格背离预警
2. 资金费率极端异常预警
3. 收割预警通知微信
"""
import sqlite3
import json
import time
import requests
import hashlib
import hmac
import base64
import warnings
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# 北京时区 (UTC+8)
BEIJING_OFFSET = timedelta(hours=8)

def get_beijing_time():
    return datetime.now(timezone.utc) + BEIJING_OFFSET

warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

API_KEY = "c72740a8-71ab-41ba-bef5-e7640e3efac9"
SECRET_KEY = "6E1EA8F850D168D5D47C8155A6460F06"
PASSPHRASE = "Jiege#@/123"
SYMBOL = "BTC-USDT-SWAP"
PROXY = {"http": "http://172.17.0.1:7890", "https": "http://172.17.0.1:7890"}
VERIFY_SSL = False
DB_FILE = "/tmp/okx_trading_v3.db"
ALERT_TARGET = "o9cq801cl6QXRfJWhroBxDriyjXA@im.wechat"

# ========== 账号配置 ==========
INITIAL_CAPITAL = 1000

LEVER_ACCOUNTS = {
    '1': {'leverage': 10, 'atr_mult_sl': 1.5, 'atr_mult_tp': 2.5, 'risk_percent': 0.02},
    '2': {'leverage': 15, 'atr_mult_sl': 1.2, 'atr_mult_tp': 2.0, 'risk_percent': 0.015},
    '3': {'leverage': 20, 'atr_mult_sl': 1.0, 'atr_mult_tp': 1.8, 'risk_percent': 0.01},
}

GRID_ACCOUNTS = {
    '4': {'leverage': 2, 'grid_count': 10, 'grid_range': 0.05, 'profit_per_grid': 0.005},
    '5': {'leverage': 3, 'grid_count': 15, 'grid_range': 0.08, 'profit_per_grid': 0.004},
}

ADX_THRESHOLD = 25
ADX_STRONG = 40

# ========== 收割预警配置 ==========
FUNDING_RATE_WARNING = 0.002   # 0.2%
FUNDING_RATE_DANGER = 0.005   # 0.5%
OI_CHANGE_WARNING = 0.20       # 20%
OI_HISTORY_HIGH = 0.90         # 历史90分位

# ========== GROQ 情绪分析配置 ==========
GROQ_API_KEY = "gsk_Lt2pJE1fK3MHyMKvEDXkF0p5"
GROQ_API_URL = "https://api.groq.com/v1/chat/completions"

positions = {**{k: None for k in LEVER_ACCOUNTS}, **{k: None for k in GRID_ACCOUNTS}}
account_capitals = {**{k: INITIAL_CAPITAL for k in LEVER_ACCOUNTS}, **{k: INITIAL_CAPITAL for k in GRID_ACCOUNTS}}

# 缓存资金费率历史
funding_rate_history = []
last_funding_alert_time = 0
last_oi_alert_time = 0
last_news_sentiment = None

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS market_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        price REAL, rsi REAL, macd REAL, signal REAL, atr REAL,
        cvd REAL, adx REAL, supertrend REAL, mode TEXT, trend TEXT,
        market_state TEXT, high24h REAL, low24h REAL,
        funding_rate REAL, oi REAL, oi_change REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT, action TEXT, side TEXT,
        entry REAL, exit_price REAL, pnl REAL,
        sl REAL, tp REAL, size INTEGER, leverage INTEGER,
        strategy TEXT, traded_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT, side TEXT, entry REAL, sl REAL, tp REAL, 
        size INTEGER, leverage INTEGER, strategy TEXT,
        grid_entry_price REAL, grid_count INTEGER, grid_profit REAL,
        opened_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY, balance REAL, trades INTEGER,
        wins INTEGER, losses REAL, strategy TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT, alert_type TEXT, message TEXT,
        price REAL, rsi REAL, cvd REAL, adx REAL, funding_rate REAL, oi_change REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS harvest_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type TEXT, message TEXT, price REAL,
        funding_rate REAL, oi REAL, oi_change REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def load_positions_from_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT p.account, p.side, p.entry, p.sl, p.tp, p.size, p.leverage, p.strategy,
               p.grid_entry_price, p.grid_count, p.grid_profit
        FROM positions p
        INNER JOIN (
            SELECT account, MAX(id) as max_id FROM positions GROUP BY account
        ) pm ON p.id = pm.max_id
    ''')
    for row in c.fetchall():
        acc_id = str(row[0])
        pos = {
            'side': row[1], 'entry': row[2], 'sl': row[3], 'tp': row[4],
            'size': row[5], 'leverage': row[6], 'strategy': row[7]
        }
        if row[7] == 'grid':
            pos['grid_entry_price'] = row[8]
            pos['grid_count'] = row[9]
            pos['grid_profit'] = row[10]
        positions[acc_id] = pos
    conn.close()

def make_sig(timestamp, method, path, body=''):
    message = timestamp + method + path + body
    mac = hmac.new(SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode('utf-8')

def get_server_time():
    r = requests.get('https://www.okx.com/api/v5/public/time', proxies=PROXY, timeout=10, verify=VERIFY_SSL)
    ts = int(json.loads(r.text)['data'][0]['ts'])
    return datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%dT%H:%M:%S.000Z')

def api_private(path):
    ts = get_server_time()
    headers = {
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': make_sig(ts, 'GET', path),
        'OK-ACCESS-TIMESTAMP': ts,
        'OK-ACCESS-PASSPHRASE': PASSPHRASE,
        'Content-Type': 'application/json'
    }
    r = requests.get('https://www.okx.com' + path, headers=headers, proxies=PROXY, timeout=10, verify=VERIFY_SSL)
    return json.loads(r.text)

def get_real_account_data():
    """获取真实账户数据"""
    try:
        result = api_private('/api/v5/account/balance')
        balance = {'total': 0, 'usdt': 0}
        if result.get('code') == '0' and result['data']:
            data = result['data'][0]
            balance['total'] = float(data.get('totalEq', 0))
            for detail in data.get('details', []):
                if detail.get('ccy') == 'USDT':
                    balance['usdt'] = float(detail.get('eq', 0))
        
        result2 = api_private('/api/v5/account/positions?instId=BTC-USDT-SWAP')
        position = None
        if result2.get('code') == '0' and result2['data']:
            pos = result2['data'][0]
            position = {
                'side': 'long' if pos['posSide'] == 'long' else 'short',
                'size': float(pos['pos']),
                'entry': float(pos.get('avgPx', 0)) if pos.get('avgPx') else 0,
                'upl': float(pos.get('upl', 0)) if pos.get('upl') else 0,
                'liq': float(pos.get('liqPx', 0)) if pos.get('liqPx') else 0,
                'leverage': int(pos.get('lever', 50))
            }
        return balance, position
    except Exception as e:
        print(f"Real account error: {e}")
        return {'total': 0, 'usdt': 0}, None

def calculate_adx(highs, lows, closes, period=14):
    """计算ADX趋势强度指标（修正版）"""
    if len(closes) < period + 1:
        return 0
    
    tr_list = []
    plus_dm = []
    minus_dm = []
    
    for i in range(1, len(closes)):
        high, low, prev_high, prev_low, prev_close = highs[i], lows[i], highs[i-1], lows[i-1], closes[i-1]
        
        # True Range
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
        
        # Directional Movement
        up_move = high - prev_high
        down_move = prev_low - low
        
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
    
    if len(tr_list) < period:
        return 0
    
    # 初始平滑 (使用简单均值)
    smoothed_tr = sum(tr_list[:period])
    smoothed_plus = sum(plus_dm[:period])
    smoothed_minus = sum(minus_dm[:period])
    
    # Wilder平滑
    for i in range(period, len(tr_list)):
        smoothed_tr = smoothed_tr - smoothed_tr / period + tr_list[i]
        smoothed_plus = smoothed_plus - smoothed_plus / period + plus_dm[i]
        smoothed_minus = smoothed_minus - smoothed_minus / period + minus_dm[i]
    
    if smoothed_tr == 0:
        return 0
    
    # +DI 和 -DI
    plus_di = (smoothed_plus / smoothed_tr) * 100
    minus_di = (smoothed_minus / smoothed_tr) * 100
    
    if plus_di + minus_di == 0:
        return 0
    
    # DX
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    
    # ADX是DX的Wilder平滑 (通常取9-14周期)
    # 这里简化处理，返回DX作为近似值（实际应用中应再平滑）
    adx_value = dx  # 简化版，正式应再做一次指数平滑
    
    return min(adx_value, 100)  # ADX最大100

def determine_market_state(adx, rsi, price_change_5m):
    if abs(price_change_5m) > 4:
        return 'extreme'
    if adx < ADX_THRESHOLD:
        return 'oscillation'
    if adx >= ADX_STRONG:
        return 'strong_trend'
    return 'trend'

def get_funding_rate_and_oi():
    """获取资金费率、订单簿和标记价格"""
    try:
        # 资金费率
        result = api_private('/api/v5/public/funding-rate?instId=BTC-USDT-SWAP')
        funding_rate = 0
        next_funding_time = None
        if result and result.get('data'):
            funding_rate = float(result['data'][0].get('fundingRate', 0))
            next_ts = result['data'][0].get('nextFundingTime')
            if next_ts:
                next_funding_time = int(next_ts) / 1000
        
        # 订单簿
        result = api_private('/api/v5/market/books?instId=BTC-USDT-SWAP&sz=10')
        bid_price, ask_price, bid_size, ask_size, spread = 0, 0, 0, 0, 0
        if result and result.get('data'):
            books = result['data'][0]
            asks = books.get('asks', [])
            bids = books.get('bids', [])
            if asks and bids:
                ask_price = float(asks[0][0])
                bid_price = float(bids[0][0])
                ask_size = sum(float(a[1]) for a in asks[:5])
                bid_size = sum(float(b[1]) for b in bids[:5])
                spread = ask_price - bid_price
        
        # OI：尝试用持仓量推算（合约数量 × 价格）
        oi = 0
        try:
            # 从账户持仓反推OI（如果有持仓的话）
            pos_result = api_private('/api/v5/account/positions?instId=BTC-USDT-SWAP')
            if pos_result.get('code') == '0' and pos_result['data']:
                for pos_data in pos_result['data']:
                    if float(pos_data.get('pos', 0)) > 0:
                        pos_usd = abs(float(pos_data.get('notionalUsd', 0)))
                        if pos_usd > 0:
                            oi = pos_usd
        except:
            pass
        
        return funding_rate, oi, bid_price, ask_price, bid_size, ask_size, spread, next_funding_time
    except Exception as e:
        print(f"Funding/API error: {e}")
        return 0, 0, 0, 0, 0, 0, 0, None


def analyze_news_sentiment():
    """使用 GROQ AI 分析加密市场情绪"""
    global last_news_sentiment
    try:
        # 从 Redis 获取最新新闻key
        import urllib.request
        req = urllib.request.Request(
            'http://127.0.0.1:8079/scan/200',
            headers={'Authorization': 'Bearer wm-local-token'}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            keys_data = json.loads(resp.read())
            all_keys = keys_data.get('result', [[], []])[1]
        
        # 收集新闻类key
        news_keys = [k for k in all_keys if 'news' in k.lower() or 'aviation' in k.lower() or 'economic' in k.lower()]
        if not news_keys:
            return None
        
        # 读取最新几条新闻内容
        news_items = []
        for key in news_keys[:3]:
            try:
                req2 = urllib.request.Request(
                    f'http://127.0.0.1:8079/get/{key}',
                    headers={'Authorization': 'Bearer wm-local-token'}
                )
                with urllib.request.urlopen(req2, timeout=5) as resp2:
                    content = json.loads(resp2.read()).get('result', {}).get('data', '')
                    if content and len(str(content)) > 50:
                        news_items.append(str(content)[:200])
            except:
                pass
        
        if not news_items:
            return None
        
        news_text = "\n".join(news_items)
        prompt = f"""你是加密货币市场分析师。请根据以下新闻判断当前市场情绪。

新闻内容：
{news_text}

请用JSON格式返回分析结果：
{{"情绪": "看多"/"看空"/"中性", "理由": "简要理由（20字内）", "对BTC影响": "利好"/"利空"/"中性"}}

只返回JSON，不要其他文字。"""
        
        payload = json.dumps({
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 200
        }).encode()
        
        req = urllib.request.Request(
            GROQ_API_URL,
            data=payload,
            headers={
                'Authorization': f'Bearer {GROQ_API_KEY}',
                'Content-Type': 'application/json'
            },
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            content = result['choices'][0]['message']['content'].strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
            sentiment = json.loads(content)
            last_news_sentiment = sentiment
            return sentiment
    except Exception as e:
        print(f"News sentiment error: {e}")
        return last_news_sentiment

def check_harvest_alerts(funding_rate, oi, price, price_change_5m, oi_history, next_funding_time=None, sentiment=None):
    """检查收割预警条件"""
    global last_funding_alert_time, last_oi_alert_time
    alerts = []
    now = time.time()
    
    # 1. 资金费率预警
    if abs(funding_rate) > FUNDING_RATE_DANGER:
        if now - last_funding_alert_time > 300:  # 5分钟内不重复
            alerts.append({
                'type': 'DANGER',
                'message': f"⚠️⚠️ 极端预警: 资金费率 {funding_rate*100:.2f}% (预期反向波动)",
                'action': '建议减仓观望'
            })
            last_funding_alert_time = now
    elif abs(funding_rate) > FUNDING_RATE_WARNING:
        if now - last_funding_alert_time > 600:  # 10分钟内不重复
            direction = '空头' if funding_rate > 0 else '多头'
            alerts.append({
                'type': 'WARNING',
                'message': f"⚠️ 资金费率预警: {funding_rate*100:.3f}% (主力可能布局{direction})",
                'action': '注意风向'
            })
            last_funding_alert_time = now
    
    # 2. OI横盘飙升预警
    if len(oi_history) >= 2:
        oi_change = (oi - oi_history[-2]) / oi_history[-2] if oi_history[-2] > 0 else 0
        if abs(price_change_5m) < 0.5 and abs(oi_change) > OI_CHANGE_WARNING:
            if now - last_oi_alert_time > 600:
                alerts.append({
                    'type': 'WARNING',
                    'message': f"⚠️ OI异动: 横盘时OI变化 {oi_change*100:.1f}% (多空双爆预警)",
                    'action': '减少隔夜高杠杆单'
                })
                last_oi_alert_time = now
    
    # 3. OI达到历史高位
    if len(oi_history) >= 20:
        sorted_oi = sorted(oi_history)
        high_threshold = sorted_oi[int(len(sorted_oi) * OI_HISTORY_HIGH)]
        if oi > high_threshold and high_threshold > 0:
            if now - last_oi_alert_time > 900:  # 15分钟
                alerts.append({
                    'type': 'WARNING',
                    'message': f"⚠️ OI历史高位: 当前OI超过90%历史数据",
                    'action': '市场杠杆过高，减少仓位'
                })
                last_oi_alert_time = now
    
    # 4. 价格+OI背离检测
    if len(oi_history) >= 5:
        recent_oi_change = (oi - oi_history[-5]) / oi_history[-5] if oi_history[-5] > 0 else 0
        price_change = price_change_5m
        
        if price_change > 0 and recent_oi_change < -0.05:
            alerts.append({
                'type': 'INFO',
                'message': f"📊 价格↑ + OI↓: 多头止盈离场，注意回调风险",
                'action': '顺势但谨慎'
            })
        elif price_change < 0 and recent_oi_change < -0.05:
            alerts.append({
                'type': 'INFO',
                'message': f"📊 价格↓ + OI↓: 空头止盈，注意反弹机会",
                'action': '观察企稳'
            })
    
    # 5. 新闻情绪预警（GROQ AI）
    if sentiment:
        btc_impact = sentiment.get('对BTC影响', '中性')
        emotion = sentiment.get('情绪', '中性')
        if btc_impact == '利空' and adx > 25:
            if now - last_funding_alert_time > 600:
                alerts.append({
                    'type': 'WARNING',
                    'message': f"🤖 GROQ情绪分析: {emotion} | {sentiment.get('理由', '')} → {btc_impact}",
                    'action': 'AI判断利空，顺势减仓'
                })
                last_funding_alert_time = now
        elif btc_impact == '利好' and adx > 25:
            if now - last_funding_alert_time > 600:
                alerts.append({
                    'type': 'INFO',
                    'message': f"🤖 GROQ情绪分析: {emotion} | {sentiment.get('理由', '')} → {btc_impact}",
                    'action': 'AI判断利好，顺势做多'
                })
                last_funding_alert_time = now
    
    return alerts

def send_wechat_alert(message):
    """发送微信告警"""
    try:
        result = subprocess.run([
            'openclaw', 'message', 'send',
            '--channel', 'openclaw-weixin',
            '--target', ALERT_TARGET,
            '--message', message,
            '--json'
        ], capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except Exception as e:
        print(f"Wechat alert failed: {e}")
        return False

def save_harvest_alert(alert_type, message, price, funding_rate, oi, oi_change):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO harvest_alerts (alert_type, message, price, funding_rate, oi, oi_change)
                 VALUES (?,?,?,?,?,?)''',
               (alert_type, message, price, funding_rate, oi, oi_change))
    conn.commit()
    conn.close()

def fetch_data():
    try:
        r = requests.get(f'https://www.okx.com/api/v5/market/candles?instId={SYMBOL}&bar=15m&limit=30', proxies=PROXY, timeout=8, verify=VERIFY_SSL)
        candles = r.json()
        if candles.get('code') != '0':
            return None
        
        data = []
        for k in candles['data']:
            data.append({
                'timestamp': int(k[0]),
                'open': float(k[1]), 'high': float(k[2]),
                'low': float(k[3]), 'close': float(k[4]),
                'volume': float(k[5])
            })
        
        closes = [d['close'] for d in data]
        highs = [d['high'] for d in data]
        lows = [d['low'] for d in data]
        
        # RSI
        if len(closes) >= 15:
            deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            gains = [d for d in deltas if d > 0]
            losses = [-d for d in deltas if d < 0]
            avg_gain = sum(gains[-14:]) / 14 if gains else 0
            avg_loss = sum(losses[-14:]) / 14 if losses else 0
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 50
        
        # MACD
        if len(closes) >= 26:
            ema_fast = sum(closes[-12:]) / 12
            ema_slow = sum(closes[-26:]) / 26
            macd = ema_fast - ema_slow
            signal = macd * 0.3
        else:
            macd, signal = 0, 0
        
        # ATR
        if len(data) >= 15:
            trs = []
            for i in range(1, min(len(data), 15)):
                tr = max(data[i]['high'] - data[i]['low'],
                         abs(data[i]['high'] - data[i-1]['close']),
                         abs(data[i]['low'] - data[i-1]['close']))
                trs.append(tr)
            atr = sum(trs) / len(trs) if trs else 0
        else:
            atr = 0
        
        # CVD
        r = requests.get(f'https://www.okx.com/api/v5/market/trades?instId={SYMBOL}&limit=100', proxies=PROXY, timeout=8, verify=VERIFY_SSL)
        cvd = sum(float(t['sz']) if t['side'] == 'buy' else -float(t['sz']) for t in r.json().get('data', [])[:100])
        
        # ADX
        adx = calculate_adx(highs, lows, closes, period=14)
        
        # 5分钟价格变化
        price_change_5m = ((closes[-1] - closes[-2]) / closes[-2]) * 100 if len(closes) >= 2 else 0
        
        # 市场状态
        market_state = determine_market_state(adx, rsi, price_change_5m)
        
        # 获取ticker
        r = requests.get(f'https://www.okx.com/api/v5/market/ticker?instId={SYMBOL}', proxies=PROXY, timeout=8, verify=VERIFY_SSL)
        ticker = r.json().get('data', [{}])[0] if r.json().get('data') else {}
        
        # 获取资金费率和订单簿
        funding_rate, oi, bid_price, ask_price, bid_size, ask_size, spread, next_funding_time = get_funding_rate_and_oi()
        
        # GROQ 情绪分析（每6分钟一次）
        sentiment = None
        if int(time.time()) % 360 < 10:  # 大约每6分钟
            sentiment = analyze_news_sentiment()
        
        # 信号生成
        mode = 'wait'
        trend = 'neutral'
        
        if market_state == 'extreme':
            mode, trend = 'wait', 'extreme'
        elif market_state == 'oscillation':
            if rsi < 30 and cvd < 0:
                mode, trend = 'short_pending', 'oscillation'
            elif rsi > 70 and cvd > 0:
                mode, trend = 'long_pending', 'oscillation'
            else:
                mode, trend = 'wait', 'oscillation'
        else:
            if adx >= ADX_THRESHOLD:
                if macd < signal and rsi < 40 and cvd < 0 and adx >= ADX_THRESHOLD:
                    mode, trend = 'short', 'bearish'
                elif macd > signal and rsi > 60 and cvd > 0 and adx >= ADX_THRESHOLD:
                    mode, trend = 'long', 'bullish'
                elif macd < signal and rsi < 50 and adx >= ADX_THRESHOLD:
                    mode, trend = 'short_pending', 'bearish'
                elif macd > signal and rsi > 50 and adx >= ADX_THRESHOLD:
                    mode, trend = 'long_pending', 'bullish'
            else:
                mode, trend = 'wait', 'neutral'
        
        return {
            'price': float(ticker.get('last', 0)),
            'rsi': rsi, 'macd': macd, 'signal': signal, 'atr': atr, 'cvd': cvd,
            'adx': adx, 'mode': mode, 'trend': trend,
            'market_state': market_state,
            'high24h': float(ticker.get('high24h', 0)),
            'low24h': float(ticker.get('low24h', 0)),
            'funding_rate': funding_rate,
            'oi': oi,
            'bid_price': bid_price,
            'ask_price': ask_price,
            'bid_size': bid_size,
            'ask_size': ask_size,
            'spread': spread,
            'price_change_5m': price_change_5m
        }
    except Exception as e:
        print(f"Error: {e}")
        return None

def check_trades(market):
    if not market or market['price'] == 0:
        return
    current = market['price']
    atr = market['atr']
    mode = market['mode']
    conn = sqlite3.connect(DB_FILE)
    
    for k, acc in LEVER_ACCOUNTS.items():
        pos = positions.get(k)
        if pos:
            entry, side, sl, tp, size = pos['entry'], pos['side'], pos['sl'], pos['tp'], pos['size']
            pnl = (entry - current) * size if side == 'short' else (current - entry) * size
            closed = False
            reason = ''
            if (side == 'short' and current >= sl) or (side == 'long' and current <= sl):
                closed, reason = True, '止损'
            elif (side == 'short' and current <= tp) or (side == 'long' and current >= tp):
                closed, reason = True, '止盈'
            if closed:
                account_capitals[k] += pnl
                c = conn.cursor()
                c.execute('''INSERT INTO trades (account, action, side, entry, exit_price, pnl, sl, tp, size, leverage, strategy)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                           (k, reason, side, entry, current, pnl, sl, tp, size, acc['leverage'], 'lever'))
                c.execute('DELETE FROM positions WHERE account=?', (k,))
                conn.commit()
                positions[k] = None
        else:
            if mode == 'short' or mode == 'long':
                side = 'short' if mode == 'short' else 'long'
                sl_dist = atr * acc['atr_mult_sl'] * (0.75 if market['market_state'] == 'extreme' else 1.0)
                tp_dist = atr * acc['atr_mult_tp']
                if side == 'short':
                    entry, sl, tp = current, current + sl_dist, current - tp_dist
                else:
                    entry, sl, tp = current, current - sl_dist, current + tp_dist
                risk_amount = account_capitals[k] * acc['risk_percent']
                risk_per_unit = atr * acc['atr_mult_sl'] * acc['leverage']
                size = max(1, int(risk_amount / risk_per_unit)) if risk_per_unit > 0 else 1
                positions[k] = {'side': side, 'entry': entry, 'sl': sl, 'tp': tp, 'size': size, 'leverage': acc['leverage'], 'strategy': 'lever'}
                c = conn.cursor()
                c.execute('''INSERT INTO positions (account, side, entry, sl, tp, size, leverage, strategy)
                             VALUES (?,?,?,?,?,?,?,?)''',
                           (k, side, entry, sl, tp, size, acc['leverage'], 'lever'))
                conn.commit()
    conn.close()

def save_market(market):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    beijing_time = get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''INSERT INTO market_data 
        (price, rsi, macd, signal, atr, cvd, adx, mode, trend, market_state, high24h, low24h, funding_rate, oi, oi_change, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
               (market['price'], market['rsi'], market['macd'], market['signal'], market['atr'], market['cvd'],
                market['adx'], market['mode'], market['trend'], market['market_state'], market['high24h'], market['low24h'],
                market.get('funding_rate', 0), market.get('oi', 0), market.get('price_change_5m', 0), beijing_time))
    conn.commit()
    conn.close()
    market['last_update'] = beijing_time
    sync_market_to_supabase(market)

def get_oi_history():
    """获取OI历史数据"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT oi FROM market_data WHERE oi > 0 ORDER BY id DESC LIMIT 30')
    oi_list = [row[0] for row in c.fetchall() if row[0]]
    conn.close()
    return list(reversed(oi_list))

def export_json(bid_price=0, ask_price=0, bid_size=0, ask_size=0, spread=0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''SELECT price, rsi, macd, signal, atr, cvd, adx, mode, trend, market_state, high24h, low24h, funding_rate, oi, created_at
                 FROM market_data ORDER BY id DESC LIMIT 1''')
    row = c.fetchone()
    
    if row:
        market = {
            'price': row[0], 'rsi': row[1], 'macd': row[2], 'signal': row[3], 'atr': row[4], 'cvd': row[5],
            'adx': row[6], 'mode': row[7], 'trend': row[8], 'market_state': row[9],
            'high24h': row[10], 'low24h': row[11], 'funding_rate': row[12], 'oi': row[13], 'last_update': row[14]
        }
    else:
        market = {'price': 0, 'rsi': 50, 'macd': 0, 'signal': 0, 'atr': 0, 'cvd': 0,
                  'adx': 0, 'mode': 'wait', 'trend': 'neutral', 'market_state': 'oscillation',
                  'high24h': 0, 'low24h': 0, 'funding_rate': 0, 'oi': 0, 'last_update': ''}
    
    # 添加订单簿数据
    market['bid_price'] = bid_price
    market['ask_price'] = ask_price
    market['bid_size'] = bid_size
    market['ask_size'] = ask_size
    market['spread'] = spread
    
    # 添加情绪数据
    market['sentiment'] = last_news_sentiment or {'情绪': '中性', '理由': '无数据', '对BTC影响': '中性'}
    
    accounts_data = {}
    for k in list(LEVER_ACCOUNTS.keys()) + list(GRID_ACCOUNTS.keys()):
        pos = positions.get(k)
        unreal = 0
        if pos and market['price'] > 0:
            if pos['side'] == 'short':
                unreal = (pos['entry'] - market['price']) * pos['size']
            else:
                unreal = (market['price'] - pos['entry']) * pos['size']
        accounts_data[k] = {
            'capital': account_capitals.get(k, INITIAL_CAPITAL),
            'position': pos,
            'unrealized': unreal
        }
    
    # 获取真实账户
    real_bal, real_pos = get_real_account_data()
    if real_pos:
        real_upl = real_pos.get('upl', 0)
    else:
        real_upl = 0
    accounts_data['Real'] = {
        'name': '真实账户',
        'capital': real_bal.get('total', 0),
        'position': real_pos,
        'unrealized': real_upl
    }
    
    conn.close()
    
    SIGNAL_MAP = {'wait': '等待信号', 'short': '做空信号 🔴', 'long': '做多信号 🟢', 'short_pending': '等待做空', 'long_pending': '等待做多'}
    MARKET_STATE_MAP = {'oscillation': '震荡 🔵', 'trend': '趋势 🟡', 'strong_trend': '强趋势 🟠', 'extreme': '极端 🔴'}
    
    data = {
        'market': market,
        'accounts': accounts_data,
        'signal_desc': SIGNAL_MAP.get(market['mode'], '等待信号'),
        'market_state_desc': MARKET_STATE_MAP.get(market.get('market_state', 'oscillation'), '震荡 🔵'),
        'harvest_warnings': [],
        'timestamp': get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    with open('/tmp/market_data.json', 'w') as f:
        json.dump(data, f, ensure_ascii=False)



def sync_market_to_supabase(market):
    """同步行情数据到 Supabase btcmarketdata 表"""
    try:
        sb = 'YOUR_SUPABASE_SECRET_HERE'
        BASE = 'https://lpcrnobolifrzwrkxoli.supabase.co/rest/v1'
        headers = {'apikey': sb, 'Authorization': f'Bearer {sb}', 'Content-Type': 'application/json', 'Prefer': 'return=representation'}
        
        record = {
            'price': market.get('price', 0),
            'rsi': market.get('rsi', 0),
            'macd': market.get('macd', 0),
            'signal_line': market.get('signal', 0),
            'atr': market.get('atr', 0),
            'cvd': market.get('cvd', 0),
            'adx': market.get('adx', 0),
            'trend': market.get('trend', ''),
            'market_state': market.get('market_state', ''),
            'high24h': market.get('high24h', 0),
            'low24h': market.get('low24h', 0),
            'funding_rate': market.get('funding_rate', 0),
            'bid_price': market.get('bid_price', 0),
            'ask_price': market.get('ask_price', 0),
            'bid_size': market.get('bid_size', 0),
            'ask_size': market.get('ask_size', 0),
            'spread': market.get('spread', 0),
        }
        
        req = urllib.request.Request(
            f'{BASE}/btcmarketdata',
            data=json.dumps(record).encode(),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5):
            pass  # 静默写入，不阻塞主流程
    except Exception as e:
        print(f"Supabase sync error (non-blocking): {e}")


if __name__ == '__main__':
    init_db()
    load_positions_from_db()
    print("=" * 60)
    print("OKX 数据采集器 V3.1 (收割预警模块)")
    print("=" * 60)
    print("新增功能: OI背离 + 资金费率预警 + 收割预警")
    print("-" * 60)
    
    oi_history = get_oi_history()
    
    while True:
        try:
            market = fetch_data()
            if market:
                market['last_update'] = get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')
                save_market(market)
                
                # 更新OI历史
                if market['oi'] > 0:
                    oi_history.append(market['oi'])
                    if len(oi_history) > 30:
                        oi_history.pop(0)
                
                check_trades(market)
                
                # 收割预警检查
                alerts = check_harvest_alerts(
                    market.get('funding_rate', 0),
                    market.get('oi', 0),
                    market['price'],
                    market.get('price_change_5m', 0),
                    oi_history,
                    market.get('next_funding_time'),
                    market.get('sentiment')
                )
                
                for alert in alerts:
                    print(f"\n🚨 [{alert['type']}] {alert['message']}")
                    print(f"   操作建议: {alert['action']}")
                    send_wechat_alert(f"{alert['message']}\n建议: {alert['action']}")
                    save_harvest_alert(alert['type'], alert['message'], market['price'],
                                     market.get('funding_rate', 0), market.get('oi', 0),
                                     market.get('price_change_5m', 0))
                
                export_json(
                    market.get('bid_price', 0),
                    market.get('ask_price', 0),
                    market.get('bid_size', 0),
                    market.get('ask_size', 0),
                    market.get('spread', 0)
                )
                
                STATE_EMOJI = {'oscillation': '🔵', 'trend': '🟡', 'strong_trend': '🟠', 'extreme': '🔴'}
                state_emoji = STATE_EMOJI.get(market.get('market_state', 'oscillation'), '🔵')
                SIGNAL_MAP = {'wait': '等待', 'short': '做空', 'long': '做多', 'short_pending': '等做空', 'long_pending': '等做多'}
                fr = market.get('funding_rate', 0)
                sent = market.get('sentiment', {})
                sent_str = f" | AI:{sent.get('对BTC影响','-')}" if sent else ''
                print(f"[{market['last_update']}] ${market['price']:,.0f} RSI:{market['rsi']:.0f} ADX:{market['adx']:.0f} {state_emoji}{market.get('market_state', 'oscillation')} | {SIGNAL_MAP.get(market['mode'], '?')} | 资金:{fr*100:.4f}%{sent_str}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")
        
        time.sleep(5)