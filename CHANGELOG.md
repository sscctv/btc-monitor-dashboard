# BTC Monitor Dashboard 更新说明

## 2026-05-13 更新

### 新增功能

#### 1. 多页面架构
- **index.html** - 首页：BTC价格、目标进度、Top 3策略概览
- **virtual.html** - 虚拟交易：资金曲线、交易记录、策略对比
- **signals.html** - 实时信号：技术指标、策略信号、多周期分析
- **strategies.html** - 策略管理：15个策略详情、交易记录弹窗
- **history.html** - 历史记录：每日收益、月度统计、回测记录

#### 2. 策略管理页面 (strategies.html)
- 显示所有15个策略（BB策略5个 + RSI策略10个）
- 每个策略卡片显示：
  - 初始资金、当前余额
  - 浮动盈亏（实时计算）
  - 持仓状态（做多/做空/空闲）
  - 交易胜率、交易次数
- 点击策略卡片弹出交易记录弹窗
- 收益对比柱状图

#### 3. 移动端优化
- 底部导航悬浮设计
- 大触摸区域按钮
- 响应式2列网格布局
- ECharts图表自适应

#### 4. 数据API
- **api.py** - Flask API服务
  - `/api/strategies` - 获取所有策略状态
  - `/api/trades` - 获取交易记录
  - `/api/history` - 获取历史数据
- **db_config.py** - 数据库配置
  - 支持Supabase云数据库
  - 支持本地PostgreSQL

### 文件清单

| 文件 | 说明 |
|:-----|:-----|
| index.html | 首页 |
| virtual.html | 虚拟交易页面 |
| signals.html | 实时信号页面 |
| strategies.html | 策略管理页面 |
| history.html | 历史记录页面 |
| styles.css | 统一样式文件 |
| config.js | 前端配置（数据库连接） |
| api.py | Flask API服务 |
| db_config.py | 数据库配置 |
| virt_top10_strategies.py | Top 10策略回测脚本 |

### 策略列表

#### BB策略 (5个)
| 策略名 | 杠杆 | 描述 |
|:-------|:-----|:-----|
| BB_30x_1 | 30x | 布林带策略，周期20 |
| BB_30x_2 | 30x | 布林带策略，周期25 |
| BB_25x_1 | 25x | 布林带策略，周期20 |
| BB_25x_2 | 25x | 布林带策略，周期25 |
| BB_25x_3 | 25x | 布林带策略，周期30 |

#### RSI策略 (10个)
| 策略名 | 描述 |
|:-------|:-----|
| RSI_Strategy_1~10 | RSI超买超卖策略，不同参数配置 |

### 数据库结构

#### virtual_trades 表
```sql
- id: 主键
- strategy_id: 策略ID
- strategy_name: 策略名称
- entry_price: 入场价格
- exit_price: 出场价格
- position_type: 持仓类型(做多/做空)
- pnl: 盈亏金额
- pnl_percent: 盈亏百分比
- leverage: 杠杆倍数
- status: 状态(开仓/平仓)
- created_at: 创建时间
- updated_at: 更新时间
```

#### virtual_balances 表
```sql
- id: 主键
- strategy_id: 策略ID
- strategy_name: 策略名称
- initial_balance: 初始资金
- current_balance: 当前余额
- total_pnl: 总盈亏
- win_rate: 胜率
- trade_count: 交易次数
- updated_at: 更新时间
```

### 使用说明

1. **启动API服务**
```bash
python api.py
```

2. **运行策略回测**
```bash
python virt_top10_strategies.py
```

3. **访问页面**
打开 index.html 查看首页，导航到各页面查看详情

### 更新日志

- 2026-05-13: 完成多页面架构、移动端优化、策略管理页面
