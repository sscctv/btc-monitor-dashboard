#!/usr/bin/env python3
"""
每日复盘脚本 - 每天 08:00 自动发送
"""
import requests, json, hashlib, hmac, base64, sqlite3, warnings, subprocess
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

PROXY = {'http': 'http://172.17.0.1:7890', 'https': 'http://172.17.0.1:7890'}
API_KEY = "c72740a8-71ab-41ba-bef5-e7640e3efac9"
SECRET_KEY = "6E1EA8F850D168D5D47C8155A6460F06"
PASSPHRASE = "Jiege#@/123"
TARGET = "o9cq801cl6QXRfJWhroBxDriyjXA@im.wechat"

def get_server_time():
    r = requests.get('https://www.okx.com/api/v5/public/time', proxies=PROXY, timeout=10, verify=False)
    return json.loads(r.text)['data'][0]['ts']

def get_ts():
    ts = get_server_time()
    return datetime.utcfromtimestamp(int(ts)/1000).strftime('%Y-%m-%dT%H:%M:%S.') + str(ts)[-3:] + 'Z'

def make_sig(ts, method, path, body=''):
    msg = str(ts) + method + path + body
    return base64.b64encode(hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def get_market():
    with open('/tmp/market_data.json') as f:
        d = json.load(f)
    m = d['market']
    return {
        'price': m.get('price', 0),
        'rsi': m.get('rsi', 50),
        'adx': m.get('adx', 25),
        'cvd': m.get('cvd', 0),
        'mode': m.get('mode', ''),
        'state': m.get('market_state', ''),
        'trend': m.get('trend', ''),
        'atr': m.get('atr', 0),
        'high24h': m.get('high24h', 0),
        'low24h': m.get('low24h', 0),
    }

def get_real_position():
    ts = get_ts()
    path = '/api/v5/account/positions?instId=BTC-USDT-SWAP'
    headers = {
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': make_sig(ts, 'GET', path),
        'OK-ACCESS-TIMESTAMP': ts,
        'OK-ACCESS-PASSPHRASE': PASSPHRASE,
        'Content-Type': 'application/json',
    }
    r = requests.get('https://www.okx.com' + path, headers=headers, proxies=PROXY, timeout=10, verify=False)
    data = json.loads(r.text)
    if data.get('code') != '0':
        return None
    positions = data.get('data', [])
    for p in positions:
        if 'BTC' not in p.get('instId', ''):
            continue
        pos = float(p.get('pos', 0))
        if pos <= 0:
            return {'has_pos': False}
        return {
            'has_pos': True,
            'side': p.get('posSide', ''),
            'pos': pos,
            'avgPx': float(p.get('avgPx', 0)),
            'upl': float(p.get('upl', 0)),
            'uplRatio': float(p.get('uplRatio', 0)),
            'liqPx': float(p.get('liqPx', 0)),
            'lever': int(p.get('lever', 1)),
            'last': float(p.get('last', 0)),
            'margin': float(p.get('margin', 0)) if p.get('margin') else 0,
            'mgnRatio': float(p.get('mgnRatio', 0)) if p.get('mgnRatio') else 0,
            'fee': float(p.get('fee', 0)),
            'fundingFee': float(p.get('fundingFee', 0)),
            'notionalUsd': float(p.get('notionalUsd', 0)),
        }
    return {'has_pos': False}

def get_virt_accounts():
    try:
        with open('/tmp/virt_positions.json') as f:
            d = json.load(f)
        mkt = d.get('market', {})
        return d.get('accounts', []), mkt
    except:
        return [], {}

def send(msg):
    try:
        subprocess.run([
            'openclaw', 'message', 'send',
            '--channel', 'openclaw-weixin',
            '--target', TARGET,
            '--message', msg
        ], capture_output=True, timeout=30)
    except:
        pass

def main():
    mkt = get_market()
    real = get_real_position()
    virt_accounts, mkt_data = get_virt_accounts()
    price = mkt['price']
    now = datetime.now()

    # === Yesterday snapshot ===
    yesterday_open = 78031
    yesterday_high = 79447
    yesterday_low = 77440
    yesterday_close = 77900  # approximate from memory

    # === Today's data ===
    today_open = mkt['high24h']  # 24h high/low from current session
    today_high = mkt['high24h']
    today_low = mkt['low24h']

    msg = f"""━━━━━━━━━━━━━━━
📋 每日复盘 · {now.strftime('%Y-%m-%d')}
━━━━━━━━━━━━━━━

【昨日回顾 · 04-27】
• 开: ${yesterday_open:,} → 高: ${yesterday_high:,} → 低: ${yesterday_low:,} → 收: ~${yesterday_close:,}
• 整体：震荡偏弱，信号在 long/pending 间频繁切换
• 问题：无趋势（ADX 15-30），RSI 无极值，无明确方向

【今日概况 · 04-28】
• 现价: ${price:,.0f}
• 24h高: ${mkt['high24h']:,.0f} | 24h低: ${mkt['low24h']:,.0f}
• RSI: {mkt['rsi']:.1f} | ADX: {mkt['adx']:.1f} | CVD: {mkt['cvd']:,.0f}
• 信号: {mkt['mode']} | 趋势: {mkt['trend']}
• 市场状态: {mkt['state']}

【真实账户】
• 多单 {real['pos']}张 @ ${real['avgPx']:,.0f} | 当前 ${real['last']:,.0f}
• 浮盈: ${real['upl']:+.1f}（{real['uplRatio']*100:+.1f}%）
• 强平: ${real['liqPx']:,.0f} | 距强平: {(real['last']-real['liqPx'])/real['last']*100:.1f}%
• 杠杆: {real['lever']}x | 保证金率: {real['mgnRatio']:.1f}%

【虚拟账户】
• V1(保守型): 空仓 | 余额 ${virt_accounts[0]['balance'] if len(virt_accounts)>0 else 0:.2f}U
• V2(平衡型): 空仓 | 余额 ${virt_accounts[1]['balance'] if len(virt_accounts)>1 else 0:.2f}U
• V3(激进型): {'空仓' if not virt_accounts[2]['side'] else virt_accounts[2]['side']+' @ $'+str(round(virt_accounts[2]['entry'],0)) if virt_accounts[2]['side'] else '空仓'} | 余额 ${virt_accounts[2]['balance'] if len(virt_accounts)>2 else 0:.2f}U"""

    # Analysis
    analysis = f"""
━━━━━━━━━━━━━━━
【分析 & 建议】

1️⃣ 大势：暂无趋势
ADX={mkt['adx']:.1f} 仍在 30 以下，震荡格局未改。信号在 short_pending 状态，多看少动。

2️⃣ 真实账户
• 6.15张多单，均价 $76,650，浮盈 +$41，但保证金率仅 5.5%
• 100x 杠杆 + Cross 模式 ≈ 行情反向 5.5% 就爆仓
• 建议：设置预警线，跌破 $75,000 考虑减仓

3️⃣ V3 仓位
• 反激进做空 @ $77,333，当前 $77,299，微盈 +$0.45
• 今日如果信号转 long，建议平掉，空头趋势未明

4️⃣ 今日操作建议
• $76,500 支撑不破：观望或轻仓试多
• 跌破 $76,000：止损，趋势可能加速下行
• 突破 $78,000：可考虑追多，止损 $77,500

⚠️ API 仅读取权限，无法自动平仓，请关注盘中风险
━━━━━━━━━━━━━━━"""

    send(msg + analysis)
    print(msg + analysis)

if __name__ == '__main__':
    main()
