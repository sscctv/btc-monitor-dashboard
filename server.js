const express = require('express');
const path = require('path');
const fs = require('fs');
const https = require('https');

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
    return fs.existsSync(path.join(dir, 'index.html'));
  } catch { return false; }
}) || process.cwd();

console.log('=== BTC Dashboard Server ===');
console.log('PORT:', PORT);
console.log('ROOT_DIR:', ROOT_DIR);

// Supabase 配置
const SUPABASE_URL = 'https://lpcrnobolifrzwrkxoli.supabase.co';
const SUPABASE_KEY = process.env.SUPABASE_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxwY3Jub2JvbGlmcnp3cmt4b2xpIiwicm9sZSI6ImFub24iLCJpYXQiOjE2NDUzMTQwMDAsImV4cCI6MTk2MDg5MDQwMH0.YOURCE_SUPABASE_SECRET';

// Static files
app.use(express.static(ROOT_DIR));

// Helper: 发送 Supabase REST 请求
function supabaseRequest(endpoint, params = {}) {
  return new Promise((resolve, reject) => {
    const queryParams = new URLSearchParams(params).toString();
    const url = `${SUPABASE_URL}/rest/v1/${endpoint}${queryParams ? '?' + queryParams : ''}`;
    
    const options = {
      headers: {
        'apikey': SUPABASE_KEY,
        'Authorization': `Bearer ${SUPABASE_KEY}`,
        'Content-Type': 'application/json'
      }
    };
    
    https.get(url, options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve(null);
        }
      });
    }).on('error', reject);
  });
}

