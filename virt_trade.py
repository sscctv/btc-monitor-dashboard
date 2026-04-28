#!/usr/bin/env python3
"""
虚拟仓位动态管理系统 V3 - 三策略对比版
风险: 30%-50%本金 | 无固定止损止盈 | 根据市场信号自主判断
"""
import sqlite3
import json
import time
from datetime import datetime

DB_FILE = "/tmp/okx_trading_v3.db"
STATE_FILE = "/tmp/.virt_trade_state"
INIT_BALANCE = 1000.0

# 三种策略配置
# risk_pct: 本金的百分比作为风险敞口
STRATEGIES = {
    'V1': {'name': '保守型', 'adx_threshold': 30, 'rsi_min': 35, 'rsi_max': 65,
           'risk_pct': 0.30, 'leverage': 50, 'confirm_only': True},
    'V2': {'name': '平衡型', 'adx_threshold': 25, 'rsi_min': 30, 'rsi_max': 70,
           'risk_pct': 0.40, 'leverage': 100, 'confirm_only': True},
    'V3': {'name': '激进型', 'adx_threshold': 20, 'rsi_min': 25, 'rsi_max': 75,
           'risk_pct': 0.50, 'leverage': 100, 'confirm_only': False}
}

_state = None

def load_state():
    global _state
    if _state is not None:
        return _state
    try:
        with open(STATE_FILE) as f:
            _state = json.load(f)
    except:
        _state = {'balances': {'V1': 1015.3, 'V2': 1015.3, 'V3': 1015.3}}
    return _state

def save_state(s):
    global _state
    _state = s
    with open(STATE_FILE, 'w') as f:
        json.dump(s, f)

def get_market():
    with open('/tmp/market_data.json') as f:
        d = json.load(f)
    m = d['market']
    return {
        'price': m.get('price', 0),
        'rsi': m.get('rsi', 50),
        'adx': m.get('adx', 25),
        'cvd': m.get('cvd', 0),
        'mode': m.get('mode', 'wait'),
    }

def get_positions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT account, side, entry, size, leverage FROM positions WHERE account IN ('V1','V2','V3')")
    pos = {r[0]: {'side': r[1], 'entry': float(r[2]), 'size': float(r[3])} for r in c.fetchall()}
    conn.close()
    return pos

def should_open(acc, mkt):
    s = STRATEGIES[acc]
    mode = mkt['mode']
    adx = mkt['adx']
    rsi = mkt['rsi']

    # Pending 信号过滤
    if mode.endswith('_pending') and s['confirm_only']:
        return False
    if mode.endswith('_pending') and not s['confirm_only']:
        pass  # V3 接受 pending
    if mode == 'wait':
        return False

    # ADX 检查
    if adx < s['adx_threshold']:
        return False

    # RSI 检查
    if rsi < s['rsi_min'] or rsi > s['rsi_max']:
        return False

    return True

def should_close(acc, pos, mkt):
    """无固定止损止盈，只根据市场信号判断"""
    s = STRATEGIES[acc]
    price = mkt['price']
    entry = pos['entry']
    side = pos['side']
    size = pos['size']

    if side == 'long':
        pnl = (price - entry) * size
    else:
        pnl = (entry - price) * size

    mode = mkt['mode']
    adx = mkt['adx']

    # === 平仓信号判断 ===

    # 1. 反向信号（最强信号）
    if side == 'long' and mode in ('short', 'short_pending') and adx > s['adx_threshold']:
        return True, '反向做空', pnl
    if side == 'short' and mode in ('long', 'long_pending') and adx > s['adx_threshold']:
        return True, '反向做多', pnl

    # 2. 信号消失（之前有趋势现在变 wait）
    if mode == 'wait' and adx < s['adx_threshold']:
        return True, '信号消失', pnl

    # 3. ADX 极度走弱（无趋势延续）
    if adx < 15:
        return True, '无趋势(ADX<15)', pnl

    # 4. RSI 极端 + ADX 弱（反弹/回调预警）
    rsi = mkt['rsi']
    if side == 'long' and rsi > 80 and adx < 25:
        return True, 'RSI极端超买', pnl
    if side == 'short' and rsi < 20 and adx < 25:
        return True, 'RSI极端超卖', pnl

    # 5. CVD 严重背离
    cvd = mkt['cvd']
    if side == 'long' and cvd < -500 and adx < 25:
        return True, 'CVD背离', pnl
    if side == 'short' and cvd > 500 and adx < 25:
        return True, 'CVD背离', pnl

    return False, '', pnl

