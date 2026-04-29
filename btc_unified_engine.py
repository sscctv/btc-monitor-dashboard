#!/usr/bin/env python3
"""
BTC 统一监控引擎 v2.0
====================================
- 读取 OKX 数据库（okx schema）
- 计算综合信号
- 记录到本地 btc schema
- 同步到云端 Supabase
- 支持真实账户数据
- 写入 market_data.json 供现有监控脚本使用
"""

import os
import json
import time
import hashlib
import hmac
import base64
import requests
import urllib.request
import warnings
from datetime import datetime, timezone
from collections import deque
import psycopg2
from psycopg2.extras import RealDictCursor

warnings.filterwarnings('ignore')

# === PostgreSQL 配置 ===
PG_HOST = '192.168.1.2'
PG_PORT = '5432'
PG_USER = 'postgres'
PG_PASSWORD = 'Postgres@2026'
PG_DB = 'postgres'

# === Supabase 配置 ===
SB_KEY = os.getenv('SB_SECRET_KEY', '')
SB_BASE = 'https://lpcrnobolifrzwrkxoli.supabase.co/rest/v1'

# === OKX API 配置 ===
OKX_KEY = 'c72740a8-71ab-41ba-bef5-e7640e3efac9'
OKX_SECRET = '6E1EA8F850D168D5D47C8155A6460F06'
OKX_PASS = 'Jiege#@/123'
OKX_PROXY = {'http': 'http://172.17.0.1:7890', 'https': 'http://172.17.0.1:7890'}

INST_ID = 'BTC-USDT-SWAP'

# === 信号参数 ===
DEPTH_BUY = 2.0
DEPTH_SELL = 0.5
BIG_CONFIRM = 3
FUNDING_THR = 0.0001
ADX_WEAK = 20
ADX_STRONG = 30

# === 微信通知目标 ===
TARGET = 'o9cq801cl6QXRfJWhroBxDriyjXA@im.wechat'


def pg_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname=PG_DB,
        connect_timeout=5, cursor_factory=RealDictCursor
    )


