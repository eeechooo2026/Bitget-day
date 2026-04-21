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

def is_consolidation_kline(current_close, prev_high, prev_low):
    return current_close < prev_high and current_close > prev_low

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
    print(f"🚀 开始第五个工作流扫描 - 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根4小时K棒收盘价 > MA5，且 MA5 > MA10 ≥ MA20")
    print(f"   • 上根和上上根4小时K棒均处于震荡（收盘价落于前一根区间内）")
    print(f"   • 上根KDJ满足 J > K > D")
    print(f"📊 排序：按上上上根和上上上上根4小时K棒的收盘价累计涨幅从高到低")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")
    swap_symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    # 计算目标K线时间戳
    # 上根: offset=-1, 上上根: offset=-2, 上上上根: offset=-3, 上上上上根: offset=-4
    prev1_ts = get_4h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts = get_4h_period_start_timestamp(beijing_now, -2)   # 上上根
    prev3_ts = get_4h_period_start_timestamp(beijing_now, -3)   # 上上上根
    prev4_ts = get_4h_period_start_timestamp(beijing_now, -4)   # 上上上上根

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上上根: {ts_to_beijing(prev3_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上上上根: {ts_to_beijing(prev4_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev4_ts)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=100)
            if len(ohlcv) < 30:
                continue

            # 查找目标K线
            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)  # 上根
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)  # 上上根
            k3 = find_kline_by_timestamp(ohlcv, prev3_ts)  # 上上上根
            k4 = find_kline_by_timestamp(ohlcv, prev4_ts)  # 上上上上根
            if not (k1 and k2 and k3 and k4):
                continue

            close1 = k1[4]
            close2, high2, low2 = k2[4], k2[2], k2[3]
            high3, low3 = k3[2], k3[3]
            close3 = k3[4]
            close4 = k4[4]

            # 条件1：均线条件（基于上根）
            ma5 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 5)
            ma10 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 10)
            ma20 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 20)
            if ma5 is None or ma10 is None or ma20 is None:
                continue
            # MA5 > MA10 >= MA20
            if not (close1 > ma5 and ma5 > ma10 and ma10 >= ma20):
                continue

            # 条件2：上上根震荡（相对于上上上根）
            if not is_consolidation_kline(close2, high3, low3):
                continue

            # 条件3：上根震荡（相对于上上根）
            if not is_consolidation_kline(close1, high2, low2):
                continue

            # 条件4：KDJ J > K > D（上根）
            closes = [k[4] for k in ohlcv]
            highs = [k[2] for k in ohlcv]
            lows = [k[3] for k in ohlcv]
            k_vals, d_vals, j_vals = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv) if k[0] == prev1_ts), None)
            if idx1 is None or k_vals[idx1] is None or d_vals[idx1] is None or j_vals[idx1] is None:
                continue
            k_val = k_vals[idx1]
            d_val = d_vals[idx1]
            j_val = j_vals[idx1]
            if not (j_val > k_val > d_val):
                continue

            # 排序指标：上上上根和上上上上根的收盘价累计涨幅
            if close4 == 0:
                continue
            gain_sort = (close3 - close4) / close4 * 100

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain_sort': round(gain_sort, 2),
                'ma5': round(ma5, 4),
                'ma10': round(ma10, 4),
                'ma20': round(ma20, 4),
                'close1': round(close1, 4),
                'close2': round(close2, 4),
                'k_val': round(k_val, 2),
                'd_val': round(d_val, 2),
                'j_val': round(j_val, 2),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按涨幅从高到低排序
    result_list.sort(key=lambda x: x['gain_sort'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 4小时级别扫描（第五个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根收盘价 > MA5，且 MA5 > MA10 ≥ MA20",
        f"   • 上根和上上根均处于震荡",
        f"   • 上根KDJ: J > K > D",
        f"📊 排序：按上上上根和上上上上根4小时K棒累计涨幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   排序涨幅: +{item['gain_sort']}%\n"
                f"   均线: MA5={item['ma5']}, MA10={item['ma10']}, MA20={item['ma20']}\n"
                f"   上根收盘: {item['close1']} > MA5 ✅, MA5>MA10 ✅, MA10≥MA20 ✅\n"
                f"   上上根震荡: {item['close2']} ∈ 前根区间\n"
                f"   KDJ: K={item['k_val']}, D={item['d_val']}, J={item['j_val']} (J>K>D ✅)"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：短期均线强势（MA5>MA10≥MA20）+ 双K线震荡 + KDJ金叉，且前两周期涨幅领先")
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
