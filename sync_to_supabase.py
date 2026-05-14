"""
数据同步脚本 - 将本地 PostgreSQL 数据推送到 Supabase
运行方式: python sync_to_supabase.py
建议: 每 5-10 秒运行一次，配合 Windows 任务计划程序
"""
import psycopg2
import json
import time
import sys
import requests
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# ============== 配置 ==============

# 本地 PostgreSQL 配置
PG_CONFIG = {
    'host': '192.168.1.2',
    'port': 5432,
    'user': 'postgres',
    'password': 'Postgres@2026',
    'database': 'postgres'
}

# Supabase 配置 (请替换为你的实际 key)
SUPABASE_URL = "https://lpcrnobolifrzwrkxoli.supabase.co"
SUPABASE_KEY = "sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug"

# ============== 工具函数 ==============

def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)

def supabase_request(method, endpoint, data=None, params=None):
    """发送请求到 Supabase REST API"""
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
    """同步虚拟账户余额"""
    print("  [1/4] 同步 virtual_balances...")
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT strategy_id, strategy_name, strategy_type, balance, initial_balance,
                   position_type, position_entry, position_size, leverage, last_update
            FROM virtual_balances
            ORDER BY strategy_id
        """)
        
        rows = cur.fetchall()
        count = 0
        
        for row in rows:
            data = {
                "strategy_id": row[0],
                "strategy_name": row[1],
                "strategy_type": row[2],
                "balance": float(row[3]) if row[3] else 1000,
                "initial_balance": float(row[4]) if row[4] else 1000,
                "position_type": row[5],
                "position_entry": float(row[6]) if row[6] else None,
                "position_size": float(row[7]) if row[7] else None,
                "leverage": row[8],
                "last_update": row[9].isoformat() if row[9] else None,
                "synced_at": datetime.now().isoformat()
            }
            
            # 使用 upsert
            params = {"strategy_id": f"eq.{row[0]}"}
            r = supabase_request("GET", "virtual_balances", params=params)
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
    """同步市场数据"""
    print("  [2/4] 同步 market_data...")
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT inst_id, price, change_24h, volume_24h, high_24h, low_24h
            FROM market_data
            WHERE inst_id = 'BTC-USDT-SWAP'
            ORDER BY ts DESC
            LIMIT 1
        """)
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row:
            print("    SKIP: 无市场数据")
            return 0
        
        data = {
            "inst_id": row[0],
            "price": float(row[1]) if row[1] else 0,
            "change_24h": float(row[2]) if row[2] else 0,
            "volume_24h": float(row[3]) if row[3] else 0,
            "high_24h": float(row[4]) if row[4] else 0,
            "low_24h": float(row[5]) if row[5] else 0,
            "updated_at": datetime.now().isoformat()
        }
        
        # 检查是否存在
        r = supabase_request("GET", "market_data", {"inst_id": "eq.BTC-USDT-SWAP"})
        if r.status_code == 200 and r.json():
            supabase_request("PATCH", "market_data?inst_id=eq.BTC-USDT-SWAP", data)
        else:
            supabase_request("POST", "market_data", data)
        
        print(f"    OK: BTC价格 ${data['price']}")
        return 1
        
    except Exception as e:
        print(f"    ERROR: {e}")
        return 0

