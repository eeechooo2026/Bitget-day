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
TIMEFRAME_1D = '1d'
MA_PERIODS = [5, 10, 20]
KDJ_RSV_PERIOD = 9
KDJ_SMOOTH = 3

# 调试开关：填入你想调试的币种（标准格式，如 'BLUR/USDT:USDT'）
DEBUG_SYMBOLS = ['BLUR/USDT:USDT']   # 可修改为其他币种，留空则关闭调试
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
        print("📤 正在发送推送请求...")
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=10)
        result = response.json()
        if result.get("code") == 1000:
            print("✅ WxPusher 推送成功!")
        else:
            print(f"❌ 推送失败: {result}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")

def get_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_4h_period_start_timestamp(beijing_dt, offset_periods=0):
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
    utc_start = period_start - timedelta(hours=8)
    return int(utc_start.timestamp() * 1000)

def get_daily_period_start_timestamp(beijing_dt, offset_days=0):
    day_start = beijing_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start += timedelta(days=offset_days)
    utc_start = day_start - timedelta(hours=8)
    return int(utc_start.timestamp() * 1000)

def find_kline_by_timestamp(ohlcv, target_ts):
    for k in ohlcv:
        if k[0] == target_ts:
            return k
    return None

def calculate_moving_averages(closes, periods):
    ma_values = {}
    for period in periods:
        if len(closes) >= period:
            ma_values[period] = sum(closes[-period:]) / period
        else:
            ma_values[period] = None
    return ma_values

def is_bullish_arrangement(ma_values):
    if ma_values[5] is None or ma_values[10] is None or ma_values[20] is None:
        return False
    return ma_values[5] > ma_values[10] > ma_values[20]

def calculate_kdj(highs, lows, closes, rsv_period=9, smooth=3):
    n = len(closes)
    k_values = [None] * n
    d_values = [None] * n
    j_values = [None] * n
    if n < rsv_period:
        return k_values, d_values, j_values
    k_prev = 50
    d_prev = 50
    for i in range(rsv_period - 1, n):
        period_high = max(highs[i - rsv_period + 1:i + 1])
        period_low = min(lows[i - rsv_period + 1:i + 1])
        if period_high == period_low:
            rsv = 50
        else:
            rsv = (closes[i] - period_low) / (period_high - period_low) * 100
        k = (k_prev * (smooth - 1) + rsv) / smooth
        d = (d_prev * (smooth - 1) + k) / smooth
        j = 3 * k - 2 * d
        k_values[i] = k
        d_values[i] = d
        j_values[i] = j
        k_prev, d_prev = k, d
    return k_values, d_values, j_values

