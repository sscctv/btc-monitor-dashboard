-- =====================================================
-- Supabase 数据库初始化 SQL
-- 执行此脚本创建与本地 PostgreSQL 同步的表结构
-- =====================================================

-- 1. 虚拟账户余额表
CREATE TABLE IF NOT EXISTS virtual_balances (
    strategy_id INTEGER PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    strategy_type TEXT,
    balance NUMERIC(18, 4) DEFAULT 1000,
    initial_balance NUMERIC(18, 4) DEFAULT 1000,
    position_type TEXT,
    position_entry NUMERIC(18, 4),
    position_size NUMERIC(18, 8),
    leverage INTEGER DEFAULT 20,
    last_update TIMESTAMPTZ,
    synced_at TIMESTAMPTZ
);

-- 2. 市场数据表
CREATE TABLE IF NOT EXISTS market_data (
    id SERIAL PRIMARY KEY,
    inst_id TEXT NOT NULL,
    price NUMERIC(18, 4),
    change_24h NUMERIC(10, 4),
    volume_24h NUMERIC(20, 2),
    high_24h NUMERIC(18, 4),
    low_24h NUMERIC(18, 4),
    ts BIGINT,
    dt TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 策略配置表
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    rsi_period INTEGER,
    oversold NUMERIC(5, 2),
    overbought NUMERIC(5, 2),
    stop_loss NUMERIC(5, 4),
    take_profit NUMERIC(5, 4),
    leverage INTEGER DEFAULT 20,
    mode TEXT,
    params TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. 交易记录表
CREATE TABLE IF NOT EXISTS btc_trades (
    id SERIAL,
    ts BIGINT NOT NULL,
    dt TIMESTAMPTZ,
    account TEXT NOT NULL,
    action TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price NUMERIC(18, 4),
    exit_price NUMERIC(18, 4),
    size NUMERIC(18, 8),
    pnl NUMERIC(18, 4),
    leverage INTEGER,
    strategy TEXT,
    signal_mode TEXT,
    reason TEXT,
    status TEXT DEFAULT 'closed',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. 同步日志表
CREATE TABLE IF NOT EXISTS sync_log (
    id SERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    records_synced INTEGER DEFAULT 0,
    status TEXT DEFAULT 'success',
    error_message TEXT,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- 索引
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_market_data_inst ON market_data(inst_id);
CREATE INDEX IF NOT EXISTS idx_market_data_ts ON market_data(ts DESC);
CREATE INDEX IF NOT EXISTS idx_btc_trades_strategy ON btc_trades(strategy);
CREATE INDEX IF NOT EXISTS idx_btc_trades_ts ON btc_trades(ts DESC);
CREATE INDEX IF NOT EXISTS idx_virtual_balances_type ON virtual_balances(strategy_type);

-- =====================================================
-- Row Level Security (RLS) 策略
-- =====================================================

ALTER TABLE virtual_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE btc_trades ENABLE ROW LEVEL SECURITY;

-- 允许匿名读取
CREATE POLICY "Allow anonymous read" ON virtual_balances FOR SELECT USING (true);
CREATE POLICY "Allow anonymous read" ON market_data FOR SELECT USING (true);
CREATE POLICY "Allow anonymous read" ON strategies FOR SELECT USING (true);
CREATE POLICY "Allow anonymous read" ON btc_trades FOR SELECT USING (true);

-- 允许服务端 KEY 写入 (用于同步脚本)
CREATE POLICY "Allow service role insert" ON virtual_balances FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow service role update" ON virtual_balances FOR UPDATE USING (true);
CREATE POLICY "Allow service role insert" ON market_data FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow service role update" ON market_data FOR UPDATE USING (true);
CREATE POLICY "Allow service role insert" ON strategies FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow service role update" ON strategies FOR UPDATE USING (true);
CREATE POLICY "Allow service role insert" ON btc_trades FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow service role update" ON btc_trades FOR UPDATE USING (true);
