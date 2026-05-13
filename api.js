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
        baseUrl: 'http://192.168.1.2:5000/api'  // 本地 Node.js API 服务地址
    },
    
    // Supabase 云端数据库
    supabase: {
        url: 'https://lpcrnobolifrzwrkxoli.supabase.co',
        key: 'sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug'
    }
};

// 获取当前数据源
function getDataSource() {
    return API_CONFIG.isLocal ? API_CONFIG.local : API_CONFIG.supabase;
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

// ============ 本地 API ============
async function fetchFromLocal(endpoint) {
    try {
        const response = await fetch(`${API_CONFIG.local.baseUrl}/${endpoint}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`本地 API 错误 [${endpoint}]:`, error);
        return null;
    }
}

// ============ Supabase API ============
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

// ============ 统一数据获取 ============

// 获取所有交易记录
async function fetchAllTrades() {
    if (API_CONFIG.isLocal) {
        return await fetchFromLocal('btc_trades');
    } else {
        return await fetchFromSupabase('btc_trades', '&order=opened_at.desc&limit=500');
    }
}

// 获取策略统计数据
async function fetchStrategyStats() {
    if (API_CONFIG.isLocal) {
        return await fetchFromLocal('stats');
    } else {
        const data = await fetchFromSupabase('btc_trades');
        return transformTradesData(data);
    }
}

// 获取市场数据
async function fetchMarketData() {
    if (API_CONFIG.isLocal) {
        return await fetchFromLocal('market');
    } else {
        return await fetchFromSupabase('market_data', '&order=created_at.desc&limit=1');
    }
}

// 根据实际数据库结构转换数据
function transformTradesData(rawData) {
    if (!rawData || !Array.isArray(rawData)) return [];
    
    const strategyMap = {};
    
    rawData.forEach(trade => {
        const strategy = trade.strategy || trade.account_id || 'Unknown';
        if (!strategyMap[strategy]) {
            strategyMap[strategy] = {
                strategy_name: strategy,
                balance: 0,
                initial_balance: 1000,
                total_pnl: 0,
                total_pnl_percent: 0,
                win_rate: 0,
                trade_count: 0,
                wins: 0
            };
        }
        
        strategyMap[strategy].trade_count++;
        const pnl = trade.realized_pnl || 0;
        strategyMap[strategy].total_pnl += pnl;
        if (pnl > 0) strategyMap[strategy].wins++;
    });
    
    Object.values(strategyMap).forEach(s => {
        s.win_rate = s.trade_count > 0 ? (s.wins / s.trade_count) * 100 : 0;
        s.balance = s.initial_balance + s.total_pnl;
        s.total_pnl_percent = s.initial_balance > 0 ? (s.total_pnl / s.initial_balance) * 100 : 0;
    });
    
    return Object.values(strategyMap);
}

// 示例数据
const SAMPLE_BALANCES = [
    { strategy_name: '实盘账户', balance: 10000, initial_balance: 10000, total_pnl: 1500.5, total_pnl_percent: 15.0, win_rate: 65, trade_count: 45 },
    { strategy_name: '测试账户', balance: 8500, initial_balance: 10000, total_pnl: -1500.0, total_pnl_percent: -15.0, win_rate: 45, trade_count: 38 }
];

// 导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { 
        API_CONFIG, 
        fetchData, 
        fetchFromLocal, 
        fetchFromSupabase,
        fetchAllTrades,
        fetchStrategyStats,
        fetchMarketData,
        transformTradesData,
        formatNumber, 
        formatPercent, 
        getPnLClass, 
        SAMPLE_BALANCES 
    };
}
