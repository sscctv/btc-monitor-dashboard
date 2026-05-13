const express = require('express');
const { Pool } = require('pg');

const app = express();
const PORT = 5000;

// PostgreSQL 连接配置
const pool = new Pool({
    host: '192.168.1.2',
    port: 5432,
    user: 'postgres',
    password: 'Postgres@2026',
    database: 'postgres'
});

// 测试连接
pool.query('SELECT NOW()', (err, res) => {
    if (err) {
        console.error('数据库连接失败:', err);
    } else {
        console.log('数据库连接成功:', res.rows[0].now);
    }
});

// 允许跨域
app.use((req, res, next) => {
    res.header('Access-Control-Allow-Origin', '*');
    res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept');
    next();
});

app.use(express.json());

// 获取所有交易记录
app.get('/api/btc_trades', async (req, res) => {
    try {
        const result = await pool.query(
            'SELECT * FROM btc_trades ORDER BY opened_at DESC LIMIT 500'
        );
        res.json(result.rows);
    } catch (err) {
        console.error('查询错误:', err);
        res.status(500).json({ error: err.message });
    }
});

// 获取统计数据（按账户分组）
app.get('/api/stats', async (req, res) => {
    try {
        const result = await pool.query(`
            SELECT 
                COALESCE(strategy, account_id, 'Unknown') as strategy_name,
                COUNT(*) as trade_count,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(realized_pnl) as total_pnl
            FROM btc_trades 
            GROUP BY COALESCE(strategy, account_id, 'Unknown')
            ORDER BY total_pnl DESC
        `);
        
        const stats = result.rows.map(row => ({
            strategy_name: row.strategy_name,
            trade_count: parseInt(row.trade_count),
            win_rate: row.trade_count > 0 ? (parseInt(row.wins) / parseInt(row.trade_count)) * 100 : 0,
            total_pnl: parseFloat(row.total_pnl) || 0
        }));
        
        res.json(stats);
    } catch (err) {
        console.error('查询错误:', err);
        res.status(500).json({ error: err.message });
    }
});

// 获取市场数据
app.get('/api/market', async (req, res) => {
    try {
        const result = await pool.query(
            'SELECT * FROM market_data ORDER BY created_at DESC LIMIT 1'
        );
        res.json(result.rows[0] || null);
    } catch (err) {
        console.error('查询错误:', err);
        res.status(500).json({ error: err.message });
    }
});

// 健康检查
app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.listen(PORT, () => {
    console.log(`本地 API 服务运行在 http://0.0.0.0:${PORT}`);
});