def sync_strategies():
    """同步策略配置"""
    print("  [3/4] 同步 strategies...")
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, name, type, rsi_period, oversold, overbought,
                   stop_loss, take_profit, leverage, mode, params
            FROM strategies
            ORDER BY id
        """)
        
        rows = cur.fetchall()
        count = 0
        
        for row in rows:
            data = {
                "id": row[0],
                "name": row[1],
                "type": row[2],
                "rsi_period": row[3],
                "oversold": float(row[4]) if row[4] else None,
                "overbought": float(row[5]) if row[5] else None,
                "stop_loss": float(row[6]) if row[6] else None,
                "take_profit": float(row[7]) if row[7] else None,
                "leverage": row[8],
                "mode": row[9],
                "params": row[10]
            }
            
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
    """同步交易记录 (最近 100 条)"""
    print("  [4/4] 同步 btc_trades (最近100条)...")
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT ts, dt, account, action, side, entry_price, exit_price,
                   size, pnl, leverage, strategy, signal_mode, reason, status
            FROM btc_trades
            ORDER BY ts DESC
            LIMIT 100
        """)
        
        rows = cur.fetchall()
        count = 0
        
        for row in rows:
            data = {
                "ts": row[0],
                "dt": row[1].isoformat() if row[1] else None,
                "account": row[2],
                "action": row[3],
                "side": row[4],
                "entry_price": float(row[5]) if row[5] else None,
                "exit_price": float(row[6]) if row[6] else None,
                "size": float(row[7]) if row[7] else None,
                "pnl": float(row[8]) if row[8] else None,
                "leverage": row[9],
                "strategy": row[10],
                "signal_mode": row[11],
                "reason": row[12],
                "status": row[13] or "closed"
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

def get_api_data():
    """获取 API 数据 (返回 JSON 给前端)"""
    print("  [API] 获取策略数据...")
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        # 获取所有策略数据
        cur.execute("""
            SELECT 
                v.strategy_id,
                v.strategy_name,
                v.strategy_type,
                v.balance,
                v.initial_balance,
                v.position_type,
                v.position_entry,
                v.position_size,
                v.leverage,
                v.last_update,
                COUNT(t.id) as total_trades,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as winning_trades
            FROM virtual_balances v
            LEFT JOIN btc_trades t ON t.account = v.strategy_name
            GROUP BY v.strategy_id, v.strategy_name, v.strategy_type, 
                     v.balance, v.initial_balance, v.position_type,
                     v.position_entry, v.position_size, v.leverage, v.last_update
            ORDER BY v.strategy_id
        """)
        
        rows = cur.fetchall()
        strategies = []
        
        for row in rows:
            total = row[10] or 0
            wins = row[11] or 0
            strategies.append({
                "id": row[0],
                "name": row[1],
                "type": row[2],
                "balance": float(row[3]) if row[3] else 1000,
                "initial": float(row[4]) if row[4] else 1000,
                "pnl": float(row[3] - row[4]) if row[3] and row[4] else 0,
                "position": {
                    "type": row[5],
                    "entry": float(row[6]) if row[6] else None,
                    "size": float(row[7]) if row[7] else None
                } if row[5] else None,
                "leverage": row[8],
                "trades": total,
                "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
                "last_update": row[9].isoformat() if row[9] else None
            })
        
        cur.close()
        conn.close()
        
        # 获取市场数据
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT price, change_24h, volume_24h, high_24h, low_24h
            FROM market_data
            WHERE inst_id = 'BTC-USDT-SWAP'
            ORDER BY ts DESC
            LIMIT 1
        """)
        market = cur.fetchone()
        cur.close()
        conn.close()
        
        result = {
            "strategies": strategies,
            "market": {
                "price": float(market[0]) if market and market[0] else 0,
                "change_24h": float(market[1]) if market and market[1] else 0,
                "volume_24h": float(market[2]) if market and market[2] else 0,
                "high_24h": float(market[3]) if market and market[3] else 0,
                "low_24h": float(market[4]) if market and market[4] else 0
            } if market else None,
            "updated_at": datetime.now().isoformat()
        }
        
        return result
        
    except Exception as e:
        print(f"    ERROR: {e}")
        return None

# ============== 主函数 ==============

def sync_all():
    """同步所有数据到 Supabase"""
    print(f"\n=== 同步开始 {datetime.now().strftime('%H:%M:%S')} ===")
    
    total = 0
    total += sync_virtual_balances()
    total += sync_market_data()
    total += sync_strategies()
    total += sync_trades()
    
    print(f"=== 同步完成: {total} 条记录 ===\n")
    return total

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        # 循环模式：每 N 秒执行一次，默认 5 秒
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        print(f"循环模式: 每 {interval} 秒同步一次，按 Ctrl+C 停止")
        while True:
            sync_all()
            time.sleep(interval)
    elif len(sys.argv) > 1 and sys.argv[1] == "--api":
        data = get_api_data()
        if data:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print("{}")
    else:
        # 单次同步
        sync_all()