def okx_sig(ts, method, path, body=''):
    msg = str(ts) + method + path + body
    mac = hmac.new(OKX_SECRET.encode(), msg.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def okx_server_time():
    try:
        r = requests.get('https://www.okx.com/api/v5/public/time', proxies=OKX_PROXY, timeout=10, verify=False)
        ts = json.loads(r.text)['data'][0]['ts']
        return datetime.utcfromtimestamp(int(ts) / 1000).strftime('%Y-%m-%dT%H:%M:%S.') + str(ts)[-3:] + 'Z'
    except:
        return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.') + 'Z'


# ============ 数据采集 ============

def fetch_okx_public(conn):
    """从 okx schema 获取市场数据"""
    with conn.cursor() as cur:
        # 最新盘口
        cur.execute("""
            SELECT ts, depth_ratio_5, depth_ratio_50, spread
            FROM okx.order_book_summary WHERE inst_id=%s ORDER BY ts DESC LIMIT 1
        """, (INST_ID,))
        depth = cur.fetchone()

        # 大单流向（5分钟窗口）
        cur.execute("""
            SELECT side, COUNT(*) FROM okx.trades
            WHERE inst_id=%s AND is_big=1 AND ts > (SELECT MAX(ts) FROM okx.trades) - 300000
            GROUP BY side
        """, (INST_ID,))
        bt = {r['side']: r['count'] for r in cur.fetchall()}
        big = {'buy': bt.get('buy', 0), 'sell': bt.get('sell', 0),
               'net': bt.get('buy', 0) - bt.get('sell', 0)}

        # 最新行情
        cur.execute("""
            SELECT ts, last, bid_px, ask_px, high_24h, low_24h, change_pct, vol_24h
            FROM okx.tickers WHERE inst_id=%s ORDER BY ts DESC LIMIT 1
        """, (INST_ID,))
        ticker = cur.fetchone()

        # 资金费率
        cur.execute("""
            SELECT ts, funding_rate, next_funding_rate, premium
            FROM okx.funding_rates WHERE inst_id=%s ORDER BY ts DESC LIMIT 1
        """, (INST_ID,))
        funding = cur.fetchone()

        # K线（1m，最近30根）
        cur.execute("""
            SELECT ts, o, h, l, c, vol FROM okx.candles
            WHERE inst_id=%s AND bar='1m' ORDER BY ts DESC LIMIT 30
        """, (INST_ID,))
        candles = cur.fetchall()

        # 检查K线是否新鲜（<5分钟）
        candles_stale = False
        if candles:
            latest_ts = candles[0]['ts']
            now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
            candles_stale = (now_ts - latest_ts) > 300000

        return {
            'depth': depth, 'big': big, 'ticker': ticker,
            'funding': funding, 'candles': candles,
            'candles_stale': candles_stale
        }


def fetch_okx_account():
    """从 OKX API 拉取真实账户数据"""
    try:
        ts = okx_server_time()
        headers = {
            'OK-ACCESS-KEY': OKX_KEY,
            'OK-ACCESS-SIGN': okx_sig(ts, 'GET', '/api/v5/account/positions?instType=SWAP'),
            'OK-ACCESS-TIMESTAMP': ts,
            'OK-ACCESS-PASSPHRASE': OKX_PASS,
            'Content-Type': 'application/json',
        }
        r = requests.get('https://www.okx.com/api/v5/account/positions?instType=SWAP',
                         headers=headers, proxies=OKX_PROXY, timeout=10, verify=False)
        pos_data = json.loads(r.text)

        # 账户余额
        r2 = requests.get('https://www.okx.com/api/v5/account/balance',
                          headers={**headers, 'OK-ACCESS-SIGN': okx_sig(ts, 'GET', '/api/v5/account/balance')},
                          proxies=OKX_PROXY, timeout=10, verify=False)
        bal_data = json.loads(r2.text)

        positions = []
        if pos_data.get('code') == '0':
            for p in pos_data.get('data', []):
                if 'BTC' not in p.get('instId', ''):
                    continue
                positions.append({
                    'inst_id': p.get('instId'),
                    'pos_side': p.get('posSide'),
                    'avg_px': float(p.get('avgPx', 0)),
                    'mark_px': float(p.get('markPx', 0)),
                    'upl': float(p.get('upl', 0)),
                    'upl_ratio': float(p.get('uplRatio', 0)),
                    'lever': float(p.get('lever', 1)),
                    'liq_px': float(p.get('liqPx', 0)),
                    'pos': float(p.get('pos', 0)),
                    'margin': float(p.get('margin', 0)),
                })

        balance = None
        if bal_data.get('code') == '0':
            for d in bal_data.get('data', []):
                for b in d.get('details', []):
                    if b.get('ccy') == 'USDT':
                        balance = {
                            'eq': float(b.get('eq', 0)),
                            'cash_bal': float(b.get('cashBal', 0)),
                            'upl': float(b.get('upl', 0)),
                            'avail_eq': float(b.get('availEq', 0)),
                        }
                        break

        return {'positions': positions, 'balance': balance}
    except Exception as e:
        return {'error': str(e)}


# ============ 信号计算 ============

def calc_rsi(candles, period=14):
    if len(candles) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, min(period + 1, len(candles))):
        diff = float(candles[i-1]['c']) - float(candles[i]['c'])
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag = sum(gains) / len(gains) if gains else 0
    al = sum(losses) / len(losses) if losses else 0
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))


def calc_adx(candles, period=14):
    if len(candles) < period + 1:
        return 20.0
    pdm, mdm, trs = [], [], []
    for i in range(1, min(period, len(candles))):
        h, l, c = float(candles[i-1]['h']), float(candles[i-1]['l']), float(candles[i]['c'])
        tr = max(h - l, abs(h - c), abs(l - c))
        pdm.append(max(float(candles[i-1]['h']) - float(candles[i]['h']), 0))
        mdm.append(max(float(candles[i]['l']) - float(candles[i-1]['l']), 0))
        trs.append(tr)
    if not trs:
        return 20.0
    return min((sum(pdm) / sum(trs) + sum(mdm) / sum(trs)) / 2 * 100, 100)


def calc_cvd(candles):
    cvd = 0.0
    for c in candles[:20]:
        vol = float(c['vol'])
        cvd += vol if float(c['c']) > float(c['o']) else -vol
    return cvd


