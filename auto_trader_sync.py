#!/usr/bin/env python3
"""
BTC 自动交易 + Supabase 同步合并脚本
每 5 秒：自动交易 → 本地 PostgreSQL → 同步到 Supabase

运行方式:
    python3 auto_trader_sync.py              # 单次执行
    python3 auto_trader_sync.py --loop 5     # 每 5 秒循环（默认）
    python3 auto_trader_sync.py --loop 60    # 每 60 秒循环
"""
import sys
import time
import json
import requests
import numpy as np
import psycopg2
from datetime import datetime
from threading import Thread, Lock

sys.stdout.reconfigure(encoding='utf-8')

# ============== 配置 ==============
PG_CONFIG = {
    'host': '192.168.1.2',
    'port': 5432,
    'user': 'postgres',
    'password': 'Postgres@2026',
    'database': 'postgres'
}

SUPABASE_URL = "https://lpcrnobolifrzwrkxoli.supabase.co"
SUPABASE_KEY = "sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug"

OKX_API = "https://www.okx.com"
SYMBOL = "BTC-USDT-SWAP"
INTERVAL = "5m"

# ============== 策略配置 ==============
STRATEGIES = [
    # RSI 策略 (10个)
    {"id": 6,  "name": "RSI_14_35_65_L20", "type": "rsi", "period": 14, "oversold": 35, "overbought": 65, "leverage": 20, "stop_loss": 0.03, "take_profit": 0.15},
    {"id": 7,  "name": "RSI_7_30_75_L20",  "type": "rsi", "period": 7,  "oversold": 30, "overbought": 75, "leverage": 20, "stop_loss": 0.04, "take_profit": 0.20},
    {"id": 8,  "name": "RSI_7_35_75_L20",  "type": "rsi", "period": 7,  "oversold": 35, "overbought": 75, "leverage": 20, "stop_loss": 0.04, "take_profit": 0.20},
    {"id": 9,  "name": "RSI_7_20_75_L20",  "type": "rsi", "period": 7,  "oversold": 20, "overbought": 75, "leverage": 20, "stop_loss": 0.05, "take_profit": 0.25},
    {"id": 10, "name": "RSI_14_35_70_L20", "type": "rsi", "period": 14, "oversold": 35, "overbought": 70, "leverage": 20, "stop_loss": 0.03, "take_profit": 0.15},
    {"id": 11, "name": "RSI_7_35_65_L20",  "type": "rsi", "period": 7,  "oversold": 35, "overbought": 65, "leverage": 20, "stop_loss": 0.035,"take_profit": 0.18},
    {"id": 12, "name": "RSI_7_25_75_L20",  "type": "rsi", "period": 7,  "oversold": 25, "overbought": 75, "leverage": 20, "stop_loss": 0.05, "take_profit": 0.25},
    {"id": 13, "name": "RSI_7_35_70_L20",  "type": "rsi", "period": 7,  "oversold": 35, "overbought": 70, "leverage": 20, "stop_loss": 0.04, "take_profit": 0.20},
    {"id": 14, "name": "RSI_14_35_75_L20", "type": "rsi", "period": 14, "oversold": 35, "overbought": 75, "leverage": 20, "stop_loss": 0.03, "take_profit": 0.12},
    {"id": 15, "name": "RSI_7_20_70_L20",  "type": "rsi", "period": 7,  "oversold": 20, "overbought": 70, "leverage": 20, "stop_loss": 0.05, "take_profit": 0.25},
    # BB 策略 (5个)
    {"id": 1, "name": "BB策略 30x全仓", "type": "bb", "period": 20, "oversold": 0.2, "overbought": 0.8, "leverage": 30, "stop_loss": 0.02, "take_profit": 0.06},
    {"id": 2, "name": "BB策略 30x逐仓", "type": "bb", "period": 20, "oversold": 0.2, "overbought": 0.8, "leverage": 30, "stop_loss": 0.02, "take_profit": 0.06},
    {"id": 3, "name": "BB策略 25x全仓", "type": "bb", "period": 20, "oversold": 0.2, "overbought": 0.8, "leverage": 25, "stop_loss": 0.02, "take_profit": 0.06},
    {"id": 4, "name": "BB策略 25x逐仓", "type": "bb", "period": 20, "oversold": 0.2, "overbought": 0.8, "leverage": 25, "stop_loss": 0.02, "take_profit": 0.06},
    {"id": 5, "name": "BB策略 20x",      "type": "bb", "period": 20, "oversold": 0.2, "overbought": 0.8, "leverage": 20, "stop_loss": 0.02, "take_profit": 0.06},
]

