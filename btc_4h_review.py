#!/usr/bin/env python3
"""
BTC 每4小时复盘报告
定时向微信发送复盘摘要
"""
import os
import json, time, urllib.request
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor

PG_HOST = '192.168.1.2'; PG_PORT = '5432'; PG_USER = 'postgres'
PG_PASSWORD = 'Postgres@2026'; PG_DB = 'postgres'
SB_KEY = os.getenv('SB_SECRET_KEY', '')
SB_BASE = 'https://lpcrnobolifrzwrkxoli.supabase.co/rest/v1'
TARGET = 'o9cq801cl6QXRfJWhroBxDriyjXA@im.wechat'

def pg_conn():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB, connect_timeout=5, cursor_factory=RealDictCursor)

def send_wechat(msg):
    import subprocess
    try:
        subprocess.run(['openclaw', 'message', 'send', '--channel', 'openclaw-weixin', '--target', TARGET, '--message', msg], capture_output=True, timeout=20)
    except:
        pass

def query_sig_stats(conn, hours=4):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT mode, COUNT(*) as cnt,
                   MAX(dt) as last_dt,
                   MIN(price) as min_price,
                   MAX(price) as max_price,
                   AVG(score) as avg_score
            FROM btc.signal_log
            WHERE dt > NOW() - INTERVAL '%s hours'
            GROUP BY mode ORDER BY cnt DESC
        """, (hours,))
        return cur.fetchall()

def query_trades(conn, hours=4):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT account, action, side, entry_price, exit_price, pnl, reason, dt
            FROM btc.all_trades
            WHERE dt > NOW() - INTERVAL '%s hours'
            ORDER BY ts DESC LIMIT 20
        """, (hours,))
        return cur.fetchall()

def query_balance(conn, hours=4):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT account, balance, equity, unrealized_pnl, dt
            FROM btc.balance_history
            WHERE dt > NOW() - INTERVAL '%s hours'
            AND (account, ts) IN (
                SELECT account, MAX(ts) FROM btc.balance_history
                WHERE dt > NOW() - INTERVAL '%s hours'
                GROUP BY account
            )
            ORDER BY account
        """, (hours, hours))
        return cur.fetchall()

def query_alerts(conn, hours=4):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT severity, alert_type, message, price, dt
            FROM btc.alert_log
            WHERE dt > NOW() - INTERVAL '%s hours'
            ORDER BY ts DESC LIMIT 10
        """, (hours,))
        return cur.fetchall()

def generate_report():
    conn = pg_conn()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        stats = query_sig_stats(conn, 4)
        trades = query_trades(conn, 4)
        balances = query_balance(conn, 4)
        alerts = query_alerts(conn, 4)
        conn.close()

        # 最新价格
        latest_price = stats[0]['max_price'] if stats else 0
        min_price = min(r['min_price'] for r in stats) if stats else 0
        max_price = max(r['max_price'] for r in stats) if stats else 0

        # 信号统计
        sig_lines = []
        for s in stats:
            sig_lines.append(f"  {s['mode']}: {s['cnt']}次")

        # 账户余额
        bal_lines = []
        for b in balances:
            pnl = b['unrealized_pnl'] or 0
            bal_lines.append(f"  {b['account']}: 余额{b['balance']:.2f}U 浮盈{pnl:+.2f}U")

        # 交易
        trade_lines = []
        for t in trades:
            pnl_str = f"{t['pnl']:+.2f}U" if t['pnl'] else '--'
            trade_lines.append(f"  {t['account']} {t['action']} {t['side']} {pnl_str} 理由:{t['reason'] or '--'}")

        # 预警
        alert_lines = []
        for a in alerts:
            alert_lines.append(f"  [{a['severity']}] {a['message']}")

        # 构建报告
        report = f"""━━━━━━━━━━━━━━━
📊 BTC 4小时复盘
{now}
━━━━━━━━━━━━━━━
📈 信号统计(4h):
{chr(10).join(sig_lines) if sig_lines else '  无信号'}

📊 价格区间:
  最高: ${max_price:,.0f}
  最低: ${min_price:,.0f}
  振幅: {(max_price-min_price)/min_price*100:.2f}%

💼 账户状态:
{chr(10).join(bal_lines) if bal_lines else '  无账户数据'}

📋 交易记录:
{chr(10).join(trade_lines) if trade_lines else '  无交易'}

🚨 预警:
{chr(10).join(alert_lines) if alert_lines else '  无预警'}

━━━━━━━━━━━━━━━"""
        return report
    except Exception as e:
        return f"复盘生成失败: {e}"

def main():
    print("生成4小时复盘...")
    report = generate_report()
    print(report)
    send_wechat(report)
    print("复盘已发送")

if __name__ == '__main__':
    main()