def compute_signal(data):
    depth = data.get('depth')
    big = data.get('big')
    ticker = data.get('ticker')
    funding = data.get('funding')
    candles = data.get('candles', [])
    candles_stale = data.get('candles_stale', False)

    price = ticker['last'] if ticker else (candles[0]['c'] if candles else 0)
    now = datetime.now()
    now_ts = int(now.timestamp() * 1000)

    # 基础指标
    rsi = calc_rsi(candles) if candles and not candles_stale else 50.0
    adx = calc_adx(candles) if candles and not candles_stale else 25.0
    cvd = calc_cvd(candles) if candles else 0.0
    depth_ratio = float(depth['depth_ratio_5']) if depth else 1.0
    depth_ratio_50 = float(depth['depth_ratio_50']) if depth else 1.0
    spread = float(depth['spread']) if depth else 0.0
    big_net = big['net'] if big else 0
    big_buy = big['buy'] if big else 0
    big_sell = big['sell'] if big else 0
    funding_rate = float(funding['funding_rate']) if funding else 0
    funding_premium = float(funding['premium']) if funding else 0

    # === 各维度评分 ===
    # 1. 盘口深度 (30%)
    if depth_ratio > DEPTH_BUY:
        depth_signal = min((depth_ratio - DEPTH_BUY) / 2, 1.0) * 0.5 + 0.5
        depth_label = f"深度极度偏多({depth_ratio:.2f})"
    elif depth_ratio < DEPTH_SELL:
        depth_signal = -(min((DEPTH_SELL - depth_ratio) / 0.5, 1.0) * 0.5 + 0.5)
        depth_label = f"深度极度偏空({depth_ratio:.2f})"
    else:
        depth_signal = (depth_ratio - 1.0) * 0.5
        depth_label = f"中性({depth_ratio:.2f})"

    # 2. 大单流向 (30%)
    if big_net > BIG_CONFIRM:
        big_signal = min(big_net / 10, 1.0) * 0.5 + 0.5
        big_label = f"大单净买入{big_net}笔"
    elif big_net < -BIG_CONFIRM:
        big_signal = -(min(abs(big_net) / 10, 1.0) * 0.5 + 0.5)
        big_label = f"大单净卖出{abs(big_net)}笔"
    else:
        big_signal = big_net * 0.1
        big_label = f"大单中性({big_net})"

    # 3. 资金费率 (15%)
    if funding_rate > FUNDING_THR:
        fund_signal = 0.3
        fund_label = f"资金费率偏高({funding_rate*100:.4f}%)"
    elif funding_rate < -FUNDING_THR:
        fund_signal = -0.3
        fund_label = f"资金费率偏低({funding_rate*100:.4f}%)"
    else:
        fund_signal = 0.0
        fund_label = f"资金费率中性({funding_rate*100:.4f}%)"

    # 4. RSI/ADX (25%)
    if rsi > 60 and adx > ADX_STRONG:
        rsi_signal = 0.5
        rsi_label = f"RSI超买({rsi:.1f})ADX强({adx:.1f})"
    elif rsi < 40 and adx > ADX_STRONG:
        rsi_signal = -0.5
        rsi_label = f"RSI超卖({rsi:.1f})ADX强({adx:.1f})"
    elif rsi > 60:
        rsi_signal = 0.1
        rsi_label = f"RSI偏热({rsi:.1f})"
    elif rsi < 40:
        rsi_signal = -0.1
        rsi_label = f"RSI偏冷({rsi:.1f})"
    else:
        rsi_signal = (rsi - 50) / 50 * 0.3
        rsi_label = f"RSI中性({rsi:.1f})"

    score = depth_signal * 0.30 + big_signal * 0.30 + fund_signal * 0.15 + rsi_signal * 0.25

    # 信号判定
    if score >= 0.65:
        mode = 'long'
    elif score <= -0.65:
        mode = 'short'
    elif score > 0.35:
        mode = 'long_pending'
    elif score < -0.35:
        mode = 'short_pending'
    else:
        mode = 'wait'

    # ADX 弱市修正
    if adx < ADX_WEAK:
        if mode == 'long':
            mode = 'long_pending'
        elif mode == 'short':
            mode = 'short_pending'
        elif mode == 'wait':
            pass

    # K线陈旧警告
    if candles_stale:
        mode = 'wait'
        rsi_label += " [K线陈旧]"

    sentiment = classify_sentiment(score, depth_ratio, big_net)

    return {
        'ts': now_ts, 'dt': now,
        'mode': mode, 'score': round(score, 4),
        'price': price, 'rsi': round(rsi, 2), 'adx': round(adx, 2),
        'cvd': round(cvd, 2), 'depth_ratio_5': round(depth_ratio, 4),
        'depth_ratio_50': round(depth_ratio_50, 4), 'spread': round(spread, 2),
        'big_trade_net': big_net, 'big_trade_buy': big_buy, 'big_trade_sell': big_sell,
        'funding_rate': funding_rate, 'funding_premium': funding_premium,
        'candles_stale': candles_stale,
        'depth_label': depth_label, 'big_label': big_label,
        'fund_label': fund_label, 'rsi_label': rsi_label,
        'sentiment': sentiment['情绪'], 'sentiment_reason': sentiment['理由'],
        'high24h': ticker['high_24h'] if ticker else 0,
        'low24h': ticker['low_24h'] if ticker else 0,
        'vol24h': ticker['vol_24h'] if ticker else 0,
    }


