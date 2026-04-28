#!/usr/bin/env python3
"""
综合监控系统 - 模拟账户 + 真实账户
"""
import sqlite3, json, time, subprocess, hashlib, hmac, base64, requests, warnings
from datetime import datetime
from dataclasses import dataclass

warnings.filterwarnings('ignore')

DB_FILE = "/tmp/okx_trading_v3.db"
STATE_FILE = "/tmp/.monitor_state"
TARGET = "o9cq801cl6QXRfJWhroBxDriyjXA@im.wechat"

# OKX API
API_KEY = "c72740a8-71ab-41ba-bef5-e7640e3efac9"
SECRET_KEY = "6E1EA8F850D168D5D47C8155A6460F06"
PASSPHRASE = "Jiege#@/123"
PROXY = {"http": "http://172.17.0.1:7890", "https": "http://172.17.0.1:7890"}
VERIFY = False

def get_server_time():
    from datetime import datetime, timezone
    r = requests.get('https://www.okx.com/api/v5/public/time', proxies=PROXY, timeout=10, verify=VERIFY)
    server_ts = json.loads(r.text)['data'][0]['ts']
    return datetime.utcfromtimestamp(int(server_ts) / 1000).strftime('%Y-%m-%dT%H:%M:%S.') + str(server_ts)[-3:] + 'Z'

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
        'state': m.get('market_state', 'oscillation'),
        'trend': m.get('trend', 'neutral'),
        'atr': m.get('atr', 200),
    }

def make_sig(ts, method, path, body=''):
    message = str(ts) + method + path + body
    mac = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def get_sim_positions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT account, side, entry, sl, tp, size, leverage, strategy FROM positions")
    rows = c.fetchall()
    conn.close()
    return [{'account':r[0],'side':r[1],'entry':r[2],'sl':r[3],'tp':r[4],'size':r[5],'leverage':r[6],'strategy':r[7]} for r in rows]

def get_virt_positions():
    """获取 V1, V2, V3 虚拟仓位"""
    return [p for p in get_sim_positions() if p['account'] in ('V1','V2','V3')]

def check_virt_position(pos, mkt):
    """检查 V1/V2/V3 虚拟仓位是否该平仓"""
    price = mkt['price']
    entry = pos['entry']
    side = pos['side']
    size = pos['size']
    
    # 计算浮盈
    if side == 'long':
        unreal = (price - entry) * size
        # 检查止盈止损
        tp = entry * 1.01  # 1%
        sl = entry * 0.995  # 0.5%
    else:
        unreal = (entry - price) * size
        tp = entry * 0.99
        sl = entry * 1.005
    
    should_close = False
    reason = ""
    action = "HOLD"
    
    if side == 'long':
        if price >= tp:
            should_close = True
            reason = f"触及止盈 TP=${tp:.0f}"
            action = "TAKE_PROFIT"
        elif price <= sl:
            should_close = True
            reason = f"触及止损 SL=${sl:.0f}"
            action = "STOP_LOSS"
    else:
        if price <= tp:
            should_close = True
            reason = f"触及止盈 TP=${tp:.0f}"
            action = "TAKE_PROFIT"
        elif price >= sl:
            should_close = True
            reason = f"触及止损 SL=${sl:.0f}"
            action = "STOP_LOSS"
    
    # 信号反转也该平
    if side == 'long' and mkt['mode'] in ('short', 'short_pending'):
        should_close = True
        reason = f"信号反转 {mkt['mode']}"
        action = "SIGNAL_REVERSE"
    elif side == 'short' and mkt['mode'] in ('long', 'long_pending'):
        should_close = True
        reason = f"信号反转 {mkt['mode']}"
        action = "SIGNAL_REVERSE"
    
    return {
        'should_close': should_close,
        'reason': reason,
        'action': action,
        'unreal': unreal,
        'tp': tp,
        'sl': sl
    }

def close_virt_position(pos, mkt, action, reason):
    """平掉虚拟仓位并更新余额"""
    price = mkt['price']
    entry = pos['entry']
    size = pos['size']
    
    if pos['side'] == 'long':
        pnl = (price - entry) * size
    else:
        pnl = (entry - price) * size
    
    # 更新余额
    old_balance = 1000.0
    new_balance = old_balance + pnl
    
    # 从本地删除持仓
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM positions WHERE account=?", (pos['account'],))
    conn.commit()
    conn.close()
    
    return {'pnl': pnl, 'new_balance': new_balance, 'reason': reason}

