# BTC Dashboard 本地 API 服务

## 功能
连接本地 PostgreSQL 数据库，为前端 Dashboard 提供 REST API。

## 安装

```bash
cd server
npm install
```

## 启动

```bash
npm start
```

服务将在 `http://0.0.0.0:5000` 启动

## API 端点

| 端点 | 方法 | 说明 |
|:-----|:-----|:-----|
| `/api/btc_trades` | GET | 获取所有交易记录 |
| `/api/stats` | GET | 获取按账户分组的统计数据 |
| `/api/market` | GET | 获取市场数据 |
| `/api/health` | GET | 健康检查 |

## 数据库连接配置

- Host: 192.168.1.2
- Port: 5432
- Database: postgres
- User: postgres
- Password: Postgres@2026

## 前端配置

前端会自动检测访问环境：
- 本地访问 (localhost/192.168.x.x) → 使用本地 API
- 云端访问 → 使用 Supabase
