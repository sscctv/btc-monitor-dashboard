// 数据库配置
const CONFIG = {
    // Supabase 配置
    SUPABASE_URL: 'https://lpcrnobolifrzwrkxoli.supabase.co',
    SUPABASE_KEY: 'sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug',

    // PostgreSQL 配置
    DB_CONFIG: {
        host: 'db.lpcrnobolifrzwrkxoli.supabase.co',
        port: 5432,
        user: 'postgres',
        password: 'sbsecretU3jwawwwnBTppSz0H1-QyQ_eb6rG-8C',
        database: 'postgres'
    }
};

// 策略配置
const STRATEGIES_CONFIG = {
    original: [
        { name: 'BB策略 30x全仓', sig: 'bb_squeeze', tp: 'triple', lev: 30, type: '全仓' },
        { name: 'BB策略 30x逐仓', sig: 'bb_squeeze', tp: 'partial', lev: 30, type: '逐仓' },
        { name: 'BB策略 25x全仓', sig: 'bb_squeeze', tp: 'triple', lev: 25, type: '全仓' },
        { name: 'BB策略 25x逐仓', sig: 'bb_squeeze', tp: 'partial', lev: 25, type: '逐仓' },
        { name: 'BB策略 20x', sig: 'bb_squeeze', tp: 'partial', lev: 20, type: '逐仓' }
    ],
    new: [
        { name: 'RSI_14_35_65_L20', rsi_period: 14, oversold: 35, overbought: 65, lev: 20 },
        { name: 'RSI_7_30_75_L20', rsi_period: 7, oversold: 30, overbought: 75, lev: 20 },
        { name: 'RSI_7_35_75_L20', rsi_period: 7, oversold: 35, overbought: 75, lev: 20 },
        { name: 'RSI_7_20_75_L20', rsi_period: 7, oversold: 20, overbought: 75, lev: 20 },
        { name: 'RSI_14_35_70_L20', rsi_period: 14, oversold: 35, overbought: 70, lev: 20 },
        { name: 'RSI_7_35_65_L20', rsi_period: 7, oversold: 35, overbought: 65, lev: 20 },
        { name: 'RSI_7_25_75_L20', rsi_period: 7, oversold: 25, overbought: 75, lev: 20 },
        { name: 'RSI_7_35_70_L20', rsi_period: 7, oversold: 35, overbought: 70, lev: 20 },
        { name: 'RSI_14_35_75_L20', rsi_period: 14, oversold: 35, overbought: 75, lev: 20 },
        { name: 'RSI_7_20_70_L20', rsi_period: 7, oversold: 20, overbought: 70, lev: 20 }
    ]
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CONFIG, STRATEGIES_CONFIG };
}
