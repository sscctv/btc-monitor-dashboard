#!/usr/bin/env python3
"""
数据库配置和连接模块
支持 Supabase (云) 和 PostgreSQL (本地)
"""

import os
from supabase import create_client, Client
import psycopg2
from psycopg2.extras import RealDictCursor

# ============== Supabase 配置 ==============
SUPABASE_URL = "https://lpcrnbolifrzwrkxoli.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_KEY"  # 需要替换为实际key

# ============== PostgreSQL 本地配置 ==============
DB_CONFIG = {
    'host': '192.168.1.2',
    'port': 5432,
    'user': 'postgres',
    'password': 'Postgres@2026',
    'database': 'postgres'
}

# ============== 数据库连接函数 ==============

def get_supabase_client():
    """获取 Supabase 客户端"""
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_postgres_connection():
    """获取 PostgreSQL 本地连接"""
    return psycopg2.connect(**DB_CONFIG, connect_timeout=5)

# ============== 策略配置 ==============

# 原项目策略 (BB策略)
ORIGINAL_STRATEGIES = [
    {'id': 1, 'name': 'BB策略 30x全仓', 'sig': 'bb_squeeze', 'tp': 'triple', 'lev': 30, 'type': '全仓'},
    {'id': 2, 'name': 'BB策略 30x逐仓', 'sig': 'bb_squeeze', 'tp': 'partial', 'lev': 30, 'type': '逐仓'},
    {'id': 3, 'name': 'BB策略 25x全仓', 'sig': 'bb_squeeze', 'tp': 'triple', 'lev': 25, 'type': '全仓'},
    {'id': 4, 'name': 'BB策略 25x逐仓', 'sig': 'bb_squeeze', 'tp': 'partial', 'lev': 25, 'type': '逐仓'},
    {'id': 5, 'name': 'BB策略 20x', 'sig': 'bb_squeeze', 'tp': 'partial', 'lev': 20, 'type': '逐仓'},
]

# 新策略 (RSI Top 10)
NEW_STRATEGIES = [
    {'id': 6, 'name': 'RSI_14_35_65_L20', 'rsi_period': 14, 'oversold': 35, 'overbought': 65, 'lev': 20},
    {'id': 7, 'name': 'RSI_7_30_75_L20', 'rsi_period': 7, 'oversold': 30, 'overbought': 75, 'lev': 20},
    {'id': 8, 'name': 'RSI_7_35_75_L20', 'rsi_period': 7, 'oversold': 35, 'overbought': 75, 'lev': 20},
    {'id': 9, 'name': 'RSI_7_20_75_L20', 'rsi_period': 7, 'oversold': 20, 'overbought': 75, 'lev': 20},
    {'id': 10, 'name': 'RSI_14_35_70_L20', 'rsi_period': 14, 'oversold': 35, 'overbought': 70, 'lev': 20},
    {'id': 11, 'name': 'RSI_7_35_65_L20', 'rsi_period': 7, 'oversold': 35, 'overbought': 65, 'lev': 20},
    {'id': 12, 'name': 'RSI_7_25_75_L20', 'rsi_period': 7, 'oversold': 25, 'overbought': 75, 'lev': 20},
    {'id': 13, 'name': 'RSI_7_35_70_L20', 'rsi_period': 7, 'oversold': 35, 'overbought': 70, 'lev': 20},
    {'id': 14, 'name': 'RSI_14_35_75_L20', 'rsi_period': 14, 'oversold': 35, 'overbought': 75, 'lev': 20},
    {'id': 15, 'name': 'RSI_7_20_70_L20', 'rsi_period': 7, 'oversold': 20, 'overbought': 70, 'lev': 20},
]

# 所有策略
ALL_STRATEGIES = ORIGINAL_STRATEGIES + NEW_STRATEGIES


# ============== 数据库操作函数 ==============

def get_all_strategies_data():
    """获取所有策略的完整数据"""
    try:
        conn = get_postgres_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 获取策略余额
        cur.execute("""
            SELECT strategy_id, balance, initial_balance, position_type, 
                   position_entry, position_size, last_update
            FROM virtual_balances
            ORDER BY strategy_id
        """)
        balances = {row['strategy_id']: row for row in cur.fetchall()}
        
        # 获取交易统计
        cur.execute("""
            SELECT strategy_id, COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                   AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                   AVG(CASE WHEN pnl <= 0 THEN pnl END) as avg_loss
            FROM trades
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY strategy_id
        """)
        stats = {row['strategy_id']: row for row in cur.fetchall()}
        
        cur.close()
        conn.close()
        
        # 合并数据
        result = []
        for strat in ALL_STRATEGIES:
            sid = strat['id']
            bal = balances.get(sid, {})
            st = stats.get(sid, {})
            
            total_trades = st.get('total_trades', 0) or 0
            winning = st.get('winning_trades', 0) or 0
            
            result.append({
                **strat,
                'initial': bal.get('initial_balance', 1000),
                'balance': bal.get('balance', 1000),
                'pnl': bal.get('balance', 1000) - bal.get('initial_balance', 1000),
                'position': {
                    'type': bal.get('position_type'),
                    'entry': bal.get('position_entry'),
                    'size': bal.get('position_size')
                } if bal.get('position_type') else None,
                'trades': total_trades,
                'win_rate': (winning / total_trades * 100) if total_trades > 0 else 0,
                'last_update': bal.get('last_update')
            })
        
        return result
        
    except Exception as e:
        print(f"Database error: {e}")
        return None


def get_strategy_trades(strategy_id, limit=50):
    """获取指定策略的交易记录"""
    try:
        conn = get_postgres_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT id, type, entry_price, exit_price, position_size,
                   pnl, pnl_percent, reason, created_at, closed_at
            FROM trades
            WHERE strategy_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (strategy_id, limit))
        
        trades = cur.fetchall()
        cur.close()
        conn.close()
        
        return trades
        
    except Exception as e:
        print(f"Database error: {e}")
        return []


def get_current_positions():
    """获取所有当前持仓"""
    try:
        conn = get_postgres_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT v.strategy_id, v.position_type, v.position_entry, v.position_size,
                   o.price as current_price, o.volume_24h
            FROM virtual_balances v
            LEFT JOIN okx_candles o ON o.ts = (SELECT MAX(ts) FROM okx_candles)
            WHERE v.position_type IS NOT NULL
        """)
        
        positions = cur.fetchall()
        cur.close()
        conn.close()
        
        return positions
        
    except Exception as e:
        print(f"Database error: {e}")
        return []


# ============== 主函数测试 ==============
if __name__ == "__main__":
    print("测试数据库连接...")
    
    # 测试 PostgreSQL 连接
    try:
        conn = get_postgres_connection()
        print("✓ PostgreSQL 连接成功")
        conn.close()
    except Exception as e:
        print(f"✗ PostgreSQL 连接失败: {e}")
    
    # 测试 Supabase 连接
    try:
        supabase = get_supabase_client()
        print("✓ Supabase 客户端初始化成功")
    except Exception as e:
        print(f"✗ Supabase 初始化失败: {e}")
    
    # 显示所有策略
    print(f"\n共 {len(ALL_STRATEGIES)} 个策略:")
    for s in ALL_STRATEGIES:
        print(f"  {s['id']}. {s['name']}")