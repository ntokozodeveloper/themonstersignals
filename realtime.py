from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
CORS(app)

def calculate_probability(sma_50, sma_200):
    distance = abs(sma_50 - sma_200)
    max_distance = max(sma_50, sma_200)
    probability = (distance / max_distance) * 100
    return round(probability, 2)

def recommend_lot_size(probability, account_balance):
    risk_per_trade = 0.01  # 1% of the account balance
    if probability >= 80:
        lot_size_factor = 0.02
    elif probability >= 60:
        lot_size_factor = 0.015
    elif probability >= 40:
        lot_size_factor = 0.01
    else:
        lot_size_factor = 0.005
    
    lot_size = account_balance * risk_per_trade * lot_size_factor
    return round(lot_size, 2)

def download_data(ticker_symbol, interval, start_date, end_date):
    try:
        data = yf.download(ticker_symbol, start=start_date, end=end_date, interval=interval)
        if data.empty:
            logging.info(f"No data available for {ticker_symbol} at interval {interval}")
            return None
        return data
    except Exception as e:
        logging.error(f"Error downloading data for {ticker_symbol} at interval {interval}: {e}")
        return None

@app.route('/api/trade', methods=['POST'])
def trade():
    data = request.json

    symbol = data.get('symbol')
    amount = data.get('amount')
    contract_type = data.get('contract_type')
    deriv_api_token = data.get('deriv_api_token')
    stop_loss_percent = data.get('stop_loss_percent', 1)  # default 1% stop loss
    take_profit_percent = data.get('take_profit_percent', 2)  # default 2% take profit

    if not symbol or not amount or not contract_type:
        return jsonify({'errors': 'Invalid input'}), 400

    
    # Adjust ticker symbol format for Yahoo Finance
    ticker_symbol = f'{symbol}=X'

    start_date = '2020-01-01'
    end_date = '2026-05-29'

    intervals = ['3mo', '1mo', '1wk', '1d', '1h', '90m', '30m', '15m']
    data_frames = {}

    for interval in intervals:
        data_frames[interval] = download_data(ticker_symbol, interval, start_date, end_date)

    # Filter out None values
    data_frames = {k: v for k, v in data_frames.items() if v is not None}

    # Calculate SMAs for available time frames
    for interval, data in data_frames.items():
        data['SMA_50'] = data['Close'].rolling(window=50).mean()
        data['SMA_200'] = data['Close'].rolling(window=200).mean()

    # Generate trade signals based on different time frames
    timeframe_displayed = None
    recent_signal_1h = None
    recent_signal_30m = None

    if '1h' in data_frames:
        data_1h = data_frames['1h']
        data_1h['Signal'] = np.where(data_1h['SMA_50'] > data_1h['SMA_200'], 1, 0)
        data_1h['Position'] = data_1h['Signal'].diff()
        recent_signal_1h = data_1h.iloc[-1] if not data_1h.empty else None

    if '30m' in data_frames:
        data_30m = data_frames['30m']
        data_30m['Signal'] = np.where(data_30m['SMA_50'] > data_30m['SMA_200'], 1, 0)
        data_30m['Position'] = data_30m['Signal'].diff()
        recent_signal_30m = data_30m.iloc[-1] if not data_30m.empty else None

    # Determine trade signal (based on the shortest timeframe with a signal)
    if recent_signal_30m is not None:
        trade_signal = 'buy' if recent_signal_30m['Signal'] == 1 else 'sell'
        entry_price = recent_signal_30m['Close']
        probability = calculate_probability(recent_signal_30m['SMA_50'], recent_signal_30m['SMA_200'])
        timeframe_displayed = '30 Minutes'
    elif recent_signal_1h is not None:
        trade_signal = 'buy' if recent_signal_1h['Signal'] == 1 else 'sell'
        entry_price = recent_signal_1h['Close']
        probability = calculate_probability(recent_signal_1h['SMA_50'], recent_signal_1h['SMA_200'])
        timeframe_displayed = '1 Hour'
    else:
        trade_signal = 'hold'
        entry_price = None
        probability = 0
        timeframe_displayed = 'No signal'

    if trade_signal != 'hold':
        stop_loss = entry_price * (1 - stop_loss_percent / 100) if trade_signal == 'buy' else entry_price * (1 + stop_loss_percent / 100)
        take_profit = entry_price * (1 + take_profit_percent / 100) if trade_signal == 'buy' else entry_price * (1 - take_profit_percent / 100)
    else:
        stop_loss = None
        take_profit = None

    lot_sizes = {}
    for balance in [100, 200, 500, 1000, 2000, 5000, 10000]:
        lot_sizes[f'Account Balance {balance}'] = recommend_lot_size(probability, balance)

    result = {
        'status': 'success',
        'message': f'Trade signal: {trade_signal}',
        'entry_price': entry_price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'probability': f'{probability}%',
        'recommended_lot_sizes': lot_sizes,
        'timeframe_displayed': timeframe_displayed,
    }

    return jsonify(result)

if __name__ == '__main__':
    app.run(port=5000)