def calculate_daily_gain(ohlcv_1d, target_ts, prev_ts):
    k_target = find_kline_by_timestamp(ohlcv_1d, target_ts)
    k_prev = find_kline_by_timestamp(ohlcv_1d, prev_ts)
    if not (k_target and k_prev):
        return None
    close_target = k_target[4]
    close_prev = k_prev[4]
    if close_prev == 0:
        return None
    return (close_target - close_prev) / close_prev * 100

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第七个工作流扫描 - 当前UTC时间: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根4小时K棒均线多头排列（MA5 > MA10 > MA20，且上根K棒收盘价 > MA5）")
    print(f"   • 上根4小时K棒收阳、最低价低于上上根K棒的最低价、且KDJ的J值大于上上根")
    print(f"📊 排序：按前两根日线K棒涨幅从高到低")
    
    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    
    # 加载市场数据
    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")
    swap_symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")
    
    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return
    
    # 计算时间戳
    prev1_ts_4h = get_4h_period_start_timestamp(beijing_now, -1)
    prev2_ts_4h = get_4h_period_start_timestamp(beijing_now, -2)
    prev1_ts_1d = get_daily_period_start_timestamp(beijing_now, -1)
    prev2_ts_1d = get_daily_period_start_timestamp(beijing_now, -2)
    
    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根4小时: {ts_to_beijing(prev1_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根4小时: {ts_to_beijing(prev2_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   排序用日线: {ts_to_beijing(prev2_ts_1d).strftime('%Y-%m-%d')} 和 {ts_to_beijing(prev1_ts_1d).strftime('%Y-%m-%d')}")
    
    print("⏳ 正在获取K线数据...")
    result_list = []
    
    for idx, symbol in enumerate(swap_symbols):
        is_debug = symbol in DEBUG_SYMBOLS
        if is_debug:
            print(f"\n🔍 详细分析 {symbol}")
        
        try:
            # 获取4小时K线
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=80)
            if len(ohlcv_4h) < 30:
                if is_debug: print(f"❌ 4小时K线不足30根 (实际{len(ohlcv_4h)})")
                continue
            
            # 获取日线K线
            ohlcv_1d = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1D, limit=10)
            if len(ohlcv_1d) < 5:
                if is_debug: print(f"❌ 日线K线不足5根 (实际{len(ohlcv_1d)})")
                continue
            
            # 计算均线
            closes_4h = [k[4] for k in ohlcv_4h]
            ma_values = calculate_moving_averages(closes_4h, MA_PERIODS)
            if not is_bullish_arrangement(ma_values):
                if is_debug: print(f"❌ 均线非多头: MA5={ma_values[5]:.4f}, MA10={ma_values[10]:.4f}, MA20={ma_values[20]:.4f}")
                continue
            if is_debug: print(f"✅ 均线多头: {ma_values[5]:.4f} > {ma_values[10]:.4f} > {ma_values[20]:.4f}")
            
            # 查找K线
            k_prev1 = find_kline_by_timestamp(ohlcv_4h, prev1_ts_4h)
            k_prev2 = find_kline_by_timestamp(ohlcv_4h, prev2_ts_4h)
            if not (k_prev1 and k_prev2):
                if is_debug: print(f"❌ 未找到目标K线: 上根={k_prev1 is not None}, 上上根={k_prev2 is not None}")
                continue
            if is_debug: print(f"✅ 找到目标K线")
            
            close1, open1, low1 = k_prev1[4], k_prev1[1], k_prev1[3]
            low2 = k_prev2[3]
            
            if is_debug: print(f"   上根: 收盘={close1:.4f}, 开盘={open1:.4f}, 最低={low1:.4f}")
            if is_debug: print(f"   上上根最低={low2:.4f}")
            
            # 收盘 > MA5
            if close1 <= ma_values[5]:
                if is_debug: print(f"❌ 收盘 {close1:.4f} <= MA5 {ma_values[5]:.4f}")
                continue
            if is_debug: print(f"✅ 收盘 > MA5")
            
            # 收阳
            if close1 <= open1:
                if is_debug: print(f"❌ 未收阳 (收盘<=开盘)")
                continue
            if is_debug: print(f"✅ 收阳")
            
            # 最低价低于上上根最低价
            if low1 >= low2:
                if is_debug: print(f"❌ 最低价 {low1:.4f} >= 上上根最低 {low2:.4f}")
                continue
            if is_debug: print(f"✅ 最低价创新低")
            
            # KDJ J值比较
            highs_4h = [k[2] for k in ohlcv_4h]
            lows_4h = [k[3] for k in ohlcv_4h]
            _, _, j_vals = calculate_kdj(highs_4h, lows_4h, closes_4h, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            
            idx1 = next((i for i, k in enumerate(ohlcv_4h) if k[0] == prev1_ts_4h), None)
            idx2 = next((i for i, k in enumerate(ohlcv_4h) if k[0] == prev2_ts_4h), None)
            if idx1 is None or idx2 is None or j_vals[idx1] is None or j_vals[idx2] is None:
                if is_debug: print(f"❌ 无法获取J值: idx1={idx1}, idx2={idx2}, j1={j_vals[idx1] if idx1 is not None else None}, j2={j_vals[idx2] if idx2 is not None else None}")
                continue
            if is_debug: print(f"   J值: 上上根={j_vals[idx2]:.2f}, 上根={j_vals[idx1]:.2f}")
            if j_vals[idx1] <= j_vals[idx2]:
                if is_debug: print(f"❌ J值未上升")
                continue
            if is_debug: print(f"✅ J值上升")
            
            # 日线涨幅
            gain_1d = calculate_daily_gain(ohlcv_1d, prev1_ts_1d, prev2_ts_1d)
            if gain_1d is None:
                if is_debug: print(f"❌ 日线涨幅计算失败")
                continue
            if is_debug: print(f"✅ 日线涨幅: {gain_1d:.2f}%")
            
            # 全部通过
            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain_1d': round(gain_1d, 2),
                'ma5': round(ma_values[5], 4),
                'ma10': round(ma_values[10], 4),
                'ma20': round(ma_values[20], 4),
                'close1': round(close1, 4),
                'low1': round(low1, 4),
                'low2': round(low2, 4),
                'j_prev2': round(j_vals[idx2], 2),
                'j_prev1': round(j_vals[idx1], 2),
            })
            print(f"🎉 {symbol} 通过所有条件！")
            
            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            if is_debug: print(f"⚠️ 异常: {e}")
            time.sleep(0.3)
    
    # 排序并推送
    result_list.sort(key=lambda x: x['gain_1d'], reverse=True)
    top = result_list[:PUSH_TOP_N]
    
    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 4小时级别扫描（第七个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根4小时K棒均线多头排列（MA5>MA10>MA20，且收盘价>MA5）",
        f"   • 上根4小时K棒收阳、最低价低于上上根最低价",
        f"   • 上根4小时K棒的KDJ的J值 > 上上根",
        f"📊 排序：按前两根日线K棒涨幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   日线涨幅: +{item['gain_1d']}%\n"
                f"   均线: {item['ma5']} > {item['ma10']} > {item['ma20']}\n"
                f"   上根收盘: {item['close1']} > MA5 ✅\n"
                f"   上根最低: {item['low1']} < 上上根最低 {item['low2']}\n"
                f"   J值变化: {item['j_prev2']} → {item['j_prev1']} 📈"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：4小时级别均线多头+创新低+J值上升，日线级别正处上涨阶段")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 今日未找到符合条件的币种")
    
    message = "\n".join(msg_lines)
    print("\n" + "="*50)
    print(message)
    print("="*50)
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