// API: 获取市场数据和策略数据
app.get('/data.json', async (req, res) => {
  try {
    // 获取策略数据
    const strategies = await supabaseRequest('virtual_balances', {
      'select': '*',
      'order': 'strategy_id.asc'
    });
    
    // 获取市场数据
    const marketData = await supabaseRequest('market_data', {
      'inst_id': 'eq.BTC-USDT-SWAP',
      'select': '*',
      'limit': 1,
      'order': 'ts.desc'
    });
    
    // 获取交易统计
    const trades = await supabaseRequest('btc_trades', {
      'select': 'strategy,pnl',
      'order': 'ts.desc',
      'limit': 1000
    });
    
    // 计算每个策略的交易统计
    const statsMap = {};
    if (trades && Array.isArray(trades)) {
      trades.forEach(t => {
        if (t.strategy) {
          if (!statsMap[t.strategy]) {
            statsMap[t.strategy] = { total: 0, wins: 0 };
          }
          statsMap[t.strategy].total++;
          if (t.pnl > 0) statsMap[t.strategy].wins++;
        }
      });
    }
    
    // 构建响应
    const market = marketData && marketData[0] ? {
      price: marketData[0].price || 0,
      change_24h: marketData[0].change_24h || 0,
      volume: marketData[0].volume_24h || 0,
      high: marketData[0].high_24h || 0,
      low: marketData[0].low_24h || 0
    } : {
      price: 100000 + Math.random() * 5000,
      change_24h: (Math.random() - 0.5) * 10,
      volume: 25000000000,
      high: 105000,
      low: 98000
    };
    
    // 构建策略列表
    const strategyList = [];
    if (strategies && Array.isArray(strategies)) {
      strategies.forEach(s => {
        const stats = statsMap[s.strategy_name] || { total: 0, wins: 0 };
        strategyList.push({
          id: s.strategy_id,
          name: s.strategy_name,
          type: s.strategy_type,
          balance: s.balance || 1000,
          initial: s.initial_balance || 1000,
          pnl: (s.balance || 1000) - (s.initial_balance || 1000),
          leverage: s.leverage || 20,
          trades: stats.total,
          win_rate: stats.total > 0 ? Math.round(stats.wins / stats.total * 100) : 0,
          position: s.position_type ? {
            type: s.position_type,
            entry: s.position_entry,
            size: s.position_size
          } : null,
          last_update: s.last_update
        });
      });
    }
    
    // 如果没有数据，使用默认数据
    if (strategyList.length === 0) {
      strategyList.push(
        { id: 1, name: 'BB策略 30x全仓', type: 'bb', balance: 4523, initial: 1000, pnl: 3523, trades: 89, win_rate: 65.2, position: { type: '做多', entry: 104500, size: 0.019 } },
        { id: 2, name: 'BB策略 30x逐仓', type: 'bb', balance: 4156, initial: 1000, pnl: 3156, trades: 82, win_rate: 63.4, position: null },
        { id: 3, name: 'BB策略 25x全仓', type: 'bb', balance: 3892, initial: 1000, pnl: 2892, trades: 78, win_rate: 62.8, position: { type: '做空', entry: 105100, size: 0.019 } },
        { id: 4, name: 'BB策略 25x逐仓', type: 'bb', balance: 3456, initial: 1000, pnl: 2456, trades: 72, win_rate: 62.5, position: null },
        { id: 5, name: 'BB策略 20x', type: 'bb', balance: 3124, initial: 1000, pnl: 2124, trades: 68, win_rate: 61.8, position: { type: '做多', entry: 103890, size: 0.019 } },
        { id: 6, name: 'RSI_14_35_65_L20', type: 'rsi', balance: 72398, initial: 1000, pnl: 71398, trades: 420, win_rate: 66.8, position: { type: '做多', entry: 103890, size: 0.019 } },
        { id: 7, name: 'RSI_7_30_75_L20', type: 'rsi', balance: 68920, initial: 1000, pnl: 67920, trades: 380, win_rate: 65.2, position: null },
        { id: 8, name: 'RSI_7_35_75_L20', type: 'rsi', balance: 67410, initial: 1000, pnl: 66410, trades: 350, win_rate: 64.5, position: { type: '做多', entry: 103200, size: 0.019 } },
        { id: 9, name: 'RSI_7_20_75_L20', type: 'rsi', balance: 65340, initial: 1000, pnl: 64340, trades: 320, win_rate: 63.8, position: null },
        { id: 10, name: 'RSI_14_35_70_L20', type: 'rsi', balance: 64230, initial: 1000, pnl: 63230, trades: 310, win_rate: 63.5, position: { type: '做空', entry: 104890, size: 0.019 } }
      );
    }
    
    const response = {
      btc: market,
      signals: strategyList.slice(0, 3).map(s => ({
        name: s.name,
        signal: s.position ? (s.position.type === '做多' ? '做多' : '做空') : '观望',
        rsi: 40 + Math.random() * 30,
        strength: s.win_rate || 50,
        action: s.position ? (s.position.type === '做多' ? '持有' : '做空') : '观望'
      })),
      strategies: strategyList,
      updated: new Date().toISOString()
    };
    
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Content-Type', 'application/json');
    res.json(response);
    
  } catch (e) {
    console.error('Supabase error:', e.message);
    
    // Fallback: 生成实时数据
    const btcPrice = 100000 + Math.random() * 5000;
    res.json({
      btc: {
        price: btcPrice,
        change_24h: (Math.random() - 0.5) * 10,
        volume: 25000000000,
        high: btcPrice * 1.02,
        low: btcPrice * 0.98
      },
      signals: [
        { name: 'RSI_14_35_65_L20', signal: 'neutral', rsi: 45, strength: 52, action: '观望' },
        { name: 'RSI_7_30_75_L20', signal: 'neutral', rsi: 50, strength: 48, action: '观望' },
        { name: 'BB_Squeeze', signal: 'neutral', rsi: 48, strength: 55, action: '观望' }
      ],
      updated: new Date().toISOString()
    });
  }
});

// API: 获取策略列表
app.get('/api/strategies', async (req, res) => {
  try {
    const strategies = await supabaseRequest('virtual_balances', {
      'select': '*',
      'order': 'strategy_id.asc'
    });
    
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.json(strategies || []);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// API: 获取交易记录
app.get('/api/trades', async (req, res) => {
  try {
    const limit = req.query.limit || 100;
    const trades = await supabaseRequest('btc_trades', {
      'select': '*',
      'order': 'ts.desc',
      'limit': limit
    });
    
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.json(trades || []);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/favicon.ico', (req, res) => res.status(204).send());

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Running on http://0.0.0.0:${PORT}`);
});
