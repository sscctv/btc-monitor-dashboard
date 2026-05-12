#!/usr/bin/env python3
"""
Supabase同步模块 - 使用现有btc_trades/btc_signals表
"""

import requests
import json
from datetime import datetime, timezone, timedelta

SUPABASE_URL = "https://lpcrnobolifrzwrkxoli.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_SECRET"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

def supabase_request(method, table, data=None, params=None):
    """Supabase REST API请求"""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        if method == "GET":
            r = requests.get(url, headers=HEADERS, params=params)
        elif method == "POST":
            r = requests.post(url, headers=HEADERS, json=data)
        elif method == "PATCH":
            r = requests.patch(url, headers=HEADERS, json=data, params=params)
        
        if r.status_code in [200, 201]:
            return r.json() if r.text else True
        return r.text
    except Exception as e:
        return str(e)

def sync_trade(trade_data):
    """同步交易到btc_trades表"""
    data = {
        'account_id': '虚拟5策略',
        'strategy': trade_data['strategy'],
        'side': 'long',
        'entry_price': trade_data['entry'],
        'exit_price': trade_data.get('exit'),
        'close_price': trade_data.get('exit'),
        'size': 1,
        'leverage': trade_data.get('leverage', 20),
        'status': 'closed' if trade_data.get('exit') else 'open',
        'realized_pnl': trade_data.get('pnl'),
        'opened_at': trade_data.get('opened_at'),
        'closed_at': trade_data.get('closed_at'),
    }
    return supabase_request("POST", "btc_trades", data=data)

def sync_signal(signal_data):
    """同步信号到btc_signals表"""
    data = {
        'signal_type': signal_data['type'],  # 'OPEN' or 'CLOSE'
        'price': signal_data['price'],
        'strategy': signal_data.get('strategy'),
        'market_state': signal_data.get('result_note'),
    }
    return supabase_request("POST", "btc_signals", data=data)

def get_virtual_trades():
    """获取虚拟交易记录"""
    return supabase_request("GET", "btc_trades", params={
        "account_id": "eq.虚拟5策略",
        "order": "opened_at.desc",
        "limit": 100
    })

def get_virtual_summary():
    """获取虚拟交易汇总"""
    trades = get_virtual_trades()
    if not trades or isinstance(trades, str):
        return None
    
    total_pnl = sum([t.get('realized_pnl', 0) or 0 for t in trades])
    wins = [t for t in trades if (t.get('realized_pnl') or 0) > 0]
    losses = [t for t in trades if (t.get('realized_pnl') or 0) < 0]
    
    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'total_pnl': total_pnl,
        'win_rate': len(wins) / len(trades) * 100 if trades else 0
    }

if __name__ == '__main__':
    print("📊 虚拟5策略交易汇总")
    print("=" * 50)
    
    summary = get_virtual_summary()
    if summary:
        print(f"总交易: {summary['total_trades']}笔")
        print(f"盈利: {summary['wins']}笔")
        print(f"亏损: {summary['losses']}笔")
        print(f"胜率: {summary['win_rate']:.1f}%")
        print(f"总盈亏: ${summary['total_pnl']:+.2f}")
    else:
        print("暂无数据")
    
    print("\n📋 最近10笔交易:")
    trades = get_virtual_trades()
    if trades and isinstance(trades, list):
        for t in trades[:10]:
            pnl = t.get('realized_pnl', 0) or 0
            emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "⏳"
            print(f"  {emoji} {t.get('strategy')} | ${pnl:+.2f} | {t.get('entry_price')} -> {t.get('close_price')}")
