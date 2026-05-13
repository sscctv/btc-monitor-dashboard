// 数据库配置 - 自动检测环境
const API_CONFIG = {
    // 检测是否为本地环境 (局域网IP或localhost)
    isLocal: window.location.hostname === 'localhost' || 
             window.location.hostname === '127.0.0.1' ||
             window.location.hostname.startsWith('192.168.') ||
             window.location.hostname.startsWith('10.') ||
             window.location.hostname.startsWith('172.'),
    
    // 本地数据库 (局域网)
    local: {
        baseUrl: 'http://192.168.1.2:5000/api'  // 修改为你的本地API地址
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

// 获取API基础URL
function getBaseUrl() {
    const source = getDataSource();
    return source.baseUrl || source.url;
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

// 从 Supabase 获取数据
async function fetchFromSupabase(table, params = '') {
    const source = API_CONFIG.supabase;
    try {
        const response = await fetch(`${source.url}/rest/v1/${table}?select=*${params}`, {
            headers: {
                'apikey': source.key,
                'Authorization': `Bearer ${source.key}`,
                'Content-Type': 'application/json'
            }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`Error fetching ${table}:`, error);
        return null;
    }
}

// 从本地API获取数据
async function fetchFromLocal(table) {
    try {
        const response = await fetch(`${API_CONFIG.local.baseUrl}/${table}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`Error fetching ${table} from local:`, error);
        return null;
    }
}

// 统一的数据获取接口
async function fetchData(table, params = '') {
    if (API_CONFIG.isLocal) {
        return await fetchFromLocal(table);
    } else {
        return await fetchFromSupabase(table, params);
    }
}

// 示例数据
const SAMPLE_BALANCES = [
    { strategy_name: 'BB策略 30x全仓', balance: 1000, initial_balance: 1000, total_pnl: 150.5, total_pnl_percent: 15.05, win_rate: 65, trade_count: 45 },
    { strategy_name: 'BB策略 30x逐仓', balance: 1200, initial_balance: 1000, total_pnl: 200.0, total_pnl_percent: 20.0, win_rate: 68, trade_count: 52 },
    { strategy_name: 'RSI_14_35_65_L20', balance: 850, initial_balance: 1000, total_pnl: -150.0, total_pnl_percent: -15.0, win_rate: 45, trade_count: 38 },
    { strategy_name: 'RSI_7_30_75_L20', balance: 1100, initial_balance: 1000, total_pnl: 100.0, total_pnl_percent: 10.0, win_rate: 55, trade_count: 42 },
    { strategy_name: 'RSI_7_35_75_L20', balance: 950, initial_balance: 1000, total_pnl: -50.0, total_pnl_percent: -5.0, win_rate: 50, trade_count: 35 }
];

// 导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { API_CONFIG, fetchData, fetchFromSupabase, fetchFromLocal, formatNumber, formatPercent, getPnLClass, SAMPLE_BALANCES };
}
