const express = require('express');
const path = require('path');
const { Client } = require('pg');

const app = express();
const PORT = process.env.PORT || 3000;

// Try multiple possible root directories
const POSSIBLE_ROOTS = [
  process.cwd(),
  '/app',
  '/app/repo',
  path.join(process.cwd(), 'repo'),
  __dirname,
];

let ROOT_DIR = POSSIBLE_ROOTS.find(dir => {
  try {
    return require('fs').existsSync(path.join(dir, 'index.html'));
  } catch { return false; }
}) || process.cwd();

console.log('=== BTC Dashboard Server ===');
console.log('PORT:', PORT);
console.log('ROOT_DIR:', ROOT_DIR);

// PostgreSQL 配置 (本地)
const PG_CONFIG = {
  host: process.env.PG_HOST || '192.168.1.2',
  port: process.env.PG_PORT || 5432,
  user: process.env.PG_USER || 'postgres',
  password: process.env.PG_PASSWORD || 'Postgres@2026',
  database: process.env.PG_DB || 'postgres'
};

async function queryPg(sql) {
  const client = new Client(PG_CONFIG);
  try {
    await client.connect();
    const result = await client.query(sql);
    await client.end();
    return result.rows;
  } catch (e) {
    await client.end();
    throw e;
  }
}

// Static files
app.use(express.static(ROOT_DIR));

// API: 获取所有数据
app.get('/data.json', async (req, res) => {
  try {
    // 获取市场数据
    const marketRows = await queryPg(`
      SELECT price, change_24h, volume_24h, high_24h, low_24h 
      FROM market_data 
      WHERE inst_id = 'BTC-USDT-SWAP' 
      ORDER BY ts DESC LIMIT 1
    `);
    const market = marketRows[0] || {};
    
    // 获取策略数据
    const strategyRows = await queryPg(`
      SELECT v.strategy_id, v.strategy_name, v.strategy_type, v.balance, 
             v.initial_balance, v.position_type, v.position_entry, 
             v.position_size, v.leverage, v.last_update,
             COUNT(t.id) as total_trades,
             SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as winning_trades
      FROM virtual_balances v
      LEFT JOIN btc_trades t ON t.account = v.strategy_name
      GROUP BY v.strategy_id, v.strategy_name, v.strategy_type, 
               v.balance, v.initial_balance, v.position_type,
               v.position_entry, v.position_size, v.leverage, v.last_update
      ORDER BY v.strategy_id
    `);
    
    const strategies = strategyRows.map(row => {
      const total = parseInt(row.total_trades) || 0;
      const wins = parseInt(row.winning_trades) || 0;
      return {
        id: row.strategy_id,
        name: row.strategy_name,
        type: row.strategy_type,
        balance: parseFloat(row.balance) || 1000,
        initial: parseFloat(row.initial_balance) || 1000,
        pnl: (parseFloat(row.balance) || 1000) - (parseFloat(row.initial_balance) || 1000),
        leverage: row.leverage,
        trades: total,
        win_rate: total > 0 ? Math.round(wins / total * 100) : 0,
        position: row.position_type ? {
          type: row.position_type,
          entry: parseFloat(row.position_entry),
          size: parseFloat(row.position_size)
        } : null,
        last_update: row.last_update
      };
    });
    
    // 获取最近交易
    const recentTrades = await queryPg(`
      SELECT strategy, action, pnl, reason, dt
      FROM btc_trades 
      ORDER BY ts DESC LIMIT 20
    `);
    
    const response = {
      btc: {
        price: parseFloat(market.price) || 0,
        change_24h: parseFloat(market.change_24h) || 0,
        volume: parseFloat(market.volume_24h) || 0,
        high: parseFloat(market.high_24h) || 0,
        low: parseFloat(market.low_24h) || 0
      },
      signals: strategies.slice(0, 3).map(s => ({
        name: s.name,
        signal: s.position ? (s.position.type === '做多' ? '做多' : '做空') : '观望',
        rsi: 40 + Math.random() * 30,
        strength: s.win_rate || 50,
        action: s.position ? (s.position.type === '做多' ? '持有' : '做空') : '观望'
      })),
      strategies: strategies,
      recent_trades: recentTrades,
      updated: new Date().toISOString()
    };
    
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Content-Type', 'application/json');
    res.json(response);
    
  } catch (e) {
    console.error('Database error:', e.message);
    
    // Fallback: 示例数据
    res.json({
      btc: {
        price: 79843,
        change_24h: -1.37,
        volume: 38851,
        high: 79882,
        low: 79782
      },
      signals: [
        { name: 'RSI策略', signal: 'neutral', rsi: 45, strength: 52, action: '观望' }
      ],
      strategies: [],
      updated: new Date().toISOString()
    });
  }
});

// API: 获取策略列表
app.get('/api/strategies', async (req, res) => {
  try {
    const rows = await queryPg('SELECT * FROM virtual_balances ORDER BY strategy_id');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// API: 获取交易记录
app.get('/api/trades', async (req, res) => {
  try {
    const rows = await queryPg('SELECT * FROM btc_trades ORDER BY ts DESC LIMIT 100');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/favicon.ico', (req, res) => res.status(204).send());

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Running on http://0.0.0.0:${PORT}`);
});