def classify_sentiment(score, depth_ratio, big_net):
    if score > 0.4 or (depth_ratio > 2.0 and big_net > 3):
        return {'情绪': '强势看多', '理由': '综合信号强劲', '对BTC影响': '正向'}
    elif score < -0.4 or (depth_ratio < 0.5 and big_net < -3):
        return {'情绪': '强势看空', '理由': '综合信号偏弱', '对BTC影响': '负向'}
    else:
        return {'情绪': '中性', '理由': '信号不明', '对BTC影响': '中性'}


# ============ 数据持久化 ============

def save_signal(conn, sig):
    """保存信号到 btc.signal_log"""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO btc.signal_log (ts, dt, mode, score, price, rsi, adx, cvd,
                depth_ratio_5, big_trade_net, funding_rate, sentiment, sentiment_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (sig['ts'], sig['dt'], sig['mode'], sig['score'], sig['price'],
              sig['rsi'], sig['adx'], sig['cvd'], sig['depth_ratio_5'],
              sig['big_trade_net'], sig['funding_rate'], sig['sentiment'], sig['sentiment_reason']))
        conn.commit()


def save_indicator_snapshot(conn, sig):
    """保存技术指标快照到 btc.indicator_snapshots"""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO btc.indicator_snapshots
            (ts, dt, inst_id, price, rsi, adx, cvd, depth_ratio_5, depth_ratio_50,
             spread, big_trade_net, big_trade_buy, big_trade_sell, funding_rate)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (sig['ts'], sig['dt'], INST_ID, sig['price'], sig['rsi'], sig['adx'],
              sig['cvd'], sig['depth_ratio_5'], sig['depth_ratio_50'], sig['spread'],
              sig['big_trade_net'], sig['big_trade_buy'], sig['big_trade_sell'],
              sig['funding_rate']))
        conn.commit()


def save_account_snapshot(conn, account, data):
    """保存账户快照到 btc.account_snapshots"""
    now = datetime.now()
    now_ts = int(now.timestamp() * 1000)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO btc.account_snapshots
            (ts, dt, account, balance, equity, unrealized_pnl, leverage,
             pos_side, pos_size, entry_price, liq_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (now_ts, now, account,
              data.get('balance', 0), data.get('equity', 0),
              data.get('upl', 0), data.get('lever', 1),
              data.get('pos_side'), data.get('pos', 0),
              data.get('avg_px', 0), data.get('liq_px', 0)))
        conn.commit()


def save_alert(conn, severity, alert_type, message, price=None):
    """保存预警到 btc.alert_log"""
    now = datetime.now()
    now_ts = int(now.timestamp() * 1000)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO btc.alert_log (ts, dt, severity, alert_type, message, price)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (now_ts, now, severity, alert_type, message, price))
        conn.commit()


# ============ Supabase 同步 ============