# ============== 数据库操作 (auto_trader 部分) ==============

def get_db_conn():
    return psycopg2.connect(**PG_CONFIG)

def init_positions_table():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS strategy_positions (
            strategy_id INTEGER PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            position_type TEXT,
            entry_price NUMERIC(18, 4),
            position_size NUMERIC(18, 8),
            stop_loss NUMERIC(18, 4),
            take_profit NUMERIC(18, 4),
            leverage INTEGER,
            entry_time TIMESTAMP,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    for s in STRATEGIES:
        cur.execute("""
            INSERT INTO strategy_positions (strategy_id, strategy_name, leverage)
            VALUES (%s, %s, %s)
            ON CONFLICT (strategy_id) DO UPDATE SET
                strategy_name = EXCLUDED.strategy_name,
                leverage = EXCLUDED.leverage
        """, (s["id"], s["name"], s["leverage"]))
    conn.commit()
    cur.close()
    conn.close()

def get_current_position(strategy_id):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT position_type, entry_price, position_size, stop_loss, take_profit
        FROM strategy_positions WHERE strategy_id = %s
    """, (strategy_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row[0]:
        return {"type": row[0], "entry_price": float(row[1]), "size": float(row[2]),
                "stop_loss": float(row[3]), "take_profit": float(row[4])}
    return None

def update_position(strategy_id, position, conn=None):
    close_conn = False
    if conn is None:
        conn = get_db_conn()
        close_conn = True
    cur = conn.cursor()
    if position is None:
        cur.execute("""
            UPDATE strategy_positions SET position_type = NULL, entry_price = NULL,
            position_size = NULL, stop_loss = NULL, take_profit = NULL,
            entry_time = NULL, updated_at = NOW() WHERE strategy_id = %s
        """, (strategy_id,))
    else:
        cur.execute("""
            UPDATE strategy_positions SET position_type = %s, entry_price = %s,
            position_size = %s, stop_loss = %s, take_profit = %s, leverage = %s,
            entry_time = %s, updated_at = NOW() WHERE strategy_id = %s
        """, (position["type"], position["entry_price"], position["size"],
              position["stop_loss"], position["take_profit"], position["leverage"],
              position.get("entry_time"), strategy_id))
    if close_conn:
        conn.commit()
        cur.close()
        conn.close()

def record_trade(strategy_id, strategy_name, action, side, entry_price, exit_price, size, pnl, leverage, reason):
    conn = get_db_conn()
    cur = conn.cursor()
    now = datetime.now()
    ts = int(now.timestamp() * 1000)
    cur.execute("""
        INSERT INTO btc_trades (ts, dt, account, action, side, entry_price, exit_price, size, pnl, leverage, strategy, reason, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'closed')
    """, (ts, now, strategy_name, action, side, entry_price, exit_price, size, pnl, leverage, strategy_name, reason))
    cur.execute("""
        UPDATE virtual_balances SET balance = balance + %s,
        position_type = NULL, position_entry = NULL, position_size = NULL, last_update = NOW()
        WHERE strategy_name = %s
    """, (pnl, strategy_name))
    conn.commit()
    cur.close()
    conn.close()

def update_virtual_balance(strategy_name, position_type, entry_price, size):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE virtual_balances SET position_type = %s, position_entry = %s,
        position_size = %s, last_update = NOW() WHERE strategy_name = %s
    """, (position_type, entry_price, size, strategy_name))
    conn.commit()
    cur.close()
    conn.close()

# ============== 市场数据 (从本地 PG 读取) ==============

