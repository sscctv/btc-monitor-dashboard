#!/usr/bin/env python3
"""
API 服务 - 提供策略数据给前端
Flask 轻量级 API
"""

from flask import Flask, jsonify, request
import json
from datetime import datetime
from db_config import (
    get_all_strategies_data, 
    get_strategy_trades, 
    get_current_positions,
    ORIGINAL_STRATEGIES,
    NEW_STRATEGIES
)

app = Flask(__name__)

# ============== API 端点 ==============

@app.route('/api/strategies', methods=['GET'])
def api_strategies():
    """获取所有策略列表"""
    data = get_all_strategies_data()
    if data is None:
        # 如果数据库连接失败，返回模拟数据
        data = get_mock_strategies()
    return jsonify(data)


@app.route('/api/strategies/<int:strategy_id>', methods=['GET'])
def api_strategy_detail(strategy_id):
    """获取指定策略详情"""
    data = get_all_strategies_data()
    if data:
        for s in data:
            if s['id'] == strategy_id:
                return jsonify(s)
    return jsonify({'error': 'Strategy not found'}), 404


@app.route('/api/strategies/<int:strategy_id>/trades', methods=['GET'])
def api_strategy_trades(strategy_id):
    """获取指定策略的交易记录"""
    limit = request.args.get('limit', 50, type=int)
    trades = get_strategy_trades(strategy_id, limit)
    if not trades:
        trades = get_mock_trades(strategy_id)
    return jsonify(trades)


@app.route('/api/positions', methods=['GET'])
def api_positions():
    """获取所有当前持仓"""
    positions = get_current_positions()
    if not positions:
        positions = get_mock_positions()
    return jsonify(positions)


@app.route('/api/stats', methods=['GET'])
def api_stats():
    """获取总览统计"""
    data = get_all_strategies_data()
    if data is None:
        data = get_mock_strategies()
    
    total_balance = sum(s['balance'] for s in data)
    total_initial = sum(s['initial'] for s in data)
    total_pnl = total_balance - total_initial
    total_trades = sum(s['trades'] for s in data)
    
    return jsonify({
        'total_strategies': len(data),
        'total_balance': total_balance,
        'total_initial': total_initial,
        'total_pnl': total_pnl,
        'total_trades': total_trades,
        'updated_at': datetime.now().isoformat()
    })


# ============== 模拟数据 (数据库连接失败时使用) ==============

