#!/usr/bin/env python3
"""
数据采集脚本 - 从 OKX API 拉取 K线数据存入本地 PostgreSQL
独立运行，持续写入，供交易策略读取

运行方式:
    python3 collector.py              # 单次
    python3 collector.py --loop 300  # 每5分钟（默认）
"""
import sys
import time
import requests
import psycopg2
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# ============== 配置 ==============
PG_CONFIG = {
    'host': '192.168.1.2',
    'port': 5432,
    'user': 'postgres',
    'password': 'Postgres@2026',
    'database': 'postgres'
}

OKX_API = "https://www.okx.com"
SYMBOL = "BTC-USDT-SWAP"
INTERVAL = "5m"

# ============== 数据库 ==============

def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG, connect_timeout=5)

def init_market_table():
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_data (
            id SERIAL PRIMARY KEY,
            inst_id TEXT,
            ts BIGINT,
            price NUMERIC(18, 4),
            change_24h NUMERIC(10, 4),
            volume_24h NUMERIC(24, 4),
            high_24h NUMERIC(18, 4),
            low_24h NUMERIC(18, 4),
            dt TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # 创建普通索引（不要求唯一，允许数据清洗后重建）
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_data_inst_ts
        ON market_data(inst_id, ts)
    """)
    conn.commit()
    cur.close()
    conn.close()

# ============== OKX API ==============

def fetch_klines(limit=300):
    """从 OKX 获取历史K线"""
    url = f"{OKX_API}/api/v5/market/history-candles"
    params = {"instId": SYMBOL, "bar": INTERVAL, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    if data.get("code") == "0":
        return data["data"]
    return []

# ============== 主逻辑 ==============

def run_collection_cycle():
    print(f"\n{datetime.now().strftime('%H:%M:%S')} 采集K线数据...")

    candles = fetch_klines(300)
    if not candles:
        print("  获取数据失败")
        return

    conn = get_pg_conn()
    cur = conn.cursor()
    inserted = 0

    # 计算24h涨跌
    latest_price = float(candles[0][4])
    oldest_price = float(candles[-1][4])
    change_24h = (latest_price - oldest_price) / oldest_price * 100 if oldest_price > 0 else 0

    # 按时间升序插入所有K线
    for c in candles:
        ts = int(c[0])
        price = float(c[4])
        volume = float(c[5])
        high = float(c[2])
        low = float(c[3])
        dt = datetime.fromtimestamp(ts / 1000)

        cur.execute("""
            INSERT INTO market_data (inst_id, ts, price, change_24h, volume_24h, high_24h, low_24h, dt)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (inst_id, ts) DO UPDATE SET
                price = EXCLUDED.price,
                volume_24h = EXCLUDED.volume_24h,
                high_24h = EXCLUDED.high_24h,
                low_24h = EXCLUDED.low_24h,
                change_24h = EXCLUDED.change_24h
        """, (SYMBOL, ts, price, change_24h, volume, high, low, dt))

    conn.commit()
    cur.close()
    conn.close()

    # 同时更新最新价格到单独的行（供快速查询）
    conn = get_pg_conn()
    cur = conn.cursor()
    latest = candles[0]
    ts = int(latest[0])
    price = float(latest[4])
    volume = float(latest[5])
    high = float(latest[2])
    low = float(latest[3])
    dt = datetime.fromtimestamp(ts / 1000)

    cur.execute("""
        INSERT INTO market_data (inst_id, ts, price, change_24h, volume_24h, high_24h, low_24h, dt)
        VALUES ('BTC-USDT-SWAP', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (inst_id, ts) DO UPDATE SET
            price = EXCLUDED.price, volume_24h = EXCLUDED.volume_24h,
            high_24h = EXCLUDED.high_24h, low_24h = EXCLUDED.low_24h
    """, (ts, price, change_24h, volume, high, low, dt))
    conn.commit()
    cur.close()
    conn.close()

    print(f"  OK: 写入 {inserted} 条K线 | BTC=${price:.2f} | {change_24h:+.2f}%")
    return inserted

# ============== 入口 ==============

if __name__ == "__main__":
    init_market_table()
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        print(f"采集循环: 每 {interval} 秒执行一次")
        # 先跑一次填充历史
        run_collection_cycle()
        while True:
            time.sleep(interval)
            run_collection_cycle()
    else:
        run_collection_cycle()