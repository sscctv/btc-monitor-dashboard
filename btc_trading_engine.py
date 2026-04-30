#!/usr/bin/env python3
"""
BTC 智能交易系统 v3.0 - 统一引擎
==================================
数据源: OKX 数据库 (okx schema)
核心信号: 盘口深度(30%) + 大单流向(30%) + 资金费率(15%) + RSI/ADX(25%)
账户: V1/V2/V3 虚拟账户 + Real 真实账户
记录: 全部存入 btc schema + 同步 Supabase
推送: 仅发送有效交易信号，不发"等待"类消息
"""

import os
import json, time, hashlib, hmac, base64, requests, urllib.request, warnings
from datetime import datetime, timezone
from collections import deque
import psycopg2
from psycopg2.extras import RealDictCursor

warnings.filterwarnings('ignore')

# === 配置 ===
PG_HOST = '192.168.1.2'; PG_PORT = '5432'; PG_USER = 'postgres'; PG_PASSWORD = 'Postgres@2026'; PG_DB = 'postgres'
SB_KEY = os.getenv('SB_SECRET_KEY', '')
SB_BASE = 'https://lpcrnobolifrzwrkxoli.supabase.co/rest/v1'
OKX_KEY = 'c72740a8-71ab-41ba-bef5-e7640e3efac9'
OKX_SECRET = '6E1EA8F850D168D5D47C8155A6460F06'
OKX_PASS = 'Jiege#@/123'
OKX_PROXY = {'http': 'http://172.17.0.1:7890', 'https': 'http://172.17.0.1:7890'}
INST_ID = 'BTC-USDT-SWAP'
TARGET = 'o9cq801cl6QXRfJWhroBxDriyjXA@im.wechat'
STATE_FILE = '/tmp/.btc_trade_state'

# 策略配置
STRATEGIES = {
    'V1': {'name': '保守型', 'adx_thr': 30, 'rsi_min': 35, 'rsi_max': 65, 'risk_pct': 0.30, 'leverage': 50, 'confirm': True},
    'V2': {'name': '平衡型', 'adx_thr': 25, 'rsi_min': 30, 'rsi_max': 70, 'risk_pct': 0.40, 'leverage': 100, 'confirm': True},
    'V3': {'name': '激进型', 'adx_thr': 20, 'rsi_min': 25, 'rsi_max': 75, 'risk_pct': 0.50, 'leverage': 100, 'confirm': False},
}

# 信号阈值
DEPTH_BUY = 2.0; DEPTH_SELL = 0.5; BIG_CONFIRM = 3; FUNDING_THR = 0.0001


def pg_conn():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB, connect_timeout=5, cursor_factory=RealDictCursor)