def get_kline_data(inst_id=SYMBOL, limit=100):
    """从本地 PostgreSQL 读取 K线数据用于交易决策"""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT ts, price, volume_24h, high_24h, low_24h
            FROM market_data
            WHERE inst_id = %s
            ORDER BY ts ASC
            LIMIT %s
        """, (inst_id, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            return None
        prices = []
        for r in rows:
            prices.append({
                "ts": r[0], "close": float(r[1]),
                "volume": float(r[2]), "high": float(r[3]), "low": float(r[4])
            })
        return prices
    except Exception as e:
        print(f"从本地PG读取K线失败: {e}")
        return None

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    closes = [p["close"] for p in prices]
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_bb(prices, period=20):
    if len(prices) < period:
        return 0.5
    closes = [p["close"] for p in prices[-period:]]
    sma = np.mean(closes)
    std = np.std(closes)
    if std == 0:
        return 0.5
    current = prices[-1]["close"]
    bb_position = (current - (sma - 2*std)) / (4*std)
    return max(0, min(1, bb_position))

# ============== 交易逻辑 ==============

def check_and_trade(strategy, current_price, market_data):
    strategy_id = strategy["id"]
    strategy_name = strategy["name"]
    leverage = strategy["leverage"]
    stop_loss_rate = strategy["stop_loss"]
    take_profit_rate = strategy["take_profit"]

    if strategy["type"] == "rsi":
        indicator = calculate_rsi(market_data, strategy["period"])
        oversold = strategy["oversold"]
        overbought = strategy["overbought"]
    else:
        indicator = calculate_bb(market_data, strategy["period"])
        oversold = strategy["oversold"]
        overbought = strategy["overbought"]

    position = get_current_position(strategy_id)

    if position is None:
        if strategy["type"] == "rsi" and indicator < oversold:
            position_size = 0.1
            entry_price = current_price
            stop_loss = entry_price * (1 - stop_loss_rate / leverage)
            take_profit = entry_price * (1 + take_profit_rate / leverage)
            new_pos = {"type": "做多", "entry_price": entry_price, "size": position_size,
                       "stop_loss": stop_loss, "take_profit": take_profit,
                       "leverage": leverage, "entry_time": datetime.now()}
            update_position(strategy_id, new_pos)
            update_virtual_balance(strategy_name, "做多", entry_price, position_size)
            print(f"  [{strategy_name}] 开多 @ ${entry_price:.2f} | RSI={indicator:.1f}")
            return {"action": "open_long", "price": entry_price}
        elif strategy["type"] == "rsi" and indicator > overbought:
            position_size = 0.1
            entry_price = current_price
            stop_loss = entry_price * (1 + stop_loss_rate / leverage)
            take_profit = entry_price * (1 - take_profit_rate / leverage)
            new_pos = {"type": "做空", "entry_price": entry_price, "size": position_size,
                       "stop_loss": stop_loss, "take_profit": take_profit,
                       "leverage": leverage, "entry_time": datetime.now()}
            update_position(strategy_id, new_pos)
            update_virtual_balance(strategy_name, "做空", entry_price, position_size)
            print(f"  [{strategy_name}] 开空 @ ${entry_price:.2f} | RSI={indicator:.1f}")
            return {"action": "open_short", "price": entry_price}
    else:
        should_close = False
        reason = ""
        exit_price = current_price
        if position["type"] == "做多":
            if current_price <= position["stop_loss"]:
                should_close, reason, exit_price = True, "止损", position["stop_loss"]
            elif current_price >= position["take_profit"]:
                should_close, reason, exit_price = True, "止盈", position["take_profit"]
            elif strategy["type"] == "rsi" and indicator > overbought:
                should_close, reason = True, "反向信号"
        elif position["type"] == "做空":
            if current_price >= position["stop_loss"]:
                should_close, reason, exit_price = True, "止损", position["stop_loss"]
            elif current_price <= position["take_profit"]:
                should_close, reason, exit_price = True, "止盈", position["take_profit"]
            elif strategy["type"] == "rsi" and indicator < oversold:
                should_close, reason = True, "反向信号"

        if should_close:
            if position["type"] == "做多":
                pnl_percent = (exit_price - position["entry_price"]) / position["entry_price"] * leverage
            else:
                pnl_percent = (position["entry_price"] - exit_price) / position["entry_price"] * leverage
            pnl = position["size"] * pnl_percent
            record_trade(strategy_id, strategy_name, "平仓", position["type"],
                         position["entry_price"], exit_price, position["size"], pnl, leverage, reason)
            update_position(strategy_id, None)
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            print(f"  [{strategy_name}] 平仓 {position['type']} @ ${exit_price:.2f} | {reason} | {pnl_str}")
            return {"action": "close", "pnl": pnl, "reason": reason}
    return None

# ============== Supabase 同步工具 ==============

def supabase_request(method, endpoint, data=None, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    if method == "GET":
        r = requests.get(url, headers=headers, params=params)
    elif method == "POST":
        r = requests.post(url, headers=headers, json=data)
    elif method == "PATCH":
        r = requests.patch(url, headers=headers, json=data, params=params)
    elif method == "DELETE":
        r = requests.delete(url, headers=headers, params=params)
    return r

# ============== 同步函数 ==============

def sync_virtual_balances():
    print("  [1/4] 同步 virtual_balances...")
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT strategy_id, strategy_name, strategy_type, balance, initial_balance,
                   position_type, position_entry, position_size, leverage, last_update
            FROM virtual_balances ORDER BY strategy_id
        """)
        rows = cur.fetchall()
        count = 0
        for row in rows:
            data = {
                "strategy_id": row[0], "strategy_name": row[1], "strategy_type": row[2],
                "balance": float(row[3]) if row[3] else 1000,
                "initial_balance": float(row[4]) if row[4] else 1000,
                "position_type": row[5],
                "position_entry": float(row[6]) if row[6] else None,
                "position_size": float(row[7]) if row[7] else None,
                "leverage": row[8],
                "last_update": row[9].isoformat() if row[9] else None,
                "synced_at": datetime.now().isoformat()
            }
            r = supabase_request("GET", "virtual_balances", {"strategy_id": f"eq.{row[0]}"})
            if r.status_code == 200 and r.json():
                supabase_request("PATCH", f"virtual_balances?strategy_id=eq.{row[0]}", data)
            else:
                supabase_request("POST", "virtual_balances", data)
            count += 1
        cur.close()
        conn.close()
        print(f"    OK: {count} 条")
        return count
    except Exception as e:
        print(f"    ERROR: {e}")
        return 0

