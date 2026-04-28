#!/usr/bin/env python3
"""
World Monitor Bridge - 从 World Monitor 拉取数据补充交易信号
"""
import requests
import json
import time
from datetime import datetime

PROXY = {'http': 'http://172.17.0.1:7890', 'https': 'http://172.17.0.1:7890'}
WM_URL = "http://192.168.1.2:3000/api/bootstrap"
STATE_FILE = "/tmp/wm_bridge_state.json"

def fetch_bootstrap():
    """从 World Monitor Bootstrap API 拉取数据"""
    try:
        r = requests.get(WM_URL, proxies=PROXY, timeout=10, verify=False)
        return json.loads(r.text).get('data', {})
    except Exception as e:
        print(f"Bootstrap fetch error: {e}")
        return {}

def analyze_aaii_sentiment(data):
    """分析 AAII 情绪（反向指标）"""
    aaii = data.get('aaiiSentiment', {})
    if not aaii or aaii.get('fallback'):
        return None
    
    latest = aaii.get('latest', {})
    if not latest:
        return None
    
    bullish = latest.get('bullish', 0)
    bearish = latest.get('bearish', 0)
    neutral = latest.get('neutral', 0)
    spread = bullish - bearish  # 正=看多倾向，负=看空倾向
    
    signal = 'neutral'
    if bullish > 50:
        signal = 'extreme_bullish'  # 极度看多 → 反向看空
    elif bearish > 50:
        signal = 'extreme_bearish'  # 极度看空 → 反向看多
    elif spread > 20:
        signal = 'bullish'
    elif spread < -20:
        signal = 'bearish'
    
    return {
        'signal': signal,
        'bullish': bullish,
        'bearish': bearish,
        'neutral': neutral,
        'spread': spread,
        'date': latest.get('date', '?'),
        'raw': latest
    }

def get_fear_greed(data):
    """获取恐慌贪婪指数"""
    fg = data.get('fearGreedIndex', {})
    if not fg:
        return None
    return fg

def get_crypto_market(data):
    """获取加密市场数据"""
    cq = data.get('cryptoQuotes', {})
    quotes = cq.get('quotes', [])
    btc = [q for q in quotes if q.get('id') == 'bitcoin']
    if btc:
        return btc[0]
    return None

def analyze_macro(data):
    """宏观分析 - BIS 数据"""
    results = {}
    
    # BIS DSR (债务服务率)
    bis = data.get('bisDsr', {})
    if bis:
        entries = bis.get('entries', [])
        # 找出杠杆最高的国家
        high_lever_countries = [e for e in entries if e.get('dsrPct', 0) > 25]
        if high_lever_countries:
            results['high_lever_countries'] = [(e['countryName'], e['dsrPct']) for e in high_lever_countries[:5]]
    
    return results

def should_combine_signals(wm_data, market_data):
    """
    结合 World Monitor 数据修正交易信号
    World Monitor 数据作为辅助过滤器
    """
    aaii = analyze_aaii_sentiment(wm_data)
    btc = get_crypto_market(wm_data)
    
    modifiers = {
        'bias': 'neutral',  # neutral / bullish / bearish
        'confidence_modifier': 0,  # -1 to +1
        'warnings': [],
        'alerts': []
    }
    
    # AAII 反向交易信号
    if aaii and aaii['signal'] == 'extreme_bearish':
        # AAII 极度看空(>50%) → 反向看多信号
        modifiers['bias'] = 'bullish'
        modifiers['confidence_modifier'] = 0.3
        modifiers['alerts'].append(f"🤖 AAII反向: {aaii['bullish']}%看多/{aaii['bearish']}%看空 → 偏多")
    elif aaii and aaii['signal'] == 'extreme_bullish':
        modifiers['bias'] = 'bearish'
        modifiers['confidence_modifier'] = -0.3
        modifiers['alerts'].append(f"🤖 AAII反向: {aaii['bullish']}%看多/{aaii['bearish']}%看空 → 偏空")
    
    # 恐慌贪婪
    fg = get_fear_greed(wm_data)
    if fg and isinstance(fg, dict):
        fg_value = fg.get('value', fg.get('score', 50))
        fg_class = fg.get('classification', 'Neutral')
        if fg_value and fg_value != 50:
            modifiers['warnings'].append(f"Fear/Greed: {fg_value} ({fg_class})")
    
    return modifiers

def main():
    print("=" * 60)
    print("World Monitor Bridge - 数据采集")
    print("=" * 60)
    
    last_alert_time = 0
    
    while True:
        try:
            data = fetch_bootstrap()
            if not data:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Bootstrap 获取失败")
                time.sleep(60)
                continue
            
            # 分析 AAII 情绪
            aaii = analyze_aaii_sentiment(data)
            btc = get_crypto_market(data)
            macro = analyze_macro(data)
            
            # 构建修饰符
            mods = should_combine_signals(data, None)
            
            # 保存状态
            state = {
                'aaii': aaii,
                'btc': btc,
                'macro': macro,
                'modifiers': mods,
                'updated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, ensure_ascii=False)
            
            # 日志输出
            aaii_str = f"AAII: {aaii['bullish']}%↑/{aaii['bearish']}%↓" if aaii else "AAII: 无数据"
            btc_price = f"${btc['current_price']:,}" if btc and isinstance(btc, dict) else "?"
            mods_str = f"| Bias:{mods['bias']} | Confidence:{mods['confidence_modifier']:+.1f}" if mods['bias'] != 'neutral' else ""
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] BTC={btc_price} | {aaii_str}{mods_str}")
            
            # 发送告警
            if mods.get('alerts') and time.time() - last_alert_time > 3600:
                for alert in mods['alerts']:
                    print(f"  🚨 {alert}")
                last_alert_time = time.time()
            
            # 结合信号系统
            # 每分钟检查一次
            time.sleep(60)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

if __name__ == '__main__':
    main()