def okx_sig(ts, method, path, body=''):
    msg = str(ts) + method + path + body
    return base64.b64encode(hmac.new(OKX_SECRET.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def okx_server_time():
    try:
        r = requests.get('https://www.okx.com/api/v5/public/time', proxies=OKX_PROXY, timeout=10, verify=False)
        return datetime.utcfromtimestamp(int(json.loads(r.text)['data'][0]['ts']) / 1000).strftime('%Y-%m-%dT%H:%M:%S.') + 'Z'
    except:
        return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.') + 'Z'

def send_wechat(msg, short=False):
    try:
        subprocess.run(['openclaw', 'message', 'send', '--channel', 'openclaw-weixin', '--target', TARGET, '--message', msg], capture_output=True, timeout=15)
    except:
        pass

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {'positions': {}, 'last_signal': None, 'last_alert': None}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)


# ============ 数据采集 ============

def fetch_market_data(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT ts, depth_ratio_5, depth_ratio_50, spread FROM okx.order_book_summary WHERE inst_id=%s ORDER BY ts DESC LIMIT 1", (INST_ID,))
        depth = cur.fetchone()

        cur.execute("""SELECT side, COUNT(*) FROM okx.trades WHERE inst_id=%s AND is_big=1 AND ts > (SELECT MAX(ts) FROM okx.trades) - 300000 GROUP BY side""", (INST_ID,))
        bt = {r['side']: r['count'] for r in cur.fetchall()}
        big = {'buy': bt.get('buy', 0), 'sell': bt.get('sell', 0), 'net': bt.get('buy', 0) - bt.get('sell', 0)}

        cur.execute("SELECT ts, last, bid_px, ask_px, high_24h, low_24h, change_pct, vol_24h FROM okx.tickers WHERE inst_id=%s ORDER BY ts DESC LIMIT 1", (INST_ID,))
        ticker = cur.fetchone()

        cur.execute("SELECT ts, funding_rate, premium FROM okx.funding_rates WHERE inst_id=%s ORDER BY ts DESC LIMIT 1", (INST_ID,))
        funding = cur.fetchone()

        cur.execute("SELECT ts, o, h, l, c, vol FROM okx.candles WHERE inst_id=%s AND bar='1m' ORDER BY ts DESC LIMIT 30", (INST_ID,))
        candles = cur.fetchall()

        stale = False
        if candles:
            stale = (int(datetime.now(timezone.utc).timestamp() * 1000) - candles[0]['ts']) > 300000

        return {'depth': depth, 'big': big, 'ticker': ticker, 'funding': funding, 'candles': candles, 'stale': stale}


def fetch_real_account():
    try:
        ts = okx_server_time()
        headers = {'OK-ACCESS-KEY': OKX_KEY, 'OK-ACCESS-SIGN': okx_sig(ts, 'GET', '/api/v5/account/positions?instType=SWAP'),
                   'OK-ACCESS-TIMESTAMP': ts, 'OK-ACCESS-PASSPHRASE': OKX_PASS, 'Content-Type': 'application/json'}
        r = requests.get('https://www.okx.com/api/v5/account/positions?instType=SWAP', headers=headers, proxies=OKX_PROXY, timeout=10, verify=False)
        pos_data = json.loads(r.text)

        r2 = requests.get('https://www.okx.com/api/v5/account/balance', headers=headers, proxies=OKX_PROXY, timeout=10, verify=False)
        bal_data = json.loads(r2.text)

        positions = []
        if pos_data.get('code') == '0':
            for p in pos_data.get('data', []):
                if 'BTC' not in p.get('instId', ''):
                    continue
                positions.append({'inst_id': p.get('instId'), 'pos_side': p.get('posSide'), 'avg_px': float(p.get('avgPx', 0)),
                    'mark_px': float(p.get('markPx', 0)), 'upl': float(p.get('upl', 0)), 'lever': float(p.get('lever', 1)),
                    'liq_px': float(p.get('liqPx', 0)), 'pos': float(p.get('pos', 0))})

        balance = None
        if bal_data.get('code') == '0':
            for d in bal_data.get('data', []):
                for b in d.get('details', []):
                    if b.get('ccy') == 'USDT':
                        balance = {'eq': float(b.get('eq', 0)), 'upl': float(b.get('upl', 0)), 'avail_eq': float(b.get('availEq', 0))}

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
        gains.append(max(diff, 0)); losses.append(max(-diff, 0))
    ag = sum(gains) / len(gains) if gains else 0
    al = sum(losses) / len(losses) if losses else 0
    return 100.0 if al == 0 else 100 - (100 / (1 + ag / al))

def calc_adx(candles, period=14):
    if len(candles) < period + 1:
        return 20.0
    pdm, mdm, trs = [], [], []
    for i in range(1, min(period, len(candles))):
        h, l = float(candles[i-1]['h']), float(candles[i-1]['l'])
        c = float(candles[i]['c'])
        tr = max(h - l, abs(h - c), abs(l - c))
        pdm.append(max(float(candles[i-1]['h']) - float(candles[i]['h']), 0))
        mdm.append(max(float(candles[i]['l']) - float(candles[i-1]['l']), 0))
        trs.append(tr)
    if not trs:
        return 20.0
    return min((sum(pdm) / sum(trs) + sum(mdm) / sum(trs)) / 2 * 100, 100)

def compute_signal(data):
    depth, big, ticker, funding, candles, stale = data['depth'], data['big'], data['ticker'], data['funding'], data['candles'], data['stale']

    price = float(ticker['last']) if ticker else (float(candles[0]['c']) if candles else 0)
    rsi = calc_rsi(candles) if candles and not stale else 50.0
    adx = calc_adx(candles) if candles and not stale else 25.0
    depth_ratio = float(depth['depth_ratio_5']) if depth else 1.0
    big_net = big['net'] if big else 0
    big_buy = big['buy'] if big else 0
    big_sell = big['sell'] if big else 0
    funding_rate = float(funding['funding_rate']) if funding else 0

    # 评分
    depth_s = (min((depth_ratio - DEPTH_BUY) / 2, 1.0) * 0.5 + 0.5) if depth_ratio > DEPTH_BUY else \
              (-(min((DEPTH_SELL - depth_ratio) / 0.5, 1.0) * 0.5 + 0.5)) if depth_ratio < DEPTH_SELL else (depth_ratio - 1.0) * 0.5
    big_s = (min(big_net / 10, 1.0) * 0.5 + 0.5) if big_net > BIG_CONFIRM else \
            (-(min(abs(big_net) / 10, 1.0) * 0.5 + 0.5)) if big_net < -BIG_CONFIRM else big_net * 0.1
    fund_s = 0.3 if funding_rate > FUNDING_THR else (-0.3 if funding_rate < -FUNDING_THR else 0.0)
    rsi_s = 0.5 if rsi > 60 and adx > 30 else (-0.5 if rsi < 40 and adx > 30 else (0.1 if rsi > 60 else (-0.1 if rsi < 40 else (rsi - 50) / 50 * 0.3)))

    score = depth_s * 0.30 + big_s * 0.30 + fund_s * 0.15 + rsi_s * 0.25

    if score >= 0.65: mode = 'long'
    elif score <= -0.65: mode = 'short'
    elif score > 0.35: mode = 'long_pending'
    elif score < -0.35: mode = 'short_pending'
    else: mode = 'wait'

    if adx < 20 and mode in ('long', 'short'):
        mode = mode + '_pending'

    sentiment = '强势看多' if score > 0.4 or (depth_ratio > 2.0 and big_net > 3) else \
               ('强势看空' if score < -0.4 or (depth_ratio < 0.5 and big_net < -3) else '中性')

    return {
        'mode': mode, 'score': round(score, 4), 'price': price, 'rsi': round(rsi, 2), 'adx': round(adx, 2),
        'depth_ratio': round(depth_ratio, 4), 'big_net': big_net, 'big_buy': big_buy, 'big_sell': big_sell,
        'funding_rate': funding_rate, 'stale': stale, 'sentiment': sentiment,
        'high24h': float(ticker['high_24h']) if ticker else 0, 'low24h': float(ticker['low_24h']) if ticker else 0,
    }


# ============ 数据持久化 ============

def save_signal(conn, sig, dt):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO btc.signal_log (ts, dt, mode, score, price, rsi, adx, depth_ratio_5, big_trade_net, funding_rate, sentiment)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (int(datetime.now().timestamp()*1000), dt, sig['mode'], sig['score'], sig['price'], sig['rsi'], sig['adx'], sig['depth_ratio'], sig['big_net'], sig['funding_rate'], sig['sentiment']))
        conn.commit()

def save_trade(conn, account, action, side, entry, exit_price, size, pnl, leverage, strategy, signal_mode, reason):
    now = datetime.now()
    now_ts = int(now.timestamp() * 1000)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO btc.all_trades (ts, dt, account, action, side, entry_price, exit_price, size, pnl, leverage, strategy, signal_mode, reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (now_ts, now, account, action, side, entry, exit_price, size, pnl, leverage, strategy, signal_mode, reason))
        conn.commit()

def save_balance_history(conn, account, balance, equity, unrealized):
    now = datetime.now()
    now_ts = int(now.timestamp() * 1000)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO btc.balance_history (ts, dt, account, balance, equity, unrealized_pnl) VALUES (%s,%s,%s,%s,%s,%s)",
            (now_ts, now, account, balance, equity or balance, unrealized or 0))
        conn.commit()