def sync_to_supabase(table, records, pk_field='id'):
    """同步数据到 Supabase"""
    if not records:
        return
    headers = {
        'apikey': SB_KEY,
        'Authorization': f'Bearer {SB_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates'
    }
    url = f'{SB_BASE}/{table}'
    try:
        req = urllib.request.Request(
            url, data=json.dumps(records).encode(),
            headers=headers, method='POST'
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Supabase sync error: {e}")


def sync_signal_to_supabase(sig):
    """同步信号到云端"""
    record = {
        'ts': sig['ts'],
        'dt': sig['dt'].isoformat(),
        'mode': sig['mode'],
        'score': float(sig['score']),
        'price': float(sig['price']),
        'rsi': float(sig['rsi']),
        'adx': float(sig['adx']),
        'cvd': float(sig['cvd']),
        'depth_ratio_5': float(sig['depth_ratio_5']),
        'big_trade_net': sig['big_trade_net'],
        'funding_rate': float(sig['funding_rate']),
        'sentiment': sig['sentiment'],
        'sentiment_reason': sig['sentiment_reason'],
    }
    sync_to_supabase('btc_signals', [record], pk_field='ts')


def sync_account_to_supabase(account, data):
    """同步账户快照到云端"""
    record = {
        'account': account,
        'dt': datetime.now().isoformat(),
        'balance': float(data.get('balance', 0)),
        'equity': float(data.get('equity', 0)),
        'unrealized_pnl': float(data.get('upl', 0)),
        'leverage': float(data.get('lever', 1)),
        'pos_side': data.get('pos_side'),
        'pos_size': float(data.get('pos', 0)),
        'entry_price': float(data.get('avg_px', 0)),
    }
    sync_to_supabase('btc_accounts', [record], pk_field='account')


# ============ market_data.json 生成 ============

def generate_market_json(sig, account_data=None):
    """生成 market_data.json 供现有监控脚本使用"""
    # 确保所有数值都是 float/int，避免 Decimal 序列化问题
    def to_float(v):
        return float(v) if v is not None else 0.0
    
    market = {
        'price': to_float(sig['price']),
        'rsi': to_float(sig['rsi']),
        'macd': 0,
        'signal': 0,
        'atr': 200,
        'cvd': to_float(sig['cvd']),
        'adx': to_float(sig['adx']),
        'mode': sig['mode'],
        'state': 'oscillation',
        'trend': 'neutral',
        'market_state': 'oscillation',
        'funding_rate': to_float(sig['funding_rate']),
        'oi': 0,
        'last_update': sig['dt'].strftime('%Y-%m-%d %H:%M:%S'),
        'bid_price': to_float(sig['price']),
        'ask_price': to_float(sig['price']),
        'bid_size': 0,
        'ask_size': 0,
        'spread': to_float(sig['spread']),
        'sentiment': {
            '情绪': sig['sentiment'],
            '理由': sig['sentiment_reason'],
            '对BTC影响': '正向' if sig['score'] > 0 else '负向' if sig['score'] < 0 else '中性'
        },
        'next_funding_time': 0,
        'harvest_warnings': [],
        # 增强字段
        'depth_ratio_5': to_float(sig['depth_ratio_5']),
        'depth_ratio_50': to_float(sig['depth_ratio_50']),
        'big_trade_net': sig['big_trade_net'],
        'big_trade_buy': sig['big_trade_buy'],
        'big_trade_sell': sig['big_trade_sell'],
        'signal_score': to_float(sig['score']),
        'depth_label': sig['depth_label'],
        'big_label': sig['big_label'],
        'fund_label': sig['fund_label'],
        'rsi_label': sig['rsi_label'],
        'candles_stale': sig['candles_stale'],
        'high24h': to_float(sig['high24h']),
        'low24h': to_float(sig['low24h']),
        'vol24h': to_float(sig['vol24h']),
    }

    # 账户数据
    accounts = {}
    if account_data:
        # 真实账户
        if account_data.get('positions'):
            pos = account_data['positions'][0]
            accounts['Real'] = {
                'name': '真实账户',
                'capital': account_data.get('balance', {}).get('eq', 0),
                'position': {
                    'side': pos['pos_side'],
                    'entry': pos['avg_px'],
                    'size': pos['pos'],
                    'leverage': pos['lever'],
                    'upl': pos['upl'],
                    'liq_px': pos['liq_px'],
                },
                'unrealized': pos['upl'],
            }
        else:
            accounts['Real'] = {
                'name': '真实账户',
                'capital': account_data.get('balance', {}).get('eq', 0),
                'position': None,
                'unrealized': 0,
            }

    result = {
        'market': market,
        'accounts': accounts,
        'updated_at': sig['dt'].strftime('%Y-%m-%d %H:%M:%S'),
        'signal_desc': f"[{sig['mode'].upper()}] {sig['depth_label']} | {sig['big_label']} | {sig['fund_label']} | {sig['rsi_label']}",
        'market_state_desc': '震荡 🔵' if sig['adx'] < 25 else '趋势 📈',
        'timestamp': sig['dt'].strftime('%Y-%m-%d %H:%M:%S'),
    }

    with open('/tmp/market_data.json', 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


# ============ 预警检测 ============

def check_alerts(sig, account_data):
    """检测预警条件"""
    alerts = []

    # 1. 信号变化
    try:
        with open('/tmp/.last_signal', 'r') as f:
            last_mode = f.read().strip()
    except:
        last_mode = 'wait'

    if last_mode != sig['mode'] and sig['mode'] != 'wait':
        alerts.append({
            'severity': 'info',
            'type': 'signal_change',
            'msg': f"信号变化: {last_mode} → {sig['mode']} (评分: {sig['score']:+.2f})",
            'price': sig['price']
        })

    with open('/tmp/.last_signal', 'w') as f:
        f.write(sig['mode'])

    # 2. 强平风险
    if account_data and account_data.get('positions'):
        for pos in account_data['positions']:
            if pos.get('liq_px', 0) > 0 and pos.get('avg_px', 0) > 0:
                dist = abs(sig['price'] - pos['liq_px']) / sig['price'] * 100
                if dist < 2:
                    alerts.append({
                        'severity': 'critical',
                        'type': 'liquidation_risk',
                        'msg': f"🚨 距强平仅 {dist:.1f}%！{pos['pos_side'].upper()} {pos['pos']}张 @ {pos['avg_px']:.0f}",
                        'price': sig['price']
                    })
                elif dist < 5:
                    alerts.append({
                        'severity': 'warning',
                        'type': 'liquidation_warning',
                        'msg': f"⚠️ 距强平 {dist:.1f}% {pos['pos_side'].upper()} {pos['pos']}张",
                        'price': sig['price']
                    })

    # 3. K线陈旧
    if sig['candles_stale']:
        alerts.append({
            'severity': 'warning',
            'type': 'data_stale',
            'msg': "⚠️ K线数据陈旧，信号可能不准确",
            'price': sig['price']
        })

    # 4. 大单异动
    if abs(sig['big_trade_net']) > 50:
        direction = "买入" if sig['big_trade_net'] > 0 else "卖出"
        alerts.append({
            'severity': 'info',
            'type': 'big_trade_spike',
            'msg': f"📊 大单{direction}异动: {abs(sig['big_trade_net'])}笔",
            'price': sig['price']
        })

    return alerts


# ============ 主循环 ============

def run_once():
    """执行一次完整的数据采集-计算-保存-同步流程"""
    conn = pg_conn()
    try:
        # 1. 采集市场数据
        data = fetch_okx_public(conn)

        # 2. 计算信号
        sig = compute_signal(data)

        # 3. 采集真实账户
        account_data = fetch_okx_account()

        # 4. 保存到本地数据库
        save_signal(conn, sig)
        save_indicator_snapshot(conn, sig)

        if account_data and not account_data.get('error'):
            if account_data.get('balance'):
                save_account_snapshot(conn, 'Real', {
                    **account_data['balance'],
                    **(account_data['positions'][0] if account_data.get('positions') else {})
                })
            for pos in account_data.get('positions', []):
                save_account_snapshot(conn, f"Real_{pos['inst_id']}", pos)

        # 5. 检测预警
        alerts = check_alerts(sig, account_data)
        for a in alerts:
            save_alert(conn, a['severity'], a['type'], a['msg'], a['price'])

        # 6. 同步到 Supabase
        sync_signal_to_supabase(sig)
        if account_data and not account_data.get('error'):
            sync_account_to_supabase('Real', {
                **(account_data.get('balance') or {}),
                **(account_data['positions'][0] if account_data.get('positions') else {})
            })

        # 7. 生成 market_data.json
        generate_market_json(sig, account_data)

        # 8. 输出日志
        ts = sig['dt'].strftime('%H:%M:%S')
        stale_flag = " [K线陈旧]" if sig['candles_stale'] else ""
        print(f"[{ts}] {sig['mode']:12s} ({sig['score']:+.2f}) | ${sig['price']:,.0f} | "
              f"RSI={sig['rsi']:.0f} ADX={sig['adx']:.0f} | "
              f"深度={sig['depth_ratio_5']:.2f} 大单={sig['big_trade_net']:+d}{stale_flag}")

        if alerts:
            for a in alerts:
                print(f"  ⚠️ [{a['severity']}] {a['msg']}")

        return sig, account_data, alerts

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: {e}")
        import traceback
        traceback.print_exc()
        return None, None, []
    finally:
        conn.close()


def main():
    print("=" * 70)
    print("BTC 统一监控引擎 v2.0")
    print("=" * 70)
    print(f"本地数据库: {PG_HOST}:{PG_PORT}/{PG_DB}")
    print(f"云端同步: Supabase ({SB_BASE.split('/')[2]})")
    print(f"OKX API: 真实账户数据 + 市场数据")
    print("=" * 70)
    print("数据流向:")
    print("  OKX API → okx schema (原始采集)")
    print("  OKX API → btc schema (信号/账户/预警)")
    print("  btc schema → Supabase (云端备份)")
    print("  btc schema → market_data.json (监控脚本)")
    print("=" * 70)

    while True:
        run_once()
        time.sleep(5)


if __name__ == '__main__':
    main()
