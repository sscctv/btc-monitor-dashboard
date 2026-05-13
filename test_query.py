import urllib.request
import json

# 查询所有交易统计
url = 'https://lpcrnobolifrzwrkxoli.supabase.co/rest/v1/btc_trades?select=*&limit=50'
headers = {
    'apikey': 'sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug',
    'Authorization': 'Bearer sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug'
}

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode())
        print(f'共 {len(data)} 条记录')
        
        # 统计
        pnls = [t.get('realized_pnl', 0) for t in data]
        total_pnl = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        
        print(f'总盈亏: {total_pnl}')
        print(f'盈利: {wins}, 亏损: {losses}')
        print(f'胜率: {wins/len(data)*100:.1f}%' if data else 'N/A')
        
        # 显示非零盈亏的记录
        print('\n非零盈亏记录:')
        for t in data:
            if t.get('realized_pnl', 0) != 0:
                print(f"  {t.get('account_id')}: pnl={t.get('realized_pnl')}")
except Exception as e:
    print(f'错误: {e}')
