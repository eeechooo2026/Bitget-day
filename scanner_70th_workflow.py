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
MA5_PERIOD = 5
MA10_PERIOD = 10
MA20_PERIOD = 20
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

def find_kline_by_timestamp(ohlcv, target_ts):
    for k in ohlcv:
        if k[0] == target_ts:
            return k
    return None

def calculate_ma_for_target_kline(ohlcv, target_ts, period):
    target_idx = None
    for i, k in enumerate(ohlcv):
        if k[0] == target_ts:
            target_idx = i
            break
    if target_idx is None or target_idx < period - 1:
        return None
    closes = [ohlcv[j][4] for j in range(target_idx - period + 1, target_idx + 1)]
    return sum(closes) / period

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

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第70个工作流扫描（4小时：收阳+收盘>MA5/MA10/MA20 + J值金叉 + J值前低 + 按涨幅从高到低排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根收阳 + 收盘价 > MA5 且 > MA10 且 > MA20")
    print(f"   • 上根J值 > 上上根J值（J值上升/金叉）")
    print(f"   • 上上根J值 < 上上上根J值（J值前低）")
    print(f"   • 排序 = 上根涨幅（从高到低）")
    print(f"📊 推送：前十名（微信推送）")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")

    # 筛选 USDT 本位永续合约，并提取杠杆信息（用于显示）
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
    prev1_ts = get_4h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts = get_4h_period_start_timestamp(beijing_now, -2)   # 上上根
    prev3_ts = get_4h_period_start_timestamp(beijing_now, -3)   # 上上上根

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上上根: {ts_to_beijing(prev3_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=50)
            if len(ohlcv) < 30:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)   # 上根
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)   # 上上根
            k3 = find_kline_by_timestamp(ohlcv, prev3_ts)   # 上上上根
            if k1 is None or k2 is None or k3 is None:
                continue

            close1 = k1[4]
            open1 = k1[1]
            if open1 == 0:
                continue

            # 条件1：上根收阳
            if close1 <= open1:
                continue

            # 条件1续：上根收盘价 > MA5, > MA10, > MA20
            ma5 = calculate_ma_for_target_kline(ohlcv, prev1_ts, MA5_PERIOD)
            ma10 = calculate_ma_for_target_kline(ohlcv, prev1_ts, MA10_PERIOD)
            ma20 = calculate_ma_for_target_kline(ohlcv, prev1_ts, MA20_PERIOD)
            if None in (ma5, ma10, ma20):
                continue
            if not (close1 > ma5 and close1 > ma10 and close1 > ma20):
                continue

            # 计算KDJ
            closes = [k[4] for k in ohlcv]
            highs = [k[2] for k in ohlcv]
            lows = [k[3] for k in ohlcv]
            k_vals, d_vals, j_vals = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv) if k[0] == prev1_ts), None)
            idx2 = next((i for i, k in enumerate(ohlcv) if k[0] == prev2_ts), None)
            idx3 = next((i for i, k in enumerate(ohlcv) if k[0] == prev3_ts), None)
            if None in (idx1, idx2, idx3):
                continue
            j1 = j_vals[idx1]
            j2 = j_vals[idx2]
            j3 = j_vals[idx3]
            if None in (j1, j2, j3):
                continue

            # 条件2：上根J值 > 上上根J值（J值上升/金叉）
            if j1 <= j2:
                continue

            # 条件3：上上根J值 < 上上上根J值（J值前低）
            if j2 >= j3:
                continue

            # 计算上根涨幅
            gain = (close1 - open1) / open1 * 100
            leverage = leverage_info[symbol]

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain': round(gain, 2),
                'leverage': round(leverage),
                'close1': round(close1, 4),
                'open1': round(open1, 4),
                'ma5': round(ma5, 4),
                'ma10': round(ma10, 4),
                'ma20': round(ma20, 4),
                'j3': round(j3, 2),
                'j2': round(j2, 2),
                'j1': round(j1, 2),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按涨幅从高到低排序（涨幅最大的排最前）
    result_list.sort(key=lambda x: x['gain'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 4小时级别多条件扫描（第70个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根收阳 + 收盘价 > MA5/MA10/MA20 ✅",
        f"   • 上根J值 > 上上根J值（金叉）✅",
        f"   • 上上根J值 < 上上上根J值（前低）✅",
        f"   • 排序 = 上根涨幅（从高到低）",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 筛选结果前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   上根涨幅: +{item['gain']}%\n"
                f"   上根收盘 {item['close1']} > MA5({item['ma5']}) > MA10({item['ma10']}) > MA20({item['ma20']}) ✅\n"
                f"   J值变化: {item['j3']} → {item['j2']} → {item['j1']}\n"
                f"   (J2<J3 ✅, J1>J2 ✅)\n"
                f"   杠杆: {item['leverage']}x"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：收阳+站上三均线+J值金叉+前低，按涨幅从大到小排序")
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
