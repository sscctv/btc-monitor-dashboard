#!/usr/bin/env python3
"""
BTC 自动交易执行系统
根据RSI策略自动执行交易，记录到数据库
运行方式: python auto_trader.py
建议: 使用 Windows 任务计划程序每分钟运行一次
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
DB_CONFIG = {
    'host': '192.168.1.2',
    'port': 5432,
    'user': 'postgres',
    'password': 'Postgres@2026',
    'database': 'postgres'
}

# OKX API
OKX_API = "https://www.okx.com"
SYMBOL = "BTC-USDT-SWAP"
INTERVAL = "5m"  # 5分钟K线

# ============== 策略配置 ==============
STRATEGIES = [
    # RSI 策略
    {"id": 6, "name": "RSI_14_35_65_L20", "type": "rsi", "period": 14, "oversold": 35, "overbought": 65, "leverage": 20, "stop_loss": 0.03, "take_profit": 0.15},
    {"id": 7, "name": "RSI_7_30_75_L20", "type": "rsi", "period": 7, "oversold": 30, "overbought": 75, "leverage": 20, "stop_loss": 0.04, "take_profit": 0.20},
    {"id": 8, "name": "RSI_7_35_75_L20", "type": "rsi", "period": 7, "oversold": 35, "overbought": 75, "leverage": 20, "stop_loss": 0.04, "take_profit": 0.20},
    {"id": 9, "name": "RSI_7_20_75_L20", "type": "rsi", "period": 7, "oversold": 20, "overbought": 75, "leverage": 20, "stop_loss": 0.05, "take_profit": 0.25},
    {"id": 10, "name": "RSI_14_35_70_L20", "type": "rsi", "period": 14, "oversold": 35, "overbought": 70, "leverage": 20, "stop_loss": 0.03, "take_profit": 0.15},
    {"id": 11, "name": "RSI_7_35_65_L20", "type": "rsi", "period": 7, "oversold": 35, "overbought": 65, "leverage": 20, "stop_loss": 0.035, "take_profit": 0.18},
    {"id": 12, "name": "RSI_7_25_75_L20", "type": "rsi", "period": 7, "oversold": 25, "overbought": 75, "leverage": 20, "stop_loss": 0.05, "take_profit": 0.25},
    {"id": 13, "name": "RSI_7_35_70_L20", "type": "rsi", "period": 7, "oversold": 35, "overbought": 70, "leverage": 20, "stop_loss": 0.04, "take_profit": 0.20},
    {"id": 14, "name": "RSI_14_35_75_L20", "type": "rsi", "period": 14, "oversold": 35, "overbought": 75, "leverage": 20, "stop_loss": 0.03, "take_profit": 0.12},
    {"id": 15, "name": "RSI_7_20_70_L20", "type": "rsi", "period": 7, "oversold": 20, "overbought": 70, "leverage": 20, "stop_loss": 0.05, "take_profit": 0.25},
    # BB 策略 (备用)
    {"id": 1, "name": "BB策略 30x全仓", "type": "bb", "period": 20, "oversold": 0.2, "overbought": 0.8, "leverage": 30, "stop_loss": 0.02, "take_profit": 0.06},
    {"id": 2, "name": "BB策略 30x逐仓", "type": "bb", "period": 20, "oversold": 0.2, "overbought": 0.8, "leverage": 30, "stop_loss": 0.02, "take_profit": 0.06},
]

# ============== 数据库操作 ==============
def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)

def init_positions_table():
    """初始化持仓状态表"""
    conn = get_db_conn()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS strategy_positions (
            strategy_id INTEGER PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            position_type TEXT,      -- '做多' '做空' NULL
            entry_price NUMERIC(18, 4),
            position_size NUMERIC(18, 8),
            stop_loss NUMERIC(18, 4),
            take_profit NUMERIC(18, 4),
            leverage INTEGER,
            entry_time TIMESTAMP,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    
    # 初始化所有策略持仓状态
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
    """获取当前持仓"""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT position_type, entry_price, position_size, stop_loss, take_profit
        FROM strategy_positions
        WHERE strategy_id = %s
    """, (strategy_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if row and row[0]:
        return {
            "type": row[0],
            "entry_price": float(row[1]),
            "size": float(row[2]),
            "stop_loss": float(row[3]),
            "take_profit": float(row[4])
        }
    return None

def update_position(strategy_id, position, conn=None):
    """更新持仓状态"""
    close_conn = False
    if conn is None:
        conn = get_db_conn()
        close_conn = True
    
    cur = conn.cursor()
    
    if position is None:
        cur.execute("""
            UPDATE strategy_positions
            SET position_type = NULL, entry_price = NULL, position_size = NULL,
                stop_loss = NULL, take_profit = NULL, entry_time = NULL, updated_at = NOW()
            WHERE strategy_id = %s
        """, (strategy_id,))
    else:
        cur.execute("""
            UPDATE strategy_positions
            SET position_type = %s, entry_price = %s, position_size = %s,
                stop_loss = %s, take_profit = %s, leverage = %s,
                entry_time = %s, updated_at = NOW()
            WHERE strategy_id = %s
        """, (
            position["type"], position["entry_price"], position["size"],
            position["stop_loss"], position["take_profit"], position["leverage"],
            position.get("entry_time"), strategy_id
        ))
    
    if close_conn:
        conn.commit()
        cur.close()
        conn.close()

def record_trade(strategy_id, strategy_name, action, side, entry_price, exit_price, size, pnl, leverage, reason):
    """记录交易"""
    conn = get_db_conn()
    cur = conn.cursor()
    now = datetime.now()
    ts = int(now.timestamp() * 1000)
    
    cur.execute("""
        INSERT INTO btc_trades (ts, dt, account, action, side, entry_price, exit_price, size, pnl, leverage, strategy, reason, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'closed')
    """, (ts, now, strategy_name, action, side, entry_price, exit_price, size, pnl, leverage, strategy_name, reason))
    
    # 更新 virtual_balances
    cur.execute("""
        UPDATE virtual_balances
        SET balance = balance + %s,
            position_type = NULL,
            position_entry = NULL,
            position_size = NULL,
            last_update = NOW()
        WHERE strategy_name = %s
    """, (pnl, strategy_name))
    
    conn.commit()
    cur.close()
    conn.close()

def update_virtual_balance(strategy_name, position_type, entry_price, size):
    """更新虚拟账户余额和持仓"""
    conn = get_db_conn()
    cur = conn.cursor()
    
    cur.execute("""
        UPDATE virtual_balances
        SET position_type = %s,
            position_entry = %s,
            position_size = %s,
            last_update = NOW()
        WHERE strategy_name = %s
    """, (position_type, entry_price, size, strategy_name))
    
    conn.commit()
    cur.close()
    conn.close()

# ============== OKX API ==============
def get_kline_data(inst_id=SYMBOL, bar=INTERVAL, limit=100):
    """获取K线数据"""
    try:
        url = f"{OKX_API}/api/v5/market/history-candles"
        params = {"instId": inst_id, "bar": bar, "limit": limit}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        
        if data.get("code") == "0":
            candles = data["data"]
            prices = []
            for c in reversed(candles):
                prices.append({
                    "ts": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5])
                })
            return prices
    except Exception as e:
        print(f"获取K线数据失败: {e}")
    return None

