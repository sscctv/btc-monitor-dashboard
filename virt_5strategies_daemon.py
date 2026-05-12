#!/usr/bin/env python3
"""
BTC 5策略虚拟交易 - 守护进程
每5秒检查信号并执行交易
每小时发送复盘报告
"""

import psycopg2
import numpy as np
import json
import os
import time
import signal
import sys
import requests
from datetime import datetime, timezone, timedelta

# Supabase配置
SUPABASE_URL = "https://lpcrnobolifrzwrkxoli.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_SECRET"
SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# 数据库配置
DB_CONFIG = {
    'host': '192.168.1.2',
    'port': 5432,
    'user': 'postgres',
    'password': 'Postgres@2026',
    'dbname': 'postgres'
}

# 5个策略
STRATEGIES = [
    {'name': 'BB收缩+三批 30x', 'sig': 'bb_squeeze', 'tp': 'triple', 'lev': 30},
    {'name': 'BB收缩+分批 30x', 'sig': 'bb_squeeze', 'tp': 'partial', 'lev': 30},
    {'name': 'BB收缩+三批 25x', 'sig': 'bb_squeeze', 'tp': 'triple', 'lev': 25},
    {'name': 'BB收缩+分批 25x', 'sig': 'bb_squeeze', 'tp': 'partial', 'lev': 25},
    {'name': 'BB收缩+三批 20x', 'sig': 'bb_squeeze', 'tp': 'triple', 'lev': 20},
]

INITIAL_CAPITAL = 1000
STATE_FILE = '/tmp/virt_5state.json'
REPORT_FILE = '/tmp/virt_5report.json'

running = True

def signal_handler(signum, frame):
    global running
    print("\n🛑 收到停止信号，正在关闭...")
    running = False

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, connect_timeout=5)