def get_real_position():
    try:
        ts = get_server_time()
        path = '/api/v5/account/positions?instType=SWAP'
        headers = {
            'OK-ACCESS-KEY': API_KEY,
            'OK-ACCESS-SIGN': make_sig(ts, 'GET', path),
            'OK-ACCESS-TIMESTAMP': ts,
            'OK-ACCESS-PASSPHRASE': PASSPHRASE,
            'Content-Type': 'application/json',
        }
        r = requests.get('https://www.okx.com' + path, headers=headers, proxies=PROXY, timeout=10, verify=VERIFY)
        data = json.loads(r.text)
        
        if data.get('code') != '0':
            return None
        
        positions = data.get('data', [])
        mkt = get_market()
        
        for p in positions:
            inst = p.get('instId', '')
            if 'BTC' not in inst:
                continue
            pos = float(p.get('pos', 0))
            if pos <= 0:
                return {'has_pos': False}
            
            side = p.get('posSide', '')
            avg_px = float(p.get('avgPx', 0))
            upl = float(p.get('upl', 0))
            liq_px = float(p.get('liqPx', 0))
            lev = float(p.get('lever', 1))
            
            if side == 'long':
                dist_liq = (mkt['price'] - liq_px) / mkt['price'] * 100 if liq_px else 0
            else:
                dist_liq = (liq_px - mkt['price']) / mkt['price'] * 100 if liq_px else 0
            
            return {
                'has_pos': True,
                'inst': inst,
                'side': side,
                'pos': pos,
                'avg_px': avg_px,
                'upl': upl,
                'liq_px': liq_px,
                'lever': lev,
                'dist_liq': dist_liq,
                'mkt': mkt
            }
        return {'has_pos': False}
    except Exception as e:
        return {'error': str(e)}

def should_alert_real(pos_data):
    """判断真实账户是否需要警报"""
    if not pos_data or not pos_data.get('has_pos'):
        return None
    
    mkt = pos_data['mkt']
    side = pos_data['side']
    dist_liq = pos_data['dist_liq']
    upl = pos_data['upl']
    
    alerts = []
    
    # 1. 强平风险
    if dist_liq < 2:
        alerts.append(('critical', f"🚨 距离强平仅 {dist_liq:.1f}%，极度危险！"))
    elif dist_liq < 5:
        alerts.append(('warning', f"⚠️ 距离强平 {dist_liq:.1f}%，注意风险"))
    
    # 2. 信号反转
    if side == 'long' and mkt['mode'] in ('short', 'short_pending'):
        alerts.append(('critical', f"🔴 信号反转为 {mkt['mode']}，多仓危险！"))
    elif side == 'short' and mkt['mode'] in ('long', 'long_pending'):
        alerts.append(('critical', f"🔴 信号反转为 {mkt['mode']}，空仓危险！"))
    
    # 3. RSI 极端
    if side == 'long' and mkt['rsi'] > 75 and mkt['adx'] > 40:
        alerts.append(('warning', f"⚠️ RSI超买({mkt['rsi']:.1f})，考虑止盈"))
    elif side == 'short' and mkt['rsi'] < 25 and mkt['adx'] > 40:
        alerts.append(('warning', f"⚠️ RSI超卖({mkt['rsi']:.1f})，考虑止盈"))
    
    # 4. 无趋势
    if mkt['adx'] < 15:
        alerts.append(('warning', f"⚠️ 无趋势(ADX={mkt['adx']:.1f})，震荡风险"))
    
    return alerts if alerts else None

