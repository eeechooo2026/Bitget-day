import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10
TIMEFRAME_4H = '4h'
MA_PERIODS = [5, 10, 20]
KDJ_RSV_PERIOD = 9
KDJ_SMOOTH = 3
# =============================================

def send_push_wxpusher(message):
    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": WX_PUSHER_APP_TOKEN,
        "content": message,
        "summary": message[:50],
        "contentType": 1,
        "uids": [WX_PUSHER_UID],
    }
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=10)
        result = response.json()
        if result.get("code") == 1000:
            print("✅ 推送成功")
        else:
            print(f"❌ 推送失败: {result}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")

def get_beijing_now():
    """获取当前北京时间（datetime对象，无时区信息但数值为北京时间）"""
    utc_now = datetime.now(timezone.utc)
    beijing_now = utc_now + timedelta(hours=8)
    return beijing_now.replace(tzinfo=None)  # 移除时区，后续当作本地时间处理

def get_4h_period_start_timestamp(beijing_dt, offset_periods=0):
    """
    根据北京时间，获取指定偏移量的4小时K线周期的开始时间戳（毫秒，UTC）
    offset_periods: 0表示当前周期，-1表示上一个周期，-2表示上上个周期，以此类推
    """
    hour = beijing_dt.hour
    if 0 <= hour < 4:
        start_hour = 0
    elif 4 <= hour < 8:
        start_hour = 4
    elif 8 <= hour < 12:
        start_hour = 8
    elif 12 <= hour < 16:
        start_hour = 12
    elif 16 <= hour < 20:
        start_hour = 16
    else:
        start_hour = 20

    period_start = beijing_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    period_start += timedelta(hours=offset_periods * 4)
    # 转换为UTC时间戳（毫秒）
    utc_start = period_start - timedelta(hours=8)
    return int(utc_start.timestamp() * 1000)

def find_kline_by_timestamp(ohlcv, target_ts):
    for k in ohlcv:
        if k[0] == target_ts:
            return k
    return None

def calculate_ma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def is_bullish_arrangement(ma5, ma10, ma20):
    return ma5 is not None and ma10 is not None and ma20 is not None and ma5 > ma10 > ma20

def is_consolidation(close, prev_high, prev_low):
    return close < prev_high and close > prev_low

def calculate_kdj(highs, lows, closes, rsv_period=9, smooth=3):
    n = len(closes)
    k_vals = [None]*n
    d_vals = [None]*n
    j_vals = [None]*n
    if n < rsv_period:
        return k_vals, d_vals, j_vals
    k_prev = 50
    d_prev = 50
    for i in range(rsv_period-1, n):
        high_max = max(highs[i-rsv_period+1:i+1])
        low_min = min(lows[i-rsv_period+1:i+1])
        if high_max == low_min:
            rsv = 50
        else:
            rsv = (closes[i] - low_min) / (high_max - low_min) * 100
        k = (k_prev*(smooth-1) + rsv) / smooth
        d = (d_prev*(smooth-1) + k) / smooth
        j = 3*k - 2*d
        k_vals[i] = k
        d_vals[i] = d
        j_vals[i] = j
        k_prev, d_prev = k, d
    return k_vals, d_vals, j_vals

def main():
    beijing_now = get_beijing_now()
    print(f"🚀 扫描开始 - 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 计算目标K线的时间戳（UTC）
    prev1_ts = get_4h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts = get_4h_period_start_timestamp(beijing_now, -2)   # 上上根
    prev3_ts = get_4h_period_start_timestamp(beijing_now, -3)   # 上上上根
    
    # 将时间戳转换为北京时间用于显示
    def ts_to_beijing(ts):
        return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)
    
    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上上根: {ts_to_beijing(prev3_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    
    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    
    # 获取所有合约
    print("📡 加载市场数据...")
    markets = exchange.load_markets()
    swap_symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"📊 共找到 {len(swap_symbols)} 个USDT本位合约")
    
    # 获取24h涨幅
    tickers = exchange.fetch_tickers()
    gain24h = {s: t['percentage'] for s, t in tickers.items() if '/USDT:USDT' in s and t.get('percentage') is not None}
    
    results = []
    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=50)
            if len(ohlcv) < 30:
                continue
            
            closes = [k[4] for k in ohlcv]
            ma5 = calculate_ma(closes, 5)
            ma10 = calculate_ma(closes, 10)
            ma20 = calculate_ma(closes, 20)
            if not is_bullish_arrangement(ma5, ma10, ma20):
                continue
            
            k_prev1 = find_kline_by_timestamp(ohlcv, prev1_ts)
            k_prev2 = find_kline_by_timestamp(ohlcv, prev2_ts)
            k_prev3 = find_kline_by_timestamp(ohlcv, prev3_ts)
            if not (k_prev1 and k_prev2 and k_prev3):
                continue
            
            close1 = k_prev1[4]
            high1 = k_prev1[2]
            low1 = k_prev1[3]
            close2 = k_prev2[4]
            high2 = k_prev2[2]
            low2 = k_prev2[3]
            high3 = k_prev3[2]
            low3 = k_prev3[3]
            
            if close1 <= ma5:
                continue
            
            if not (is_consolidation(close2, high3, low3) and is_consolidation(close1, high2, low2)):
                continue
            
            highs = [k[2] for k in ohlcv]
            lows = [k[3] for k in ohlcv]
            _, _, j_vals = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv) if k[0] == prev1_ts), None)
            idx2 = next((i for i, k in enumerate(ohlcv) if k[0] == prev2_ts), None)
            if idx1 is None or idx2 is None or j_vals[idx1] is None or j_vals[idx2] is None:
                continue
            if j_vals[idx1] <= j_vals[idx2]:
                continue
            
            gain = gain24h.get(symbol, 0)
            results.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain': round(gain, 2),
                'ma5': round(ma5, 4),
                'ma10': round(ma10, 4),
                'ma20': round(ma20, 4),
                'close1': round(close1, 4),
                'j_prev2': round(j_vals[idx2], 2),
                'j_prev1': round(j_vals[idx1], 2),
                'close2': round(close2, 4),
                'high3': round(high3, 4),
                'low3': round(low3, 4),
                'high2': round(high2, 4),
                'low2': round(low2, 4),
            })
            print(f"✓ {symbol} 满足条件, 24h涨幅{gain:.2f}%")
            
            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ {symbol} 分析出错: {e}")
            time.sleep(0.3)
    
    results.sort(key=lambda x: x['gain'], reverse=True)
    top = results[:PUSH_TOP_N]
    
    msg = f"📊 Bitget 均线多头+双K线震荡+KDJ上升\n🕘 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M')}\n"
    msg += "📈 条件: MA5>MA10>MA20 & 上根收盘>MA5 & 双K线震荡 & J值上升\n"
    msg += f"📊 共{len(results)}个, 推送Top{len(top)}\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(top, 1):
        msg += f"{i}. {r['symbol']}\n   24h涨: +{r['gain']}%\n"
        msg += f"   均线: {r['ma5']}>{r['ma10']}>{r['ma20']}\n"
        msg += f"   上根收盘 {r['close1']} > MA5 ✅\n"
        msg += f"   J值: {r['j_prev2']}→{r['j_prev1']} 📈\n"
        msg += f"   上上根震荡: {r['close2']} ∈ [{r['low3']}-{r['high3']}]\n"
        msg += f"   上根震荡: {r['close1']} ∈ [{r['low2']}-{r['high2']}]\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n💡 解读: 均线多头+区间震荡+动能增强\n⚠️ 仅供参考"
    
    send_push_wxpusher(msg)

if __name__ == "__main__":
    main()