def sync_market_data():
    print("  [2/4] 同步 market_data...")
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT inst_id, price, change_24h, volume_24h, high_24h, low_24h
            FROM market_data WHERE inst_id = 'BTC-USDT-SWAP' ORDER BY ts DESC LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            print("    SKIP: 无市场数据")
            return 0
        data = {
            "inst_id": row[0], "price": float(row[1]) if row[1] else 0,
            "change_24h": float(row[2]) if row[2] else 0,
            "volume_24h": float(row[3]) if row[3] else 0,
            "high_24h": float(row[4]) if row[4] else 0, "low_24h": float(row[5]) if row[5] else 0,
            "updated_at": datetime.now().isoformat()
        }
        r = supabase_request("GET", "market_data", {"inst_id": "eq.BTC-USDT-SWAP"})
        if r.status_code == 200 and r.json():
            supabase_request("PATCH", "market_data?inst_id=eq.BTC-USDT-SWAP", data)
        else:
            supabase_request("POST", "market_data", data)
        print(f"    OK: BTC ${data['price']}")
        return 1
    except Exception as e:
        print(f"    ERROR: {e}")
        return 0

def sync_strategies():
    print("  [3/4] 同步 strategies...")
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, type, rsi_period, oversold, overbought,
                   stop_loss, take_profit, leverage, mode, params
            FROM strategies ORDER BY id
        """)
        rows = cur.fetchall()
        count = 0
        for row in rows:
            data = {"id": row[0], "name": row[1], "type": row[2], "rsi_period": row[3],
                    "oversold": float(row[4]) if row[4] else None,
                    "overbought": float(row[5]) if row[5] else None,
                    "stop_loss": float(row[6]) if row[6] else None,
                    "take_profit": float(row[7]) if row[7] else None,
                    "leverage": row[8], "mode": row[9], "params": row[10]}
            r = supabase_request("GET", "strategies", {"id": f"eq.{row[0]}"})
            if r.status_code == 200 and r.json():
                supabase_request("PATCH", f"strategies?id=eq.{row[0]}", data)
            else:
                supabase_request("POST", "strategies", data)
            count += 1
        cur.close()
        conn.close()
        print(f"    OK: {count} 条")
        return count
    except Exception as e:
        print(f"    ERROR: {e}")
        return 0

def sync_trades():
    print("  [4/4] 同步 btc_trades (最近100条)...")
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT ts, dt, account, action, side, entry_price, exit_price,
                   size, pnl, leverage, strategy, signal_mode, reason, status
            FROM btc_trades ORDER BY ts DESC LIMIT 100
        """)
        rows = cur.fetchall()
        count = 0
        for row in rows:
            data = {
                "ts": row[0], "dt": row[1].isoformat() if row[1] else None,
                "account": row[2], "action": row[3], "side": row[4],
                "entry_price": float(row[5]) if row[5] else None,
                "exit_price": float(row[6]) if row[6] else None,
                "size": float(row[7]) if row[7] else None,
                "pnl": float(row[8]) if row[8] else None,
                "leverage": row[9], "strategy": row[10],
                "signal_mode": row[11], "reason": row[12], "status": row[13] or "closed"
            }
            r = supabase_request("GET", "btc_trades", {"ts": f"eq.{row[0]}"})
            if r.status_code == 200 and r.json():
                supabase_request("PATCH", f"btc_trades?ts=eq.{row[0]}", data)
            else:
                supabase_request("POST", "btc_trades", data)
            count += 1
        cur.close()
        conn.close()
        print(f"    OK: {count} 条")
        return count
    except Exception as e:
        print(f"    ERROR: {e}")
        return 0