def get_latest_candles(limit=100):
    """获取最新K线"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT ts, dt, o, h, l, c, vol 
            FROM okx.candles 
            WHERE inst_id = 'BTC-USDT-SWAP' AND bar = '1m' 
            ORDER BY ts DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        candles = [{'ts':r[0],'dt':r[1],'open':float(r[2]),'high':float(r[3]),'low':float(r[4]),'close':float(r[5]),'vol':float(r[6])} for r in rows]
        candles.reverse()
        return candles
    except:
        return None

def calc_bb(candles, i, closes, period=20, mult=2.0):
    if i < period + 5:
        return None, None, None
    window = closes[i-period:i+1]
    ma = np.mean(window)
    std = np.std(window)
    return ma - mult*std, ma, ma + mult*std

def check_signal(candles, i, closes, sig_type):
    if sig_type == 'bb_squeeze':
        if i < 30:
            return False
        lower, mid, upper = calc_bb(candles, i, closes)
        if lower is None:
            return False
        bandwidth = (upper - lower) / mid * 100
        vr = candles[i]['vol'] / np.mean([c['vol'] for c in candles[i-20:i]])
        return bandwidth < 1.5 and vr > 3
    return False

def check_tp_sl(pos, candle, tp_type, capital, lev):
    entry = pos['entry']
    high = candle['high']
    low = candle['low']
    close = candle['close']
    
    if tp_type == 'triple':
        pos['high'] = max(pos.get('high', entry), high)
        remaining = 1.0
        pnl_total = 0
        close_all = False
        
        if not pos.get('closed1') and high >= pos['tp1']:
            pnl = capital * 0.333 * lev * 0.015
            pnl_total += pnl
            remaining -= 0.333
            pos['closed1'] = True
            pos['sl'] = high * (1 - pos['trail'])
        
        if not pos.get('closed2') and high >= pos['tp2']:
            pnl = capital * remaining * lev * ((high - entry) / entry)
            pnl_total += pnl
            remaining = 0
            pos['closed2'] = True
            close_all = True
        
        if not close_all and high > pos.get('tp3', pos['tp2']):
            pos['tp3'] = high * 1.002
            pos['sl'] = max(pos['sl'], high * (1 - pos['trail']))
        
        if not close_all and high >= pos.get('tp3', pos['tp2']):
            pnl = capital * remaining * lev * ((high - entry) / entry)
            pnl_total += pnl
            remaining = 0
            close_all = True
        
        if pnl_total > 0:
            return pnl_total, remaining, close_all
        return 0, remaining, close_all
    
    elif tp_type == 'partial':
        pos['high'] = max(pos.get('high', entry), high)
        
        if not pos.get('half') and high >= pos['tp1']:
            pnl = capital * lev * 0.01
            pos['half'] = True
            pos['sl'] = high * 0.995
            return pnl, 0.5, False
        
        if high >= pos['tp1'] * 1.02:
            pnl = capital * lev * ((high - entry) / entry)
            return pnl, 0, True
        
        return 0, 1.0, False
    
    return 0, 1.0, False

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return None

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def sync_to_supabase(name, trade_data):
    """同步交易到Supabase"""
    try:
        data = {
            'account_id': '虚拟5策略',
            'strategy': name,
            'side': 'long',
            'entry_price': trade_data.get('entry'),
            'exit_price': trade_data.get('exit'),
            'close_price': trade_data.get('exit'),
            'size': 1,
            'leverage': trade_data.get('leverage'),
            'status': 'closed' if trade_data.get('exit') else 'open',
            'realized_pnl': trade_data.get('pnl'),
            'opened_at': trade_data.get('opened_at'),
            'closed_at': trade_data.get('closed_at'),
        }
        url = f"{SUPABASE_URL}/rest/v1/btc_trades"
        r = requests.post(url, headers=SB_HEADERS, json=data)
        return r.status_code == 201
    except:
        return False

def sync_signal_to_supabase(name, signal_type, price):
    """同步信号到Supabase"""
    try:
        data = {
            'signal_type': signal_type,
            'price': price,
            'strategy': name,
        }
        url = f"{SUPABASE_URL}/rest/v1/btc_signals"
        r = requests.post(url, headers=SB_HEADERS, json=data)
        return r.status_code == 201
    except:
        return False

def upload_virt_positions(state, current_price):
    """上传虚拟持仓到Supabase Storage供前端页面显示"""
    try:
        # 构建前端需要的格式
        accounts = []
        for s in STRATEGIES:
            name = s['name']
            strat = state['strategies'].get(name, {})
            pos = strat.get('pos')
            capital = strat.get('capital', INITIAL_CAPITAL)
            
            acc = {
                'account': name,
                'balance': capital,
                'strategy': f"{s['lev']}X-{name}",
                'side': None,
                'entry': None,
                'current': current_price,
                'profit_pct': 0,
                'size': 0,
                'leverage': s['lev']
            }
            
            if pos:
                acc['side'] = 'long'
                acc['entry'] = pos['entry']
                acc['size'] = capital * s['lev'] / current_price
                acc['profit_pct'] = (current_price - pos['entry']) / pos['entry'] * 100
            
            accounts.append(acc)
        
        virt_data = {
            'updated_at': datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S'),
            'market': {
                'price': current_price,
                'mode': 'wait'
            },
            'accounts': accounts
        }
        
        # 上传到Supabase Storage
        import base64
        data_bytes = json.dumps(virt_data).encode('utf-8')
        
        upload_url = f"{SUPABASE_URL}/storage/v1/object/virt-data/virt_positions.json"
        headers = SB_HEADERS.copy()
        headers['Content-Type'] = 'application/json'
        headers['x-upsert'] = 'true'
        
        r = requests.put(upload_url, headers=headers, data=data_bytes)
        
        if r.status_code in [200, 201]:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 已上传virt_positions.json到Supabase Storage")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 上传失败: {r.status_code} {r.text[:100]}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 上传异常: {e}")

def init_state():
    state = {
        'started_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'last_update': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'strategies': {}
    }
    for s in STRATEGIES:
        state['strategies'][s['name']] = {
            'capital': INITIAL_CAPITAL,
            'initial': INITIAL_CAPITAL,
            'pos': None,
            'trades': [],
            'stats': {'total_trades': 0, 'wins': 0, 'losses': 0}
        }
    save_state(state)
    return state

def run_trade():
    """执行单次交易检查"""
    candles = get_latest_candles(100)
    if candles is None or len(candles) < 50:
        return None
    
    closes = [c['close'] for c in candles]
    current_price = closes[-1]
    state = load_state()
    if state is None:
        state = init_state()
    
    state['last_update'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    changed = False
    
    for s in STRATEGIES:
        name = s['name']
        sig_type = s['sig']
        tp_type = s['tp']
        lev = s['lev']
        
        strat = state['strategies'][name]
        capital = strat['capital']
        pos = strat['pos']
        
        # 检查信号
        sig = check_signal(candles, len(candles)-1, closes, sig_type)
        
        # 开仓
        if pos is None and sig:
            entry = current_price
            if tp_type == 'triple':
                pos = {
                    'entry': entry,
                    'open_dt': candles[-1]['dt'],
                    'tp1': entry * 1.015,
                    'tp2': entry * 1.03,
                    'sl': entry * 0.985,
                    'trail': 0.003,
                    'closed1': False,
                    'closed2': False,
                    'high': entry
                }
            elif tp_type == 'partial':
                pos = {
                    'entry': entry,
                    'open_dt': candles[-1]['dt'],
                    'tp1': entry * 1.02,
                    'sl': entry * 0.985,
                    'half': False,
                    'high': entry
                }
            strat['pos'] = pos
            changed = True
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {name} 开仓 @ ${entry:,.2f}")
            
            # 同步开仓信号到Supabase
            sync_signal_to_supabase(name, 'OPEN', entry)
        
        # 持仓检查
        elif pos is not None:
            entry = pos['entry']
            pnl, remaining, close_all = check_tp_sl(pos, candles[-1], tp_type, capital, lev)
            
            if pnl > 0:
                capital += pnl
                strat['stats']['total_trades'] += 1
                if pnl > 0:
                    strat['stats']['wins'] += 1
                else:
                    strat['stats']['losses'] += 1
                
                strat['trades'].append({
                    'dt': candles[-1]['dt'],
                    'entry': entry,
                    'exit': candles[-1]['close'],
                    'pnl': pnl,
                    'type': 'CLOSE' if close_all else 'PARTIAL'
                })
                
                # 同步到Supabase
                sync_to_supabase(name, {
                    'entry': entry,
                    'exit': candles[-1]['close'],
                    'pnl': pnl,
                    'leverage': lev,
                    'opened_at': pos.get('open_dt') if close_all else None,
                    'closed_at': candles[-1]['dt'] if close_all else None,
                })
                
                if close_all:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ {name} 平仓 {'+' if pnl > 0 else ''}${pnl:,.2f} @ ${candles[-1]['close']:,.2f}")
                    pos = None
                    capital += pnl
                
                strat['capital'] = capital
                changed = True
            
            # 止损
            if pos and candles[-1]['low'] <= pos['sl']:
                pnl = capital * lev * ((pos['sl'] - entry) / entry)
                capital += pnl
                strat['stats']['total_trades'] += 1
                if pnl > 0:
                    strat['stats']['wins'] += 1
                else:
                    strat['stats']['losses'] += 1
                
                strat['trades'].append({
                    'dt': candles[-1]['dt'],
                    'entry': entry,
                    'exit': pos['sl'],
                    'pnl': pnl,
                    'type': 'SL'
                })
                
                # 同步到Supabase
                sync_to_supabase(name, {
                    'entry': entry,
                    'exit': pos['sl'],
                    'pnl': pnl,
                    'leverage': lev,
                    'opened_at': pos.get('open_dt'),
                    'closed_at': candles[-1]['dt'],
                })
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 {name} 止损 ${pnl:,.2f}")
                pos = None
                strat['capital'] = capital
                changed = True
        
        if pos is not None:
            pos['high'] = max(pos.get('high', 0), current_price)
        
        strat['pos'] = pos
    
    if changed:
        save_state(state)
    
    # 构建报告
    results = []
    for s in STRATEGIES:
        name = s['name']
        strat = state['strategies'][name]
        capital = strat['capital']
        pos = strat['pos']
        
        current_pnl = 0
        if pos:
            current_pnl = capital * s['lev'] * ((current_price - pos['entry']) / pos['entry'])
        
        total_value = capital + current_pnl
        ret = (total_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        trades = strat['stats']['total_trades']
        wins = strat['stats']['wins']
        win_rate = wins / trades * 100 if trades > 0 else 0
        
        results.append({
            'name': name,
            'lev': s['lev'],
            'capital': capital,
            'current_pnl': current_pnl,
            'total_value': total_value,
            'return': ret,
            'pos': pos is not None,
            'trades': trades,
            'wins': wins,
            'win_rate': win_rate
        })
    
    total_capital = sum([r['capital'] for r in results])
    total_value = sum([r['total_value'] for r in results])
    total_return = (total_value - INITIAL_CAPITAL * 5) / (INITIAL_CAPITAL * 5) * 100
    total_trades = sum([r['trades'] for r in results])
    total_wins = sum([r['wins'] for r in results])
    
    report = {
        'timestamp': state['last_update'],
        'btc_price': current_price,
        'strategies': results,
        'summary': {
            'total_capital': total_capital,
            'total_value': total_value,
            'total_return': total_return,
            'total_trades': total_trades,
            'total_wins': total_wins
        }
    }
    
    with open(REPORT_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    return report

def send_hourly_report():
    """发送每小时报告"""
    try:
        with open(REPORT_FILE, 'r') as f:
            report = json.load(f)
    except:
        return
    
    timestamp = report['timestamp']
    btc_price = report['btc_price']
    strategies = report['strategies']
    summary = report['summary']
    
    now = datetime.now(timezone(timedelta(hours=8)))
    
    lines = []
    lines.append(f"📊 **5策略虚拟交易 · 每小时复盘**")
    lines.append(f"🕐 {now.strftime('%H:%M')} | BTC ${btc_price:,.0f}")
    lines.append("")
    
    for s in strategies:
        name = s['name']
        ret = s['return']
        pos = s['pos']
        trades = s['trades']
        wr = s['win_rate']
        
        status = "🟢" if pos else "⚪"
        lines.append(f"{status} {name}")
        lines.append(f"   {'+' if ret >= 0 else ''}{ret:.1f}% | {trades}笔 | 胜率{wr:.0f}%")
    
    total_ret = summary['total_return']
    total_trades = summary['total_trades']
    total_wins = summary['total_wins']
    wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    
    lines.append("")
    lines.append(f"💎 汇总 | 总收益{total_ret:+.1f}% | {total_trades}笔 | 胜率{wr:.0f}%")
    
    message = "\n".join(lines)
    
    # 发送到微信
    try:
        import requests
        url = "http://localhost:8080/api/send"
        requests.post(url, json={
            "channel": "openclaw-weixin",
            "target": "o9cq801cl6QXRfJWhroBxDriyjXA@im.wechat",
            "message": message,
            "token": "4d3a8fa658af479d8743750e5fff818e"
        }, timeout=5)
        print(f"[{now.strftime('%H:%M:%S')}] 📱 已发送每小时报告")
    except:
        pass

def main():
    global running
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"🚀 BTC 5策略虚拟交易守护进程启动")
    print(f"   每5秒检查信号")
    print(f"   每小时发送报告")
    print(f"   Ctrl+C 停止")
    
    # 初始化状态
    state = load_state()
    if state is None:
        print("📝 初始化新状态...")
        state = init_state()
    
    last_report_hour = None
    
    while running:
        try:
            report = run_trade()
            
            # 上传virt_positions到Supabase Storage供前端展示
            state = load_state()
            if state and report:
                upload_virt_positions(state, report['btc_price'])
            
            # 检查是否需要发送每小时报告
            now = datetime.now(timezone(timedelta(hours=8)))
            current_hour = now.hour
            
            if last_report_hour != current_hour:
                last_report_hour = current_hour
                send_hourly_report()
            
            time.sleep(5)  # 每5秒
            
        except Exception as e:
            print(f"错误: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
