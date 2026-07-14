import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10
TIMEFRAME_1H = '1h'
TIMEFRAME_4H = '4h'
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

def get_period_start_timestamp(beijing_dt, offset_periods=0, timeframe_minutes=60):
    total_minutes = beijing_dt.hour * 60 + beijing_dt.minute
    period_minutes = total_minutes // timeframe_minutes * timeframe_minutes
    start_hour = period_minutes // 60
    start_minute = period_minutes % 60
    period_start = beijing_dt.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    period_start += timedelta(minutes=offset_periods * timeframe_minutes)
    utc_start = period_start - timedelta(hours=8)
    return int(utc_start.timestamp() * 1000)

def find_kline_by_timestamp(ohlcv, target_ts):
    for k in ohlcv:
        if k[0] == target_ts:
            return k
    return None

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

def is_kdj_bullish(k, d, j):
    """判断KDJ是否多头排列：J > K > D"""
    return j > k > d

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第81个工作流扫描（4小时震荡 + 1小时KDJ多头 + 1小时突破 + 按1小时涨幅×杠杆/100排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 4小时级别：上根收盘 ∈ [上上根区间]（震荡）✅")
    print(f"   • 1小时级别：上根KDJ多头（J > K > D）✅")
    print(f"   • 1小时级别：上上根KDJ非多头（不满足J > K > D）✅")
    print(f"   • 1小时级别：上根收盘 > 上上根最高价（突破）✅")
    print(f"   • 排序 = 上根1小时涨幅 × (杠杆/100)（从高到低）")
    print(f"📊 推送：前十名（微信推送）")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")

    # 筛选 USDT 本位永续合约，并提取杠杆信息
    swap_symbols = []
    leverage_info = {}
    for symbol, market in markets.items():
        if market.get('type') == 'swap' and symbol.endswith('/USDT:USDT'):
            max_leverage = 0
            if 'limits' in market and 'leverage' in market['limits'] and 'max' in market['limits']['leverage']:
                max_leverage = float(market['limits']['leverage']['max'])
            elif 'info' in market and 'maxLeverage' in market['info']:
                max_leverage = float(market['info']['maxLeverage'])
            elif 'leverage' in market:
                max_leverage = float(market['leverage']) if isinstance(market['leverage'], (int, float)) else 0
            if max_leverage > 0:
                swap_symbols.append(symbol)
                leverage_info[symbol] = max_leverage
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位永续合约（且有有效杠杆信息）")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    # 目标K线时间戳
    # 1小时级别
    prev1_1h = get_period_start_timestamp(beijing_now, -1, 60)   # 上根1小时
    prev2_1h = get_period_start_timestamp(beijing_now, -2, 60)   # 上上根1小时

    # 4小时级别
    prev1_4h = get_period_start_timestamp(beijing_now, -1, 240)  # 上根4小时
    prev2_4h = get_period_start_timestamp(beijing_now, -2, 240)  # 上上根4小时

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根1小时: {ts_to_beijing(prev1_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上根1小时: {ts_to_beijing(prev2_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上根4小时: {ts_to_beijing(prev1_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根4小时: {ts_to_beijing(prev2_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_4h)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取1小时K线
            ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=50)
            if len(ohlcv_1h) < 30:
                continue

            # 获取4小时K线
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=15)
            if len(ohlcv_4h) < 4:
                continue

            # 1小时K线查找
            k1_1h = find_kline_by_timestamp(ohlcv_1h, prev1_1h)
            k2_1h = find_kline_by_timestamp(ohlcv_1h, prev2_1h)
            if None in (k1_1h, k2_1h):
                continue

            # 4小时K线查找
            k1_4h = find_kline_by_timestamp(ohlcv_4h, prev1_4h)
            k2_4h = find_kline_by_timestamp(ohlcv_4h, prev2_4h)
            if None in (k1_4h, k2_4h):
                continue

            # 提取1小时数据
            close1_1h = k1_1h[4]
            open1_1h = k1_1h[1]
            high1_1h = k1_1h[2]
            low1_1h = k1_1h[3]
            close2_1h = k2_1h[4]
            high2_1h = k2_1h[2]

            # 提取4小时数据
            close1_4h = k1_4h[4]
            high2_4h = k2_4h[2]
            low2_4h = k2_4h[3]

            if low2_4h == 0:
                continue
            if open1_1h == 0:
                continue

            # 条件1：4小时上根震荡（收盘在上上根区间内）
            if not (low2_4h < close1_4h < high2_4h):
                continue

            # 计算KDJ（1小时）
            closes = [k[4] for k in ohlcv_1h]
            highs = [k[2] for k in ohlcv_1h]
            lows = [k[3] for k in ohlcv_1h]
            k_vals, d_vals, j_vals = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev1_1h), None)
            idx2 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev2_1h), None)
            if None in (idx1, idx2):
                continue
            k1 = k_vals[idx1]
            d1 = d_vals[idx1]
            j1 = j_vals[idx1]
            k2 = k_vals[idx2]
            d2 = d_vals[idx2]
            j2 = j_vals[idx2]
            if None in (k1, d1, j1, k2, d2, j2):
                continue

            # 条件2：上根KDJ多头（J > K > D）
            if not is_kdj_bullish(k1, d1, j1):
                continue

            # 条件3：上上根KDJ非多头（不满足J > K > D）
            if is_kdj_bullish(k2, d2, j2):
                continue

            # 条件4：上根收盘 > 上上根最高价（突破）
            if close1_1h <= high2_1h:
                continue

            # 排序指标：上根1小时涨幅 × 杠杆/100
            gain = (close1_1h - open1_1h) / open1_1h * 100
            leverage = leverage_info[symbol]
            score = gain * (leverage / 100)

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain': round(gain, 2),
                'leverage': round(leverage),
                'score': round(score, 4),
                'close1_1h': round(close1_1h, 4),
                'open1_1h': round(open1_1h, 4),
                'high2_1h': round(high2_1h, 4),
                'k1': round(k1, 2),
                'd1': round(d1, 2),
                'j1': round(j1, 2),
                'k2': round(k2, 2),
                'd2': round(d2, 2),
                'j2': round(j2, 2),
                'close1_4h': round(close1_4h, 4),
                'high2_4h': round(high2_4h, 4),
                'low2_4h': round(low2_4h, 4),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按 score 从高到低排序
    result_list.sort(key=lambda x: x['score'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 双周期KDJ+形态扫描（第81个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 4小时上根震荡 ✅",
        f"   • 1小时上根KDJ多头（J>K>D）✅",
        f"   • 1小时上上根KDJ非多头 ✅",
        f"   • 1小时上根突破前高 ✅",
        f"   • 排序 = 上根1小时涨幅 × (杠杆/100)",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 筛选结果前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   上根1小时涨幅: +{item['gain']}%\n"
                f"   杠杆: {item['leverage']}x\n"
                f"   排序值: {item['score']}\n"
                f"   4小时震荡: {item['close1_4h']} ∈ [{item['low2_4h']}, {item['high2_4h']}] ✅\n"
                f"   上根KDJ: K={item['k1']}, D={item['d1']}, J={item['j1']} (J>K>D ✅)\n"
                f"   上上根KDJ: K={item['k2']}, D={item['d2']}, J={item['j2']} (非多头 ✅)\n"
                f"   突破: {item['close1_1h']} > {item['high2_1h']} ✅"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：4小时震荡+1小时KDJ多头+突破，按加权涨幅排序")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 未找到符合条件的币种")

    message = "\n".join(msg_lines)
    print("\n" + "="*50)
    print(message)
    print("="*50)
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