def calculate_rsi(prices, period=14):
    """计算RSI"""
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
    """计算布林带位置 (0-1)"""
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
    """检查策略并执行交易"""
    strategy_id = strategy["id"]
    strategy_name = strategy["name"]
    leverage = strategy["leverage"]
    stop_loss_rate = strategy["stop_loss"]
    take_profit_rate = strategy["take_profit"]
    
    # 计算指标
    if strategy["type"] == "rsi":
        indicator = calculate_rsi(market_data, strategy["period"])
        oversold = strategy["oversold"]
        overbought = strategy["overbought"]
    else:  # bb
        indicator = calculate_bb(market_data, strategy["period"])
        oversold = strategy["oversold"]
        overbought = strategy["overbought"]
    
    # 获取当前持仓
    position = get_current_position(strategy_id)
    
    # 交易逻辑
    if position is None:
        # 无持仓，检查是否应该开仓
        if strategy["type"] == "rsi":
            if indicator < oversold:
                # 开多
                position_size = 0.1  # 10%仓位
                entry_price = current_price
                stop_loss = entry_price * (1 - stop_loss_rate / leverage)
                take_profit = entry_price * (1 + take_profit_rate / leverage)
                
                new_pos = {
                    "type": "做多",
                    "entry_price": entry_price,
                    "size": position_size,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "leverage": leverage,
                    "entry_time": datetime.now()
                }
                update_position(strategy_id, new_pos)
                update_virtual_balance(strategy_name, "做多", entry_price, position_size)
                
                print(f"  [{strategy_name}] 开多 @ ${entry_price:.2f} | RSI={indicator:.1f} | SL=${stop_loss:.2f} | TP=${take_profit:.2f}")
                return {"action": "open_long", "price": entry_price}
                
            elif indicator > overbought:
                # 开空
                position_size = 0.1
                entry_price = current_price
                stop_loss = entry_price * (1 + stop_loss_rate / leverage)
                take_profit = entry_price * (1 - take_profit_rate / leverage)
                
                new_pos = {
                    "type": "做空",
                    "entry_price": entry_price,
                    "size": position_size,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "leverage": leverage,
                    "entry_time": datetime.now()
                }
                update_position(strategy_id, new_pos)
                update_virtual_balance(strategy_name, "做空", entry_price, position_size)
                
                print(f"  [{strategy_name}] 开空 @ ${entry_price:.2f} | RSI={indicator:.1f} | SL=${stop_loss:.2f} | TP=${take_profit:.2f}")
                return {"action": "open_short", "price": entry_price}
    else:
        # 有持仓，检查是否应该平仓
        should_close = False
        reason = ""
        exit_price = current_price
        
        if position["type"] == "做多":
            # 止损
            if current_price <= position["stop_loss"]:
                should_close = True
                reason = "止损"
                exit_price = position["stop_loss"]
            # 止盈
            elif current_price >= position["take_profit"]:
                should_close = True
                reason = "止盈"
                exit_price = position["take_profit"]
            # 反向信号
            elif strategy["type"] == "rsi" and indicator > overbought:
                should_close = True
                reason = "反向信号"
        
        elif position["type"] == "做空":
            # 止损
            if current_price >= position["stop_loss"]:
                should_close = True
                reason = "止损"
                exit_price = position["stop_loss"]
            # 止盈
            elif current_price <= position["take_profit"]:
                should_close = True
                reason = "止盈"
                exit_price = position["take_profit"]
            # 反向信号
            elif strategy["type"] == "rsi" and indicator < oversold:
                should_close = True
                reason = "反向信号"
        
        if should_close:
            # 计算盈亏
            if position["type"] == "做多":
                pnl_percent = (exit_price - position["entry_price"]) / position["entry_price"] * leverage
            else:
                pnl_percent = (position["entry_price"] - exit_price) / position["entry_price"] * leverage
            
            pnl = position["size"] * pnl_percent
            
            # 记录交易
            record_trade(
                strategy_id, strategy_name, "平仓", position["type"],
                position["entry_price"], exit_price,
                position["size"], pnl, leverage, reason
            )
            
            # 清空持仓
            update_position(strategy_id, None)
            
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            print(f"  [{strategy_name}] 平仓 {position['type']} @ ${exit_price:.2f} | {reason} | {pnl_str}")
            return {"action": "close", "pnl": pnl, "reason": reason}
    
    return None