# ============== 主流程 ==============

def run_trading_cycle():
    """运行交易 + 同步"""
    print(f"\n{'='*60}")
    print(f"交易周期 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print('='*60)

    market_data = get_kline_data()
    if not market_data:
        print("获取市场数据失败，跳过本周期")
        return
    current_price = market_data[-1]["close"]
    current_rsi = calculate_rsi(market_data, 14)
    print(f"BTC: ${current_price:.2f} | RSI(14): {current_rsi:.1f}")

    # 更新市场数据到本地PG
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        change_24h = (current_price - market_data[-288]["close"]) / market_data[-288]["close"] * 100 \
            if len(market_data) >= 288 else 0
        high_24h = max(p["high"] for p in market_data[-288:]) if len(market_data) >= 288 else current_price * 1.02
        low_24h = min(p["low"] for p in market_data[-288:]) if len(market_data) >= 288 else current_price * 0.98
        cur.execute("""
            INSERT INTO market_data (inst_id, price, change_24h, volume_24h, high_24h, low_24h, ts, dt)
            VALUES ('BTC-USDT-SWAP', %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT DO NOTHING
        """, (current_price, change_24h, market_data[-1]["volume"], high_24h, low_24h, market_data[-1]["ts"]))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"更新市场数据失败: {e}")

    # 检查策略交易
    trade_count = 0
    for strategy in STRATEGIES:
        result = check_and_trade(strategy, current_price, market_data)
        if result:
            trade_count += 1
    print(f"  本次执行 {trade_count} 笔交易")

    # 同步到 Supabase
    print(f"\n--- 同步到 Supabase ---")
    total = 0
    total += sync_virtual_balances()
    total += sync_market_data()
    total += sync_strategies()
    total += sync_trades()
    print(f"  同步完成: {total} 条记录")

# ============== 入口 ==============

if __name__ == "__main__":
    init_positions_table()
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        print(f"循环模式: 每 {interval} 秒执行一次，按 Ctrl+C 停止")
        while True:
            run_trading_cycle()
            time.sleep(interval)
    else:
        run_trading_cycle()