def send_wechat(msg, short=False):
    """发送微信通知，short=True时只发一行简洁消息"""
    try:
        if short:
            # 简洁格式：一行
            subprocess.run([
                'openclaw', 'message', 'send',
                '--channel', 'openclaw-weixin',
                '--target', TARGET,
                '--message', msg
            ], capture_output=True, text_timeout=30)
        else:
            subprocess.run([
                'openclaw', 'message', 'send',
                '--channel', 'openclaw-weixin',
                '--target', TARGET,
                '--message', msg
            ], capture_output=True, text_timeout=30)
        return True
    except:
        return False

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {'last_real_alert': None, 'last_report': None}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def main():
    state = load_state()
    mkt = get_market()
    sim_positions = get_sim_positions()
    real = get_real_position()
    
    now = datetime.now()
    alerts_to_send = []
    
    # === V1/V2/V3 虚拟仓位检查 ===
    virt_positions = get_virt_positions()
    for pos in virt_positions:
        result = check_virt_position(pos, mkt)
        if result['should_close']:
            close_result = close_virt_position(pos, mkt, result['action'], result['reason'])
            emoji = "🎯" if close_result['pnl'] >= 0 else "🛑"
            msg = f"""━━━━━━━━━━━━━━━
{emoji} V{pos['account'][1]} 模拟仓位平仓
━━━━━━━━━━━━━━━
方向: {pos['side'].upper()} @ ${pos['entry']:.0f}
平仓价: ${mkt['price']:.0f}
━━━━━━━━━━━━━━━
盈亏: {'+' if close_result['pnl']>=0 else ''}{close_result['pnl']:.1f}U
余额: ${close_result['new_balance']:.1f}U
原因: {result['reason']}
━━━━━━━━━━━━━━━"""
            print(msg)
            send_wechat(msg)
    
    # === 信号检测 ===
    # === 信号检测 ===
    mkt = get_market()
    if mkt['mode'] in ('long', 'long_pending', 'short', 'short_pending'):
        last_signal = state.get('last_signal')
        if last_signal != mkt['mode']:
            # 合并为一条消息
            entry = sim_positions[0]['entry'] if sim_positions else mkt['price']
            tp_price = entry * 1.02 if 'long' in mkt['mode'] else entry * 0.98
            sl_price = entry * 0.985 if 'long' in mkt['mode'] else entry * 1.015
            
            emoji = "🟢" if 'long' in mkt['mode'] else "🔴"
            direction = "做多" if 'long' in mkt['mode'] else "做空"
            pending = "（待确认）" if 'pending' in mkt['mode'] else ""
            
            msg = f"""━━━━━━━━━━━━━━━
{'🔔 BTC' + direction + '信号通知' + pending}
━━━━━━━━━━━━━━━
📊 市场: ${mkt['price']:,.0f}
📈 RSI: {mkt['rsi']:.1f} | ADX: {mkt['adx']:.1f}
📉 CVD: {mkt['cvd']:,.0f}
🔔 信号: {mkt['mode']}
━━━━━━━━━━━━━━━
🎯 建议止盈: ${tp_price:,.0f}
🛑 建议止损: ${sl_price:,.0f}
⚠️ 仅供参考，风险自担"""
            print(msg)
            send_wechat(msg)
            state['last_signal'] = mkt['mode']
    
    # === 真实账户检查 ===
    if real and 'error' not in real:
        if real.get('has_pos'):
            emoji = "🟢" if real['side'] == 'long' else "🔴"
            mkt = real['mkt']
            
            msg = f"""
━━━━━━━━━━━━━━━
{emoji} 真实账户监控
━━━━━━━━━━━━━━━
BTC: ${mkt['price']:.0f} | RSI: {mkt['rsi']:.1f}
信号: {mkt['mode']} | ADX: {mkt['adx']:.1f}
━━━━━━━━━━━━━━━
方向: {emoji} {real['side'].upper()}
持仓: {real['pos']} 张
均价: ${real['avg_px']:.2f}
━━━━━━━━━━━━━━━
浮盈: {real['upl']:+.2f} U
强平价: ${real['liq_px']:.2f}
距强平: {real['dist_liq']:.1f}%
杠杆: {real['lever']}X
━━━━━━━━━━━━━━━"""
            
            # 检查是否需要警报
            alert_conditions = should_alert_real(real)
            
            if alert_conditions:
                for sev, reason in alert_conditions:
                    if sev == 'critical':
                        alerts_to_send.append(('real_critical', reason))
                    elif sev == 'warning':
                        alerts_to_send.append(('real_warning', reason))
                
                # 添加止盈止损建议
                entry = real['avg_px']
                m = real['mkt']
                if real['side'] == 'long':
                    tp = entry * 1.015  # 1.5%止盈
                    sl = entry * 0.995   # 0.5%止损
                else:
                    tp = entry * 0.985
                    sl = entry * 1.005
                
                detail = f"""
━━━━━━━━━━━━━━━
📌 建议操作参考
━━━━━━━━━━━━━━━
🎯 止盈参考: ${tp:,.2f}
🛑 止损参考: ${sl:,.2f}
⚠️ 风险自担，仅供参考"""
                alerts_to_send.append(('real_detail', detail))
            else:
                # 每30分钟常规报告
                last = state.get('last_real_report')
                if not last or (now - datetime.strptime(last, '%Y-%m-%d %H:%M:%S')).total_seconds() > 1800:
                    send_wechat(msg)
                    state['last_real_report'] = now.strftime('%Y-%m-%d %H:%M:%S')
        else:
            # 无持仓，每小时检查一次
            last = state.get('last_real_report')
            if not last or (now - datetime.strptime(last, '%Y-%m-%d %H:%M:%S')).total_seconds() > 3600:
                mkt = get_market()
                send_wechat(f"✅ 真实账户：无持仓 | BTC: ${mkt['price']:.0f}")
                state['last_real_report'] = now.strftime('%Y-%m-%d %H:%M:%S')
    elif real and 'error' in real:
        print(f"真实账户查询错误: {real['error']}")
    
    # === 发送警报（简洁一行格式）===
    for alert_type, msg_body in alerts_to_send:
        last_key = f'last_{alert_type}'
        last = state.get(last_key)
        # 防止重复发送（5分钟内不重复）
        if not last or (now - datetime.strptime(last, '%Y-%m-%d %H:%M:%S')).total_seconds() > 300:
            print(msg_body)
            send_wechat(msg_body, short=True)
            state[last_key] = now.strftime('%Y-%m-%d %H:%M:%S')
    
    save_state(state)
    
    # 简洁输出
    real_info = ""
    if real and 'error' not in real and real.get('has_pos'):
        emoji = "🟢" if real['side'] == 'long' else "🔴"
        real_info = f" | 真实:{emoji}{real['upl']:+.1f}U({real['dist_liq']:.0f}%)"
    
    print(f"[{now.strftime('%H:%M')}] BTC=${mkt['price']:.0f} RSI={mkt['rsi']:.0f} ADX={mkt['adx']:.0f}{real_info}")

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--loop':
        print("启动综合监控（模拟+真实账户）")
        while True:
            main()
            time.sleep(30)
    else:
        main()