def open_pos(acc, side, price):
    s = STRATEGIES[acc]
    balance = load_state()['balances'].get(acc, INIT_BALANCE)

    # 仓位计算：风险敞口 = 本金 × risk_pct
    risk_amount = balance * s['risk_pct']
    # 名义本金 = 风险金额 × 杠杆
    notional = risk_amount * s['leverage']
    # 开仓数量（BTC）
    size = notional / price

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO positions (account, side, entry, size, leverage, opened_at) VALUES (?, ?, ?, ?, ?, ?)",
              (acc, side, price, size, s['leverage'], now))
    conn.commit()
    conn.close()

    print(f"[{now[-8:]}] {acc}({s['name']}): 开{side} @ ${price:.2f} | 风险{float(s['risk_pct'])*100:.0f}%=\${risk_amount:.1f}U | {s['leverage']}X | 数量={size:.4f}BTC | 余额={balance:.1f}U")

def close_pos(acc, pos, reason, pnl):
    s = STRATEGIES[acc]
    balance = load_state()['balances'].get(acc, INIT_BALANCE)
    new_balance = balance + pnl

    state = load_state()
    state['balances'][acc] = new_balance
    save_state(state)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO trades (account, action, side, entry, exit_price, pnl, size, leverage, strategy, traded_at) VALUES (?, 'close', ?, ?, ?, ?, ?, ?, ?, ?)",
              (acc, pos['side'], pos['entry'], pos.get('current', pos['entry']), round(pnl, 2), pos['size'], s['leverage'], f"{s['leverage']}X-{s['name']}", now))
    c.execute("DELETE FROM positions WHERE account=?", (acc,))
    conn.commit()
    conn.close()

    print(f"[{now[-8:]}] {acc}({s['name']}): 平仓 {reason} | {pnl:+.2f}U | 新余额={new_balance:.1f}U")

def sync_supabase(acc, balance, pos=None):
    import urllib.request
    sb = 'YOUR_SUPABASE_SECRET_HERE'
    BASE = 'https://lpcrnobolifrzwrkxoli.supabase.co/rest/v1'

    # 更新余额
    url = f'{BASE}/btc_accounts?account_id=eq.{acc}'
    headers = {'apikey': sb, 'Authorization': f'Bearer {sb}', 'Content-Type': 'application/json', 'Prefer': 'return=representation'}
    data = [{'capital': round(balance, 2), 'strategy': f"{STRATEGIES[acc]['leverage']}X-{STRATEGIES[acc]['name']}", 'status': 'open' if pos else 'idle'}]
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method='PATCH')
    try:
        urllib.request.urlopen(req, timeout=5)
    except:
        pass

    if pos:
        mkt = get_market()
        price = mkt['price']
        s = STRATEGIES[acc]

        if pos['side'] == 'long':
            unreal = (price - pos['entry']) * pos['size']
        else:
            unreal = (pos['entry'] - price) * pos['size']

        record = {
            'account_id': acc, 'side': pos['side'], 'entry_price': pos['entry'],
            'size': pos['size'], 'leverage': s['leverage'],
            'status': 'open', 'opened_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'unrealizedpnl': round(unreal, 4),
            'strategy': f"{s['leverage']}X-{s['name']}",
            'current_price': round(price, 2),  # 修复：同步当前价格
        }

        # 删除旧的，插入新的
        del_req = urllib.request.Request(f'{BASE}/btc_trades?account_id=eq.{acc}&status=eq.open',
                                         headers={'apikey': sb, 'Authorization': f'Bearer {sb}'}, method='DELETE')
        try:
            urllib.request.urlopen(del_req, timeout=5)
        except:
            pass

        # 插入新记录
        url2 = f'{BASE}/btc_trades'
        headers2 = {'apikey': sb, 'Authorization': f'Bearer {sb}', 'Content-Type': 'application/json', 'Prefer': 'return=representation'}
        req2 = urllib.request.Request(url2, data=json.dumps(record).encode(), headers=headers2)
        try:
            urllib.request.urlopen(req2, timeout=5)
        except:
            pass
        
        # 同时更新 btc_accounts 的 status
        url3 = f'{BASE}/btc_accounts?account_id=eq.{acc}'
        acc_data = [{'status': 'open', 'capital': round(balance, 2)}]
        req3 = urllib.request.Request(url3, data=json.dumps(acc_data).encode(), headers=headers2, method='PATCH')
        try:
            urllib.request.urlopen(req3, timeout=5)
        except:
            pass

