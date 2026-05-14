"""
完善本地数据库 - 创建所需表结构
"""
import psycopg2
import sys
sys.stdout.reconfigure(encoding='utf-8')

DB_CONFIG = {
    'host': '192.168.1.2',
    'port': 5432,
    'user': 'postgres',
    'password': 'Postgres@2026',
    'database': 'postgres'
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def setup_database():
    conn = get_conn()
    cur = conn.cursor()
    
    print("=== 完善数据库表结构 ===\n")
    
    # 1. 创建 virtual_balances 表 (策略余额)
    print("1. 创建 virtual_balances 表...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS virtual_balances (
            strategy_id INTEGER PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            strategy_type TEXT,                    -- 'bb' 或 'rsi'
            balance NUMERIC(18, 4) DEFAULT 1000,
            initial_balance NUMERIC(18, 4) DEFAULT 1000,
            position_type TEXT,                   -- '做多' '做空' NULL
            position_entry NUMERIC(18, 4),
            position_size NUMERIC(18, 8),
            leverage INTEGER DEFAULT 20,
            last_update TIMESTAMP DEFAULT NOW()
        )
    """)
    print("   ✓ virtual_balances")
    
    # 2. 创建 market_data 表 (市场数据)
    print("2. 创建 market_data 表...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_data (
            id SERIAL PRIMARY KEY,
            ts BIGINT NOT NULL,
            dt TIMESTAMP NOT NULL,
            inst_id TEXT NOT NULL,                -- 'BTC-USDT-SWAP'
            price NUMERIC(18, 4),
            change_24h NUMERIC(10, 4),
            volume_24h NUMERIC(20, 2),
            high_24h NUMERIC(18, 4),
            low_24h NUMERIC(18, 4),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_market_data_inst ON market_data(inst_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_market_data_ts ON market_data(ts DESC)")
    print("   ✓ market_data")
    
    # 3. 创建 strategies 表 (策略配置)
    print("3. 创建 strategies 表...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,                  -- 'bb' 或 'rsi'
            rsi_period INTEGER,
            oversold NUMERIC(5, 2),
            overbought NUMERIC(5, 2),
            stop_loss NUMERIC(5, 4),
            take_profit NUMERIC(5, 4),
            leverage INTEGER DEFAULT 20,
            mode TEXT,                           -- '全仓' '逐仓'
            params TEXT,                         -- JSON格式参数字符串
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    print("   ✓ strategies")
    
    # 4. 创建 sync_log 表 (同步日志)
    print("4. 创建 sync_log 表...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id SERIAL PRIMARY KEY,
            table_name TEXT NOT NULL,
            records_synced INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',       -- 'success' 'failed'
            error_message TEXT,
            synced_at TIMESTAMP DEFAULT NOW()
        )
    """)
    print("   ✓ sync_log")
    
    conn.commit()
    
    # 5. 初始化策略数据
    print("\n5. 初始化策略数据...")
    
    # 清空并插入 BB 策略
    cur.execute("DELETE FROM virtual_balances WHERE strategy_id <= 5")
    bb_strategies = [
        (1, 'BB策略 30x全仓', 'bb', 30, '全仓'),
        (2, 'BB策略 30x逐仓', 'bb', 30, '逐仓'),
        (3, 'BB策略 25x全仓', 'bb', 25, '全仓'),
        (4, 'BB策略 25x逐仓', 'bb', 25, '逐仓'),
        (5, 'BB策略 20x', 'bb', 20, '逐仓'),
    ]
    for sid, name, stype, lev, mode in bb_strategies:
        cur.execute("""
            INSERT INTO virtual_balances (strategy_id, strategy_name, strategy_type, balance, initial_balance, leverage)
            VALUES (%s, %s, %s, 1000, 1000, %s)
            ON CONFLICT (strategy_id) DO UPDATE SET
                strategy_name = EXCLUDED.strategy_name,
                strategy_type = EXCLUDED.strategy_type,
                leverage = EXCLUDED.leverage
        """, (sid, name, stype, lev))
    
    # 清空并插入 RSI 策略
    cur.execute("DELETE FROM virtual_balances WHERE strategy_id >= 6")
    rsi_strategies = [
        (6, 'RSI_14_35_65_L20', 'rsi', 14, 35, 65, 20),
        (7, 'RSI_7_30_75_L20', 'rsi', 7, 30, 75, 20),
        (8, 'RSI_7_35_75_L20', 'rsi', 7, 35, 75, 20),
        (9, 'RSI_7_20_75_L20', 'rsi', 7, 20, 75, 20),
        (10, 'RSI_14_35_70_L20', 'rsi', 14, 35, 70, 20),
        (11, 'RSI_7_35_65_L20', 'rsi', 7, 35, 65, 20),
        (12, 'RSI_7_25_75_L20', 'rsi', 7, 25, 75, 20),
        (13, 'RSI_7_35_70_L20', 'rsi', 7, 35, 70, 20),
        (14, 'RSI_14_35_75_L20', 'rsi', 14, 35, 75, 20),
        (15, 'RSI_7_20_70_L20', 'rsi', 7, 20, 70, 20),
    ]
    for sid, name, stype, period, os, ob, lev in rsi_strategies:
        cur.execute("""
            INSERT INTO virtual_balances (strategy_id, strategy_name, strategy_type, balance, initial_balance, leverage)
            VALUES (%s, %s, %s, 1000, 1000, %s)
            ON CONFLICT (strategy_id) DO UPDATE SET
                strategy_name = EXCLUDED.strategy_name,
                strategy_type = EXCLUDED.strategy_type
        """, (sid, name, stype, lev))
    
    # 初始化 strategies 表
    cur.execute("DELETE FROM strategies")
    all_strategies = [
        # BB 策略
        (1, 'BB策略 30x全仓', 'bb', None, None, None, 0.02, 0.06, 30, '全仓', '{"type":"bb_squeeze","tp":"triple"}'),
        (2, 'BB策略 30x逐仓', 'bb', None, None, None, 0.02, 0.06, 30, '逐仓', '{"type":"bb_squeeze","tp":"partial"}'),
        (3, 'BB策略 25x全仓', 'bb', None, None, None, 0.025, 0.075, 25, '全仓', '{"type":"bb_squeeze","tp":"triple"}'),
        (4, 'BB策略 25x逐仓', 'bb', None, None, None, 0.025, 0.075, 25, '逐仓', '{"type":"bb_squeeze","tp":"partial"}'),
        (5, 'BB策略 20x', 'bb', None, None, None, 0.03, 0.09, 20, '逐仓', '{"type":"bb_squeeze","tp":"partial"}'),
        # RSI 策略
        (6, 'RSI_14_35_65_L20', 'rsi', 14, 35, 65, 0.03, 0.15, 20, None, '{}'),
        (7, 'RSI_7_30_75_L20', 'rsi', 7, 30, 75, 0.04, 0.20, 20, None, '{}'),
        (8, 'RSI_7_35_75_L20', 'rsi', 7, 35, 75, 0.04, 0.20, 20, None, '{}'),
        (9, 'RSI_7_20_75_L20', 'rsi', 7, 20, 75, 0.05, 0.25, 20, None, '{}'),
        (10, 'RSI_14_35_70_L20', 'rsi', 14, 35, 70, 0.03, 0.15, 20, None, '{}'),
        (11, 'RSI_7_35_65_L20', 'rsi', 7, 35, 65, 0.035, 0.18, 20, None, '{}'),
        (12, 'RSI_7_25_75_L20', 'rsi', 7, 25, 75, 0.05, 0.25, 20, None, '{}'),
        (13, 'RSI_7_35_70_L20', 'rsi', 7, 35, 70, 0.04, 0.20, 20, None, '{}'),
        (14, 'RSI_14_35_75_L20', 'rsi', 14, 35, 75, 0.03, 0.12, 20, None, '{}'),
        (15, 'RSI_7_20_70_L20', 'rsi', 7, 20, 70, 0.05, 0.25, 20, None, '{}'),
    ]
    for s in all_strategies:
        cur.execute("""
            INSERT INTO strategies (id, name, type, rsi_period, oversold, overbought, stop_loss, take_profit, leverage, mode, params)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, s)
    
    conn.commit()
    print("   ✓ 初始化 15 个策略数据")
    
    # 6. 验证
    print("\n=== 验证 ===")
    cur.execute("SELECT COUNT(*) FROM virtual_balances")
    print(f"virtual_balances: {cur.fetchone()[0]} 条")
    cur.execute("SELECT COUNT(*) FROM strategies")
    print(f"strategies: {cur.fetchone()[0]} 条")
    cur.execute("SELECT COUNT(*) FROM market_data")
    print(f"market_data: {cur.fetchone()[0]} 条")
    cur.execute("SELECT COUNT(*) FROM btc_trades")
    print(f"btc_trades: {cur.fetchone()[0]} 条")
    
    cur.close()
    conn.close()
    
    print("\n✅ 数据库完善完成！")

if __name__ == "__main__":
    setup_database()
