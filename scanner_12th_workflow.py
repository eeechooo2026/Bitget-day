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
    period_start += timedelta(hours=offset_periods * (timeframe_minutes / 60))
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

def is_bullish_arrangement(ma5, ma10, ma20):
    if ma5 is None or ma10 is None or ma20 is None:
        return False
    return ma5 > ma10 > ma20

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

def calculate_4h_gain(ohlcv_4h, target_ts, prev_ts):
    k_target = find_kline_by_timestamp(ohlcv_4h, target_ts)
    k_prev = find_kline_by_timestamp(ohlcv_4h, prev_ts)
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
    print(f"🚀 开始第12个工作流扫描（1小时级别） - 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根1小时K棒均线多头排列（MA5>MA10>MA20，且收盘价>MA5）")
    print(f"   • 上根和上上根1小时K棒均处于震荡（收盘价落于前一根区间内）")
    print(f"   • 上根KDJ的J值 > 上上根KDJ的J值")
    print(f"📊 排序：按前两根4小时K棒涨幅从高到低")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")
    swap_symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    # 1小时级别目标K线时间戳
    prev1_ts_1h = get_period_start_timestamp(beijing_now, -1, 60)   # 上根
    prev2_ts_1h = get_period_start_timestamp(beijing_now, -2, 60)   # 上上根
    prev3_ts_1h = get_period_start_timestamp(beijing_now, -3, 60)   # 上上上根

    # 4小时级别目标K线时间戳（用于排序：前两根4小时K棒）
    prev1_ts_4h = get_period_start_timestamp(beijing_now, -1, 240)   # 上一根4小时
    prev2_ts_4h = get_period_start_timestamp(beijing_now, -2, 240)   # 上上一根4小时

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根1小时: {ts_to_beijing(prev1_ts_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上根1小时: {ts_to_beijing(prev2_ts_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上上根1小时: {ts_to_beijing(prev3_ts_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   排序用4小时K线: {ts_to_beijing(prev2_ts_4h).strftime('%Y-%m-%d %H:%M')} 和 {ts_to_beijing(prev1_ts_4h).strftime('%Y-%m-%d %H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=100)
            if len(ohlcv_1h) < 30:
                continue

            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=20)
            if len(ohlcv_4h) < 5:
                continue

            # 查找1小时K线
            k1 = find_kline_by_timestamp(ohlcv_1h, prev1_ts_1h)
            k2 = find_kline_by_timestamp(ohlcv_1h, prev2_ts_1h)
            k3 = find_kline_by_timestamp(ohlcv_1h, prev3_ts_1h)
            if not (k1 and k2 and k3):
                continue

            close1, open1 = k1[4], k1[1]
            close2, high2, low2 = k2[4], k2[2], k2[3]
            high3, low3 = k3[2], k3[3]

            # 条件1：均线多头排列（基于上根计算MA5, MA10, MA20）
            ma5 = calculate_ma_for_target_kline(ohlcv_1h, prev1_ts_1h, 5)
            ma10 = calculate_ma_for_target_kline(ohlcv_1h, prev1_ts_1h, 10)
            ma20 = calculate_ma_for_target_kline(ohlcv_1h, prev1_ts_1h, 20)
            if not is_bullish_arrangement(ma5, ma10, ma20):
                continue
            if close1 <= ma5:
                continue

            # 条件2：上上根震荡（收盘价介于上上上根区间）
            if not is_consolidation_kline(close2, high3, low3):
                continue

            # 条件3：上根震荡（收盘价介于上上根区间）
            if not is_consolidation_kline(close1, high2, low2):
                continue

            # 条件4：KDJ J值上升
            closes_1h = [k[4] for k in ohlcv_1h]
            highs_1h = [k[2] for k in ohlcv_1h]
            lows_1h = [k[3] for k in ohlcv_1h]
            _, _, j_vals = calculate_kdj(highs_1h, lows_1h, closes_1h, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev1_ts_1h), None)
            idx2 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev2_ts_1h), None)
            if idx1 is None or idx2 is None or j_vals[idx1] is None or j_vals[idx2] is None:
                continue
            if j_vals[idx1] <= j_vals[idx2]:
                continue

            # 排序指标：前两根4小时K棒涨幅
            gain_4h = calculate_4h_gain(ohlcv_4h, prev1_ts_4h, prev2_ts_4h)
            if gain_4h is None:
                continue

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain_4h': round(gain_4h, 2),
                'ma5': round(ma5, 4),
                'ma10': round(ma10, 4),
                'ma20': round(ma20, 4),
                'close1': round(close1, 4),
                'close2': round(close2, 4),
                'j_prev2': round(j_vals[idx2], 2),
                'j_prev1': round(j_vals[idx1], 2),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按4小时涨幅从高到低排序
    result_list.sort(key=lambda x: x['gain_4h'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 1小时级别扫描（第12个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根均线多头排列（MA5>MA10>MA20，且收盘>MA5）",
        f"   • 上上根震荡（收盘介于上上上根区间）",
        f"   • 上根震荡（收盘介于上上根区间）",
        f"   • 上根J值 > 上上根J值",
        f"📊 排序：按前两根4小时K棒涨幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   4小时涨幅: +{item['gain_4h']}%\n"
                f"   均线: {item['ma5']} > {item['ma10']} > {item['ma20']}\n"
                f"   上根收盘: {item['close1']} > MA5 ✅\n"
                f"   上上根震荡: {item['close2']} ∈ 前根区间\n"
                f"   J值变化: {item['j_prev2']} → {item['j_prev1']} 📈"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：1小时级别均线多头+双K线区间震荡+J值上升，4小时级别上涨阶段")
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
