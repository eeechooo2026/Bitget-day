import ccxt
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import requests
import json

# WxPusher 配置（从环境变量读取）
APP_TOKEN = os.environ.get('WX_PUSHER_APP_TOKEN')
UID = os.environ.get('WX_PUSHER_UID')

def send_message(msg):
    """发送微信推送"""
    if not APP_TOKEN or not UID:
        print("未配置推送信息，仅打印结果")
        return
    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": APP_TOKEN,
        "content": msg,
        "summary": msg[:50],
        "contentType": 1,
        "uids": [UID],
    }
    headers = {"Content-Type": "application/json"}
    try:
        requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        print(f"推送失败: {e}")

def check_recent_candles(symbol, days=7):
    try:
        exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        since = exchange.parse8601((datetime.utcnow() - timedelta(days=days+2)).isoformat())
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', since=since, limit=days+3)
        if not ohlcv:
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['amplitude'] = (df['high'] - df['low']) / df['low'] * 100
        df['is_bullish'] = df['close'] > df['open']
        matched = df[(df['is_bullish'] == True) & (df['amplitude'] > 100)]
        if not matched.empty:
            latest = matched.iloc[-1]
            return {
                'symbol': symbol.replace('/USDT:USDT', ''),
                'date': latest['date'].strftime('%Y-%m-%d'),
                'amplitude': round(latest['amplitude'], 2),
                'gain': round((latest['close'] - latest['open']) / latest['open'] * 100, 2)
            }
    except Exception:
        pass
    return None

def main():
    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    print("加载合约列表...")
    markets = exchange.load_markets()
    symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"共找到 {len(symbols)} 个合约，开始扫描最近7天...")
    
    results = []
    total = len(symbols)
    for i, sym in enumerate(symbols):
        res = check_recent_candles(sym)
        if res:
            results.append(res)
            print(f"[+] {res['symbol']} {res['date']} 振幅 {res['amplitude']}% 涨幅 {res['gain']}%")
        if (i+1) % 50 == 0:
            print(f"进度: {i+1}/{total}")
        time.sleep(0.1)
    
    # 保存结果到文件
    with open('result.txt', 'w') as f:
        f.write(f"扫描时间: {datetime.now()}\n")
        f.write(f"符合条件的币种数量: {len(results)}\n")
        for r in results:
            f.write(f"{r['symbol']} | {r['date']} | 振幅 {r['amplitude']}% | 涨幅 {r['gain']}%\n")
    
    # 推送微信消息
    if results:
        msg = f"发现 {len(results)} 个币种在最近7天出现振幅>100%的阳线：\n"
        for r in results[:10]:  # 最多显示10个
            msg += f"{r['symbol']} {r['date']} 振幅{r['amplitude']}%\n"
        if len(results) > 10:
            msg += f"...等{len(results)}个"
        send_message(msg)
    else:
        send_message("最近7天未发现振幅>100%的阳线币种")

if __name__ == "__main__":
    main()
