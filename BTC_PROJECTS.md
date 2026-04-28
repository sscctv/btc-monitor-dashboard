# BTC 交易系统完整项目手册

_最后更新：2026-04-28_

---

## 📁 项目仓库

| 仓库名 | 用途 | 地址 |
|--------|------|------|
| **btc-monitor-dashboard** | 主要监控面板（前端 + 脚本） | https://github.com/sscctv/btc-monitor-dashboard |
| btc-monitor-v2 | 第二版本 | https://github.com/sscctv/btc-monitor-v2 |
| btc-monitor-final | 最终版本 | https://github.com/sscctv/btc-monitor-final |

---

## 🌐 相关地址

| 服务 | 地址 | 说明 |
|------|------|------|
| 监控面板 | `http://192.168.1.2:5011` | 行情 + 虚拟账户 |
| World Monitor | `http://192.168.1.2:3000` | OSINT 数据 |
| World Monitor API | `http://192.168.1.2:3000/api/bootstrap` | 主数据出口 |
| Clash 管理 | `http://127.0.0.1:9090` | TUN 模式开关 |
| Railway | https://railway.com/ | 部署平台 |
| Supabase | `lpcrnobolifrzwrkxoli.supabase.co` | 数据库 |

---

## 📂 本地脚本（/tmp/）

| 文件 | 用途 |
|------|------|
| `okx_data_fetcher_v3.1.py` | OKX 行情 + 信号 + GROQ 情绪 |
| `virt_trade.py` | 虚拟账户 V1/V2/V3 |
| `monitor_all.py` | 综合监控 |
| `morning_review.py` | 每日 08:00 复盘 |
| `wm_bridge.py` | World Monitor 桥接 |
| `dashboard_server.py` | 面板服务（5011） |

### 数据文件
- `market_data.json` — 实时行情信号
- `virt_positions.json` — 虚拟账户状态
- `okx_trading_v3.db` — 交易记录（SQLite）

### GitHub 克隆
```
/tmp/btc-repo/ → https://github.com/sscctv/btc-monitor-dashboard
```

---

## 🔧 代码同步

```bash
cp /tmp/*.py /tmp/btc-repo/
cd /tmp/btc-repo && git add -A && git commit -m "说明" && git push origin main
```

---

## 🚀 进程管理

| 进程 | 命令 |
|------|------|
| 行情采集 | `nohup python3 -u /tmp/okx_data_fetcher_v3.1.py >> /tmp/fetcher_v3.1.log 2>&1 &` |
| 虚拟交易 | `nohup python3 -u /tmp/virt_trade.py >> /tmp/virt_trade.log 2>&1 &` |
| 综合监控 | `nohup python3 -u /tmp/monitor_all.py >> /tmp/monitor_all.log 2>&1 &` |
| 面板服务 | `nohup python3 -u /tmp/dashboard_server.py >> /tmp/dashboard.log 2>&1 &` |

---

## 📊 Supabase 表

```
btc_accounts: account_id, capital, strategy, status, updated_at
btc_trades: id, account_id, side, entry_price, sl, tp, size, leverage,
            status, opened_at, closed_at, close_price, realized_pnl,
            created_at, liqprice, margin, unrealizedpnl, strategy
```

---

## ⚠️ 注意

1. V1/V2/V3：30%-50% 风险敞口，100X 杠杆，无固定止损，靠信号判断
2. OKX 合约：`BTC-USDT-SWAP`（线性永续）
3. GitHub 密钥保护：代码推送自动替换占位符，本地 `/tmp/` 存真实密钥
4. AAII 情绪每周四更新

---

_此文件为系统核心记忆_
