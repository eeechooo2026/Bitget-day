import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json
import random

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10
TIMEFRAME_4H = '4h'
KDJ_RSV_PERIOD = 9
KDJ_SMOOTH = 3
MA20_PERIOD = 20
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
    print(f"🚀 开始第十个工作流扫描（空头版 - 收盘价<MA20） - 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📉 策略逻辑（空头）：")
    print(f"   • 上根4小时K棒收盘价 < MA20")
    print(f"   • 上根4小时K棒收阴")
    print(f"   • 上根最高价 > 上上根最高价")
    print(f"   • 上根J值 < 上上根J值")
    print(f"📊 推送：随机排序前十名")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")
    swap_symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    prev1_ts_4h = get_4h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts_4h = get_4h_period_start_timestamp(beijing_now, -2)   # 上上根

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根4小时: {ts_to_beijing(prev1_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根4小时: {ts_to_beijing(prev2_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取4小时K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=100)
            if len(ohlcv_4h) < 30:
                continue

            k_prev1 = find_kline_by_timestamp(ohlcv_4h, prev1_ts_4h)
            k_prev2 = find_kline_by_timestamp(ohlcv_4h, prev2_ts_4h)
            if not (k_prev1 and k_prev2):
                continue

            close1, open1, high1 = k_prev1[4], k_prev1[1], k_prev1[2]
            high2 = k_prev2[2]

            # 条件1：收盘价 < MA20
            ma20 = calculate_ma_for_target_kline(ohlcv_4h, prev1_ts_4h, MA20_PERIOD)
            if ma20 is None or close1 >= ma20:
                continue

            # 条件2：收阴
            if close1 >= open1:
                continue

            # 条件3：最高价创新高（高于上上根最高价）
            if high1 <= high2:
                continue

            # 条件4：KDJ J值下降
            closes_4h = [k[4] for k in ohlcv_4h]
            highs_4h = [k[2] for k in ohlcv_4h]
            lows_4h = [k[3] for k in ohlcv_4h]
            _, _, j_vals = calculate_kdj(highs_4h, lows_4h, closes_4h, KDJ_RSV_PERIOD, KDJ_SMOOTH)

            idx1 = next((i for i, k in enumerate(ohlcv_4h) if k[0] == prev1_ts_4h), None)
            idx2 = next((i for i, k in enumerate(ohlcv_4h) if k[0] == prev2_ts_4h), None)
            if idx1 is None or idx2 is None or j_vals[idx1] is None or j_vals[idx2] is None:
                continue
            if j_vals[idx1] >= j_vals[idx2]:
                continue

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'close1': round(close1, 4),
                'ma20': round(ma20, 4),
                'high1': round(high1, 4),
                'high2': round(high2, 4),
                'j_prev2': round(j_vals[idx2], 2),
                'j_prev1': round(j_vals[idx1], 2),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    random.shuffle(result_list)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📉 Bitget 4小时级别空头扫描（收盘价<MA20版）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📉 策略逻辑（空头）：",
        f"   • 上根收盘价 < MA20",
        f"   • 上根收阴",
        f"   • 上根最高价 > 上上根最高价",
        f"   • 上根J值 < 上上根J值",
        f"📊 推送：随机排序前十名",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 随机排序前十名（共{len(result_list)}个符合条件的币种）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   上根收盘: {item['close1']} < MA20({item['ma20']}) ✅\n"
                f"   上根最高: {item['high1']} > 上上根最高 {item['high2']}\n"
                f"   J值变化: {item['j_prev2']} → {item['j_prev1']} 📉"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：价格跌破MA20且收阴+创新高+J值下降，中期趋势转弱")
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
