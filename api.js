// 数据库配置 - 自动检测环境
const API_CONFIG = {
    // 检测是否为本地环境 (局域网IP或localhost)
    isLocal: window.location.hostname === 'localhost' || 
             window.location.hostname === '127.0.0.1' ||
             window.location.hostname.startsWith('192.168.') ||
             window.location.hostname.startsWith('10.') ||
             window.location.hostname.startsWith('172.'),
    
    // 本地数据库 API 服务
    local: {
        baseUrl: 'http://192.168.1.2:5000/api'
    },
    
    // Supabase 云端数据库
    supabase: {
        url: 'https://lpcrnobolifrzwrkxoli.supabase.co',
        key: 'sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug'
    }
};

// 获取市场信号数据
async function fetchMarketSignals() {
    try {
        const response = await fetch('/data.json');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('获取市场数据错误:', error);
        return null;
    }
}

// 格式化数字
function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined || isNaN(num)) return '--';
    return Number(num).toLocaleString('en-US', { 
        minimumFractionDigits: decimals, 
        maximumFractionDigits: decimals 
    });
}

// 格式化百分比
function formatPercent(num) {
    if (num === null || num === undefined || isNaN(num)) return '--';
    return (num >= 0 ? '+' : '') + num.toFixed(2) + '%';
}

// 获取盈亏样式类
function getPnLClass(value) {
    if (value === null || value === undefined || isNaN(value)) return '';
    return value >= 0 ? 'profit' : 'loss';
}

// ============ API 获取 ============
async function fetchFromSupabase(table, params = '') {
    try {
        const response = await fetch(`${API_CONFIG.supabase.url}/rest/v1/${table}?select=*${params}`, {
            headers: {
                'apikey': API_CONFIG.supabase.key,
                'Authorization': `Bearer ${API_CONFIG.supabase.key}`,
                'Content-Type': 'application/json'
            }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`Supabase 错误 [${table}]:`, error);
        return null;
    }
}

async function fetchFromLocal(endpoint) {
    try {
        const response = await fetch(`${API_CONFIG.local.baseUrl}/${endpoint}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`本地 API 错误:`, error);
        return null;
    }
}

// 获取所有交易记录
async function fetchAllTrades() {
    if (API_CONFIG.isLocal) {
        return await fetchFromLocal('btc_trades');
    } else {
        return await fetchFromSupabase('btc_trades', '&order=opened_at.desc&limit=500');
    }
}

// 根据实际数据库结构转换数据
// 注意：realized_pnl 为0时，从价格计算盈亏
function transformTradesData(rawData) {
    if (!rawData || !Array.isArray(rawData)) return [];
    
    const strategyMap = {};
    
    rawData.forEach(trade => {
        const strategy = trade.strategy || trade.account_id || 'Unknown';
        if (!strategyMap[strategy]) {
            strategyMap[strategy] = {
                strategy_name: strategy,
                balance: 10000,
                initial_balance: 10000,
                total_pnl: 0,
                total_pnl_percent: 0,
                win_rate: 0,
                trade_count: 0,
                wins: 0,
                losses: 0
            };
        }
        
        strategyMap[strategy].trade_count++;
        
        // 如果 realized_pnl 为0，从价格计算盈亏
        let pnl = trade.realized_pnl || 0;
        if (pnl === 0 && trade.entry_price && trade.close_price && trade.size) {
            // 盈亏 = (平仓价 - 开仓价) * 数量 * 方向系数
            const priceDiff = trade.close_price - trade.entry_price;
            const side = (trade.side === 'long' || trade.side === 'buy' || trade.side === 'LONG') ? 1 : -1;
            pnl = priceDiff * trade.size * side;
        }
        
        strategyMap[strategy].total_pnl += pnl;
        
        if (pnl > 0) {
            strategyMap[strategy].wins++;
        } else if (pnl < 0) {
            strategyMap[strategy].losses++;
        }
    });
    
    // 计算统计数据
    Object.values(strategyMap).forEach(s => {
        s.win_rate = s.trade_count > 0 ? (s.wins / s.trade_count) * 100 : 0;
        s.balance = s.initial_balance + s.total_pnl;
        s.total_pnl_percent = s.initial_balance > 0 ? (s.total_pnl / s.initial_balance) * 100 : 0;
    });
    
    return Object.values(strategyMap);
}

// 为交易记录计算盈亏
function enrichTradeWithPnL(trade) {
    // 如果 realized_pnl 已有值，直接使用
    if (trade.realized_pnl !== undefined && trade.realized_pnl !== null) {
        return trade;
    }
    
    // 否则从价格计算
    if (trade.entry_price && trade.close_price && trade.size) {
        const priceDiff = trade.close_price - trade.entry_price;
        const side = (trade.side === 'long' || trade.side === 'buy' || trade.side === 'LONG') ? 1 : -1;
        trade.realized_pnl = priceDiff * trade.size * side;
    } else {
        trade.realized_pnl = 0;
    }
    
    return trade;
}

// 示例数据
const SAMPLE_BALANCES = [
    { strategy_name: '实盘账户', balance: 10500, initial_balance: 10000, total_pnl: 500, total_pnl_percent: 5.0, win_rate: 60, trade_count: 20 },
    { strategy_name: '测试账户', balance: 9500, initial_balance: 10000, total_pnl: -500, total_pnl_percent: -5.0, win_rate: 45, trade_count: 15 }
];

// 导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { 
        API_CONFIG, 
        fetchAllTrades,
        transformTradesData,
        enrichTradeWithPnL,
        formatNumber, 
        formatPercent, 
        getPnLClass, 
        SAMPLE_BALANCES 
    };
}