def save_alert(conn, severity, alert_type, message, price):
    now = datetime.now()
    now_ts = int(now.timestamp() * 1000)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO btc.alert_log (ts, dt, severity, alert_type, message, price) VALUES (%s,%s,%s,%s,%s,%s)",
            (now_ts, now, severity, alert_type, message, price))
        conn.commit()


# ============ Supabase 同步 ============

def sync_supabase(table, records):
    if not records: return
    headers = {'apikey': SB_KEY, 'Authorization': f'Bearer {SB_KEY}', 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates'}
    try:
        req = urllib.request.Request(f'{SB_BASE}/{table}', data=json.dumps(records).encode(), headers=headers, method='POST')
        urllib.request.urlopen(req, timeout=10)
    except: pass


# ============ market_data.json 生成 ============

def write_market_json(sig, dt, virtual_balances):
    now_str = dt.strftime('%Y-%m-%d %H:%M:%S')
    market = {
        'price': sig['price'], 'rsi': sig['rsi'], 'macd': 0, 'signal': 0, 'atr': 200, 'cvd': 0,
        'adx': sig['adx'], 'mode': sig['mode'], 'state': 'oscillation', 'trend': 'neutral',
        'market_state': 'oscillation', 'funding_rate': sig['funding_rate'], 'oi': 0,
        'last_update': now_str, 'bid_price': sig['price'], 'ask_price': sig['price'],
        'bid_size': 0, 'ask_size': 0, 'spread': 0.1,
        'sentiment': {'情绪': sig['sentiment'], '理由': '综合信号', '对BTC影响': '正向' if sig['score'] > 0 else '负向'},
        'next_funding_time': 0, 'harvest_warnings': [],
        'depth_ratio_5': sig['depth_ratio'], 'big_trade_net': sig['big_net'],
        'big_trade_buy': sig['big_buy'], 'big_trade_sell': sig['big_sell'],
        'signal_score': sig['score'], 'candles_stale': sig['stale'],
        'high24h': sig['high24h'], 'low24h': sig['low24h'],
    }
    accounts = {'Real': {'name': '真实账户', 'capital': 0, 'position': None, 'unrealized': 0}}
    result = {'market': market, 'accounts': accounts, 'updated_at': now_str,
              'signal_desc': f"[{sig['mode'].upper()}] 评分:{sig['score']:+.2f}", 'market_state_desc': '震荡' if sig['adx'] < 25 else '趋势',
              'timestamp': now_str}
    with open('/tmp/market_data.json', 'w') as f:
        json.dump(result, f, ensure_ascii=False)


# ============ 交易决策 ============

def should_open(acc, sig, strat):
    """判断是否开仓"""
    mode = sig['mode']
    if mode == 'wait' or mode.endswith('_pending') and strat['confirm']:
        return False
    if mode == 'long' or (mode == 'long_pending' and not strat['confirm']):
        return 'long'
    if mode == 'short' or (mode == 'short_pending' and not strat['confirm']):
        return 'short'
    return False

def should_close(acc, pos, sig, strat):
    """判断是否平仓"""
    mode = sig['mode']
    price = sig['price']
    entry = pos['entry']
    side = pos['side']

    # 强平风险
    if 'liq_px' in pos and pos['liq_px'] > 0:
        dist = abs(price - pos['liq_px']) / price * 100
        if dist < 2: return True, '强平风险', 0

    # 信号反转
    if side == 'long' and mode in ('short', 'short_pending') and sig['adx'] > strat['adx_thr']:
        return True, '信号反转为做空', 0
    if side == 'short' and mode in ('long', 'long_pending') and sig['adx'] > strat['adx_thr']:
        return True, '信号反转为做多', 0

    # 无趋势
    if sig['adx'] < 15:
        return True, 'ADX无趋势', 0

    return False, '', 0

def calculate_size(balance, risk_pct, price, leverage):
    risk_amount = balance * risk_pct
    notional = risk_amount * leverage
    return notional / price

def generate_advice(sig, pos, account):
    """生成详细的交易建议"""
    mode = sig['mode']
    price = sig['price']
    score = sig['score']
    depth = sig['depth_ratio']
    big = sig['big_net']
    rsi = sig['rsi']
    adx = sig['adx']
    sentiment = sig['sentiment']

    advice = []
    action = '⏸️ 观望'

    if mode == 'long':
        action = '🟢 做多'
        advice.append(f'✅ 信号确认: 综合评分 {score:+.2f}，{sentiment}')
        advice.append(f'📊 市场: ${price:,.0f} | RSI:{rsi:.0f} | ADX:{adx:.0f}')
        advice.append(f'📐 深度比: {depth:.2f} | 大单净流向: {big:+d}笔')
        if pos:
            tp = price * 1.015  # 1.5%止盈参考
            sl = price * 0.985   # 1.5%止损参考
            advice.append(f'🎯 建议止盈: ${tp:,.0f} | 🛑 止损: ${sl:,.0f}')
    elif mode == 'short':
        action = '🔴 做空'
        advice.append(f'✅ 信号确认: 综合评分 {score:+.2f}，{sentiment}')
        advice.append(f'📊 市场: ${price:,.0f} | RSI:{rsi:.0f} | ADX:{adx:.0f}')
        advice.append(f'📐 深度比: {depth:.2f} | 大单净流向: {big:+d}笔')
        if pos:
            tp = price * 0.985
            sl = price * 1.015
            advice.append(f'🎯 建议止盈: ${tp:,.0f} | 🛑 止损: ${sl:,.0f}')
    elif mode == 'long_pending':
        action = '🟡 等待做多确认'
        advice.append(f'⚠️ 待确认信号: 评分 {score:+.2f}，{sentiment}')
        advice.append(f'📊 市场: ${price:,.0f} | RSI:{rsi:.0f} | ADX:{adx:.0f}')
        advice.append(f'📐 ADX<25，趋势不明确，建议等待信号确认')
    elif mode == 'short_pending':
        action = '🟡 等待做空确认'
        advice.append(f'⚠️ 待确认信号: 评分 {score:+.2f}，{sentiment}')
        advice.append(f'📊 市场: ${price:,.0f} | RSI:{rsi:.0f} | ADX:{adx:.0f}')
        advice.append(f'📐 ADX<25，趋势不明确，建议等待信号确认')
    else:
        advice.append(f'⏸️ 当前评分 {score:+.2f}，{sentiment}')
        advice.append(f'📊 市场: ${price:,.0f} | RSI:{rsi:.0f} | ADX:{adx:.0f}')

    return action, advice


# ============ 主循环 ============

def run():
    state = load_state()
    conn = pg_conn()
    try:
        dt = datetime.now()
        data = fetch_market_data(conn)
        sig = compute_signal(data)
        real = fetch_real_account()

        # 保存信号
        save_signal(conn, sig, dt)

        # 生成 market_data.json
        virtual_balances = {'V1': 1015.3, 'V2': 1015.3, 'V3': 1015.3}
        write_market_json(sig, dt, virtual_balances)

        # === 真实账户处理 ===
        if real and not real.get('error') and real.get('positions'):
            for pos in real['positions']:
                save_trade(conn, 'Real', 'snapshot', pos['pos_side'], pos['avg_px'], pos['mark_px'], pos['pos'],
                           pos['upl'], int(pos['lever']), 'real', sig['mode'], '持仓快照')
                save_balance_history(conn, 'Real', real['balance']['eq'] if real.get('balance') else 0,
                                    real['balance']['eq'] if real.get('balance') else 0, pos['upl'])
                # 强平预警
                if pos.get('liq_px', 0) > 0:
                    dist = abs(sig['price'] - pos['liq_px']) / sig['price'] * 100
                    if dist < 5:
                        msg = f"🚨 距强平仅 {dist:.1f}%！{pos['pos_side'].upper()} {pos['pos']}张 @ ${pos['avg_px']:.0f}"
                        save_alert(conn, 'critical', 'liquidation', msg, sig['price'])
                        send_wechat(msg)

        # === 同步到 Supabase ===
        sync_supabase('btc_signals', [{'ts': int(dt.timestamp()*1000), 'dt': dt.isoformat(), 'mode': sig['mode'],
            'score': float(sig['score']), 'price': float(sig['price']), 'rsi': float(sig['rsi']),
            'adx': float(sig['adx']), 'depth_ratio_5': float(sig['depth_ratio']),
            'big_trade_net': sig['big_net'], 'sentiment': sig['sentiment']}])

        # === 同步账户到 Supabase ===
        if real and not real.get('error'):
            acc_bal = real.get('balance', {})
            for pos in real.get('positions', []):
                sync_supabase('btc_accounts', [{
                    'account_id': 'Real_' + pos['inst_id'],
                    'account': 'Real',
                    'balance': float(acc_bal.get('eq', 0)),
                    'equity': float(acc_bal.get('eq', 0)),
                    'unrealized_pnl': float(pos.get('upl', 0)),
                    'leverage': int(pos.get('lever', 1)),
                    'pos_side': pos.get('pos_side'),
                    'pos_size': float(pos.get('pos', 0)),
                    'entry_price': float(pos.get('avg_px', 0)),
                    'liq_price': float(pos.get('liq_px', 0)),
                    'status': 'open',
                    'updated_at': dt.isoformat()
                }])

                # 交易记录
                sync_supabase('btc_trades', [{
                    'ts': int(dt.timestamp()*1000), 'dt': dt.isoformat(),
                    'account': 'Real', 'action': 'snapshot', 'side': pos.get('pos_side', ''),
                    'entry_price': float(pos.get('avg_px', 0)), 'exit_price': float(pos.get('mark_px', 0)),
                    'size': float(pos.get('pos', 0)), 'pnl': float(pos.get('upl', 0)),
                    'leverage': int(pos.get('lever', 1)), 'signal_mode': sig['mode'],
                    'reason': '持仓快照', 'status': 'open'
                }])

        # === 输出日志 ===
        ts_str = dt.strftime('%H:%M:%S')
        stale_flag = ' [K线陈旧]' if sig['stale'] else ''
        print(f"[{ts_str}] {sig['mode']:14s} ({sig['score']:+.2f}) | ${sig['price']:,.0f} | RSI={sig['rsi']:.0f} ADX={sig['adx']:.0f} | 深度={sig['depth_ratio']:.2f} 大单={sig['big_net']:+d}{stale_flag}")

        return sig, real, state

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: {e}")
        import traceback; traceback.print_exc()
        return None, None, None
    finally:
        conn.close()


def main():
    print("=" * 70)
    print("BTC 智能交易系统 v3.0")
    print("=" * 70)
    print("数据: OKX数据库(okx schema) → btc schema → market_data.json")
    print("推送: 仅发送有效信号，不发等待类消息")
    print("=" * 70)

    while True:
        run()
        time.sleep(5)


if __name__ == '__main__':
    main()