def write_json(mkt, positions, balances):
    out = {'market': mkt, 'accounts': [], 'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    for acc in ['V1', 'V2', 'V3']:
        s = STRATEGIES[acc]
        bal = balances.get(acc, INIT_BALANCE)
        pos = positions.get(acc)
        if pos:
            price = mkt['price']
            unreal = (price - pos['entry']) * pos['size'] if pos['side'] == 'long' else (pos['entry'] - price) * pos['size']
            pct = abs(price - pos['entry']) / pos['entry'] * 100
            out['accounts'].append({
                'account': acc, 'strategy': s['name'], 'side': pos['side'],
                'entry': round(pos['entry'], 2), 'current': round(price, 2),
                'size': round(pos['size'], 6), 'leverage': s['leverage'],
                'unrealized_pnl': round(unreal, 2), 'profit_pct': round(pct, 3),
                'balance': round(bal, 2), 'status': '持仓中'
            })
        else:
            out['accounts'].append({
                'account': acc, 'strategy': s['name'], 'side': None,
                'entry': None, 'current': round(mkt['price'], 2),
                'size': 0, 'leverage': s['leverage'],
                'unrealized_pnl': 0, 'profit_pct': 0,
                'balance': round(bal, 2), 'status': '空仓'
            })
    with open('/tmp/virt_positions.json', 'w') as f:
        json.dump(out, f, ensure_ascii=False)

def run():
    mkt = get_market()
    positions = get_positions()
    state = load_state()
    bals = state.get('balances', {'V1': 1015.3, 'V2': 1015.3, 'V3': 1015.3})

    now_str = datetime.now().strftime('%H:%M:%S')
    print(f"\n[{now_str}] === 虚拟仓位检查 ===")
    print(f"市场: ${mkt['price']:.2f} | RSI:{mkt['rsi']:.1f} | ADX:{mkt['adx']:.1f} | CVD:{mkt['cvd']:.0f} | 信号:{mkt['mode']}")

    # 检查平仓（信号驱动，无固定SL/TP）
    for acc in ['V1', 'V2', 'V3']:
        pos = positions.get(acc)
        if not pos:
            continue
        flag, reason, pnl = should_close(acc, pos, mkt)
        if flag:
            close_pos(acc, pos, reason, pnl)
            bals = load_state()['balances']
            sync_supabase(acc, bals[acc], None)

    positions = get_positions()

    # 检查开仓
    for acc in ['V1', 'V2', 'V3']:
        pos = positions.get(acc)
        if pos:
            continue
        if should_open(acc, mkt):
            side = 'long' if mkt['mode'].startswith('long') else 'short'
            open_pos(acc, side, mkt['price'])
            positions = get_positions()
            sync_supabase(acc, bals[acc], positions.get(acc))

    # 同步
    positions = get_positions()
    bals = load_state()['balances']
    for acc in ['V1', 'V2', 'V3']:
        sync_supabase(acc, bals[acc], positions.get(acc))
    write_json(mkt, positions, bals)

    vstr = " | ".join([f"V{i}:{load_state()['balances'].get(f'V{i}',INIT_BALANCE):.0f}U" for i in range(1,4)])
    print(f"[{now_str}] BTC=${mkt['price']:.0f} RSI={mkt['rsi']:.0f} ADX={mkt['adx']:.0f} | {vstr}")

def main():
    print("="*60)
    print("虚拟仓位 V3 - 三策略对比版（风险30%-50%，无固定止损止盈）")
    print("V1 保守型: ADX≥30, RSI 35-65, 风险30%, 50X")
    print("V2 平衡型: ADX≥25, RSI 30-70, 风险40%, 100X")
    print("V3 激进型: ADX≥20, RSI 25-75, 风险50%, 100X")
    print("="*60)

    while True:
        try:
            run()
        except Exception as e:
            print(f"错误: {e}")
        time.sleep(15)

if __name__ == '__main__':
    main()
