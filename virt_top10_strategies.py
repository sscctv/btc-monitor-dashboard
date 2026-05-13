#!/usr/bin/env python3
"""
BTC Top 10 策略虚拟交易系统
基于RSI超买超卖指标的回测和模拟交易
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

class Top10Strategy:
    """Top 10 RSI 策略基类"""
    
    def __init__(self, name, rsi_period=14, oversold=35, overbought=65, 
                 leverage=20, stop_loss=0.03, take_profit=0.15):
        self.name = name
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.leverage = leverage
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        
    def calculate_rsi(self, prices, period=None):
        """计算RSI指标"""
        if period is None:
            period = self.rsi_period
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def should_long(self, rsi):
        """是否应该做多"""
        return rsi < self.oversold
    
    def should_short(self, rsi):
        """是否应该做空"""
        return rsi > self.overbought
    
    def should_close_long(self, rsi):
        """是否应该平多"""
        return rsi > self.overbought
    
    def should_close_short(self, rsi):
        """是否应该平空"""
        return rsi < self.oversold
    
    def get_stop_loss(self, entry_price, is_long):
        """计算止损价格"""
        if is_long:
            return entry_price * (1 - self.stop_loss / self.leverage)
        else:
            return entry_price * (1 + self.stop_loss / self.leverage)
    
    def get_take_profit(self, entry_price, is_long):
        """计算止盈价格"""
        if is_long:
            return entry_price * (1 + self.take_profit / self.leverage)
        else:
            return entry_price * (1 - self.take_profit / self.leverage)
    
    def to_dict(self):
        return {
            "name": self.name,
            "rsi_period": self.rsi_period,
            "oversold": self.oversold,
            "overbought": self.overbought,
            "leverage": self.leverage,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit
        }


# Top 10 策略配置
TOP10_STRATEGIES = [
    Top10Strategy("RSI_14_35_65_L20", rsi_period=14, oversold=35, overbought=65, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_7_30_75_L20", rsi_period=7, oversold=30, overbought=75, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_7_35_75_L20", rsi_period=7, oversold=35, overbought=75, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_7_20_75_L20", rsi_period=7, oversold=20, overbought=75, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_14_35_70_L20", rsi_period=14, oversold=35, overbought=70, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_7_35_65_L20", rsi_period=7, oversold=35, overbought=65, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_7_25_75_L20", rsi_period=7, oversold=25, overbought=75, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_7_35_70_L20", rsi_period=7, oversold=35, overbought=70, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_14_35_75_L20", rsi_period=14, oversold=35, overbought=75, leverage=20, stop_loss=0.03, take_profit=0.15),
    Top10Strategy("RSI_7_20_70_L20", rsi_period=7, oversold=20, overbought=70, leverage=20, stop_loss=0.03, take_profit=0.15),
]


class VirtualTrader:
    """虚拟交易器"""
    
    def __init__(self, initial_balance=1000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions = []
        self.trades = []
        self.equity_curve = []
        
    def open_position(self, strategy, price, is_long, timestamp):
        """开仓"""
        position_size = self.balance * 0.1  # 每次用10%仓位
        stop_loss = strategy.get_stop_loss(price, is_long)
        take_profit = strategy.get_take_profit(price, is_long)
        
        position = {
            "strategy": strategy.name,
            "is_long": is_long,
            "entry_price": price,
            "position_size": position_size,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "entry_time": timestamp,
            "leverage": strategy.leverage
        }
        self.positions.append(position)
        return position
    
    def close_position(self, position, price, timestamp, reason="手动平仓"):
        """平仓"""
        entry_price = position["entry_price"]
        is_long = position["is_long"]
        position_size = position["position_size"]
        leverage = position["leverage"]
        
        if is_long:
            pnl_percent = (price - entry_price) / entry_price * leverage
        else:
            pnl_percent = (entry_price - price) / entry_price * leverage
        
        pnl = position_size * pnl_percent
        self.balance += pnl
        
        trade = {
            "strategy": position["strategy"],
            "type": "做多" if is_long else "做空",
            "entry_price": entry_price,
            "exit_price": price,
            "position_size": position_size,
            "pnl": pnl,
            "pnl_percent": pnl_percent * 100,
            "entry_time": position["entry_time"],
            "exit_time": timestamp,
            "duration": (timestamp - position["entry_time"]).total_seconds() / 3600,
            "reason": reason
        }
        self.trades.append(trade)
        self.positions.remove(position)
        return trade
    
    def check_positions(self, price, timestamp):
        """检查持仓是否需要止损止盈"""
        closed_trades = []
        for position in self.positions[:]:
            if position["is_long"]:
                if price <= position["stop_loss"]:
                    closed_trades.append(self.close_position(position, price, timestamp, "止损"))
                elif price >= position["take_profit"]:
                    closed_trades.append(self.close_position(position, price, timestamp, "止盈"))
            else:
                if price >= position["stop_loss"]:
                    closed_trades.append(self.close_position(position, price, timestamp, "止损"))
                elif price <= position["take_profit"]:
                    closed_trades.append(self.close_position(position, price, timestamp, "止盈"))
        return closed_trades
    
    def record_equity(self, price, timestamp):
        """记录权益曲线"""
        position_value = sum(
            (price - p["entry_price"]) / p["entry_price"] * p["position_size"] * p["leverage"]
            if p["is_long"]
            else (p["entry_price"] - price) / p["entry_price"] * p["position_size"] * p["leverage"]
            for p in self.positions
        )
        self.equity_curve.append({
            "timestamp": timestamp,
            "balance": self.balance,
            "equity": self.balance + position_value,
            "price": price
        })
    
    def get_stats(self):
        """获取统计信息"""
        if not self.trades:
            return None
            
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t["pnl"] > 0]
        losing_trades = [t for t in self.trades if t["pnl"] <= 0]
        
        return {
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": len(winning_trades) / total_trades * 100 if total_trades > 0 else 0,
            "total_pnl": sum(t["pnl"] for t in self.trades),
            "avg_win": np.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0,
            "avg_loss": np.mean([t["pnl"] for t in losing_trades]) if losing_trades else 0,
            "final_balance": self.balance,
            "total_return": (self.balance - self.initial_balance) / self.initial_balance * 100
        }


def run_backtest(strategy, prices, timestamps):
    """运行回测"""
    trader = VirtualTrader()
    
    for i in range(strategy.rsi_period, len(prices)):
        current_price = prices[i]
        timestamp = timestamps[i]
        
        # 检查止损止盈
        trader.check_positions(current_price, timestamp)
        
        # 计算RSI
        rsi = strategy.calculate_rsi(prices[:i+1])
        
        # 检查开仓信号
        if not trader.positions:
            if strategy.should_long(rsi):
                trader.open_position(strategy, current_price, True, timestamp)
            elif strategy.should_short(rsi):
                trader.open_position(strategy, current_price, False, timestamp)
        
        # 记录权益
        trader.record_equity(current_price, timestamp)
    
    # 平掉所有持仓
    for position in trader.positions[:]:
        trader.close_position(position, prices[-1], timestamps[-1], "回测结束")
    
    return trader


def main():
    print("=" * 60)
    print("BTC Top 10 策略回测系统")
    print("=" * 60)
    
    # 生成模拟数据（实际使用时从API获取）
    np.random.seed(42)
    days = 15
    hours = days * 24
    base_price = 100000
    prices = [base_price]
    
    for _ in range(hours):
        change = np.random.normal(0, 0.02) * prices[-1]
        prices.append(prices[-1] + change)
    
    timestamps = [datetime.now() - timedelta(hours=hours-i) for i in range(hours+1)]
    prices = np.array(prices)
    
    results = []
    
    for i, strategy in enumerate(TOP10_STRATEGIES):
        print(f"\n回测策略 {i+1}/10: {strategy.name}")
        
        trader = run_backtest(strategy, prices, timestamps)
        stats = trader.get_stats()
        
        if stats:
            results.append({
                "rank": i + 1,
                "strategy": strategy.name,
                "params": strategy.to_dict(),
                "stats": stats,
                "equity_curve": trader.equity_curve,
                "trades": trader.trades
            })
            
            print(f"  总交易次数: {stats['total_trades']}")
            print(f"  胜率: {stats['win_rate']:.1f}%")
            print(f"  最终资金: ${stats['final_balance']:.2f}")
            print(f"  总收益率: {stats['total_return']:.2f}%")
    
    # 按收益率排序
    results.sort(key=lambda x: x["stats"]["total_return"], reverse=True)
    
    print("\n" + "=" * 60)
    print("回测结果排名")
    print("=" * 60)
    
    for i, r in enumerate(results):
        print(f"\n{i+1}. {r['strategy']}")
        print(f"   收益率: {r['stats']['total_return']:.2f}%")
        print(f"   胜率: {r['stats']['win_rate']:.1f}%")
    
    # 保存结果
    with open("backtest_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    print("\n\n结果已保存到 backtest_results.json")


if __name__ == "__main__":
    main()