def get_mock_strategies():
    """生成模拟策略数据"""
    bb_data = [
        {'id': 1, 'name': 'BB策略 30x全仓', 'type': 'bb', 'lev': 30, 'mode': '全仓', 
         'initial': 1000, 'balance': 4523, 'pnl': 3523, 'trades': 89, 'win_rate': 65.2,
         'position': {'type': '做多', 'entry': 104500, 'size': 0.019}},
        {'id': 2, 'name': 'BB策略 30x逐仓', 'type': 'bb', 'lev': 30, 'mode': '逐仓',
         'initial': 1000, 'balance': 4156, 'pnl': 3156, 'trades': 82, 'win_rate': 63.4,
         'position': None},
        {'id': 3, 'name': 'BB策略 25x全仓', 'type': 'bb', 'lev': 25, 'mode': '全仓',
         'initial': 1000, 'balance': 3892, 'pnl': 2892, 'trades': 78, 'win_rate': 62.8,
         'position': {'type': '做空', 'entry': 105100, 'size': 0.019}},
        {'id': 4, 'name': 'BB策略 25x逐仓', 'type': 'bb', 'lev': 25, 'mode': '逐仓',
         'initial': 1000, 'balance': 3456, 'pnl': 2456, 'trades': 72, 'win_rate': 62.5,
         'position': None},
        {'id': 5, 'name': 'BB策略 20x', 'type': 'bb', 'lev': 20, 'mode': '逐仓',
         'initial': 1000, 'balance': 3124, 'pnl': 2124, 'trades': 68, 'win_rate': 61.8,
         'position': {'type': '做多', 'entry': 103890, 'size': 0.019}},
    ]
    
    rsi_data = [
        {'id': 6, 'name': 'RSI_14_35_65_L20', 'type': 'rsi', 'params': '周期14 | 35/65',
         'initial': 1000, 'balance': 72398, 'pnl': 71398, 'trades': 420, 'win_rate': 66.8,
         'position': {'type': '做多', 'entry': 103890, 'size': 0.019}},
        {'id': 7, 'name': 'RSI_7_30_75_L20', 'type': 'rsi', 'params': '周期7 | 30/75',
         'initial': 1000, 'balance': 68920, 'pnl': 67920, 'trades': 380, 'win_rate': 65.2,
         'position': None},
        {'id': 8, 'name': 'RSI_7_35_75_L20', 'type': 'rsi', 'params': '周期7 | 35/75',
         'initial': 1000, 'balance': 67410, 'pnl': 66410, 'trades': 350, 'win_rate': 64.5,
         'position': {'type': '做多', 'entry': 103200, 'size': 0.019}},
        {'id': 9, 'name': 'RSI_7_20_75_L20', 'type': 'rsi', 'params': '周期7 | 20/75',
         'initial': 1000, 'balance': 65340, 'pnl': 64340, 'trades': 320, 'win_rate': 63.8,
         'position': None},
        {'id': 10, 'name': 'RSI_14_35_70_L20', 'type': 'rsi', 'params': '周期14 | 35/70',
         'initial': 1000, 'balance': 64230, 'pnl': 63230, 'trades': 310, 'win_rate': 63.5,
         'position': {'type': '做空', 'entry': 104890, 'size': 0.019}},
        {'id': 11, 'name': 'RSI_7_35_65_L20', 'type': 'rsi', 'params': '周期7 | 35/65',
         'initial': 1000, 'balance': 63120, 'pnl': 62120, 'trades': 295, 'win_rate': 63.0,
         'position': None},
        {'id': 12, 'name': 'RSI_7_25_75_L20', 'type': 'rsi', 'params': '周期7 | 25/75',
         'initial': 1000, 'balance': 62010, 'pnl': 61010, 'trades': 285, 'win_rate': 62.4,
         'position': {'type': '做多', 'entry': 103500, 'size': 0.019}},
        {'id': 13, 'name': 'RSI_7_35_70_L20', 'type': 'rsi', 'params': '周期7 | 35/70',
         'initial': 1000, 'balance': 60890, 'pnl': 59890, 'trades': 275, 'win_rate': 61.8,
         'position': None},
        {'id': 14, 'name': 'RSI_14_35_75_L20', 'type': 'rsi', 'params': '周期14 | 35/75',
         'initial': 1000, 'balance': 59780, 'pnl': 58780, 'trades': 265, 'win_rate': 61.1,
         'position': {'type': '做多', 'entry': 102800, 'size': 0.019}},
        {'id': 15, 'name': 'RSI_7_20_70_L20', 'type': 'rsi', 'params': '周期7 | 20/70',
         'initial': 1000, 'balance': 58670, 'pnl': 57670, 'trades': 255, 'win_rate': 60.4,
         'position': None},
    ]
    
    return bb_data + rsi_data


def get_mock_trades(strategy_id):
    """生成模拟交易记录"""
    trades = []
    base_time = datetime.now()
    
    for i in range(10):
        trades.append({
            'id': i + 1,
            'type': '做多' if i % 2 == 0 else '做空',
            'entry_price': 103000 + i * 100,
            'exit_price': 103500 + i * 100,
            'position_size': 0.019,
            'pnl': 89 if i % 3 != 2 else -35,
            'pnl_percent': 4.5 if i % 3 != 2 else -1.8,
            'reason': '止盈' if i % 3 != 2 else '止损',
            'created_at': (base_time.replace(hour=14-i*2)).isoformat(),
            'closed_at': (base_time.replace(hour=15-i*2)).isoformat()
        })
    
    return trades


def get_mock_positions():
    """生成模拟持仓"""
    return [
        {'strategy_id': 1, 'type': '做多', 'entry': 104500, 'size': 0.019},
        {'strategy_id': 3, 'type': '做空', 'entry': 105100, 'size': 0.019},
        {'strategy_id': 5, 'type': '做多', 'entry': 103890, 'size': 0.019},
        {'strategy_id': 6, 'type': '做多', 'entry': 103890, 'size': 0.019},
    ]


# ============== CORS 支持 ==============
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    return response


# ============== 启动 ==============
if __name__ == '__main__':
    print("启动 API 服务...")
    print("端点:")
    print("  GET /api/strategies          - 获取所有策略")
    print("  GET /api/strategies/<id>     - 获取指定策略")
    print("  GET /api/strategies/<id>/trades - 获取交易记录")
    print("  GET /api/positions           - 获取当前持仓")
    print("  GET /api/stats              - 获取总览统计")
    app.run(host='0.0.0.0', port=5000, debug=True)