# ============== 主函数 ==============
def run_trading_cycle():
    """运行一次交易周期"""
    print(f"\n{'='*60}")
    print(f"交易检查 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print('='*60)
    
    # 获取市场数据
    market_data = get_kline_data()
    if not market_data:
        print("获取市场数据失败")
        return
    
    current_price = market_data[-1]["close"]
    current_rsi = calculate_rsi(market_data, 14)
    print(f"BTC 价格: ${current_price:.2f} | RSI(14): {current_rsi:.1f}")
    
    # 更新市场数据表
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        change_24h = (current_price - market_data[-288]["close"]) / market_data[-288]["close"] * 100 if len(market_data) >= 288 else 0
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
    
    # 检查每个策略
    trade_count = 0
    for strategy in STRATEGIES:
        result = check_and_trade(strategy, current_price, market_data)
        if result:
            trade_count += 1
    
    print(f"\n本次交易周期完成，执行 {trade_count} 笔交易")

def main():
    print("="*60)
    print("BTC 自动交易执行系统")
    print("="*60)
    
    # 初始化
    print("\n初始化数据库表...")
    init_positions_table()
    
    # 运行交易
    run_trading_cycle()
    
    print("\n完成!")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        # 循环模式
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        print(f"\n循环模式: 每 {interval} 秒执行一次")
        while True:
            run_trading_cycle()
            time.sleep(interval)
    else:
        # 单次执行
        main()
