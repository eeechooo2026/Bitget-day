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
    utc_date = (beijing_dt + timedelta(days=offset_days) - timedelta(hours=8)).date()
    dt_start = datetime(utc_date.year, utc_date.month, utc_date.day, tzinfo=timezone.utc)
    return int(dt_start.timestamp() * 1000)

def find_kline_by_timestamp(ohlcv, target_ts):
    for k in ohlcv:
        if k[0] == target_ts:
            return k
    return None

def find_daily_kline_by_date(ohlcv_1d, target_utc_date):
    target_date_str = target_utc_date.strftime('%Y-%m-%d')
    for k in ohlcv_1d:
        k_date = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date()
        if k_date.strftime('%Y-%m-%d') == target_date_str:
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

def calculate_daily_gain(ohlcv_1d, target_ts, prev_ts):
    target_date = datetime.fromtimestamp(target_ts / 1000, tz=timezone.utc).date()
    prev_date = datetime.fromtimestamp(prev_ts / 1000, tz=timezone.utc).date()
    k_target = find_daily_kline_by_date(ohlcv_1d, target_date)
    k_prev = find_daily_kline_by_date(ohlcv_1d, prev_date)
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
    print(f"🚀 开始第五个工作流扫描（无J值条件版） - 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根4小时K棒均线多头排列（MA5 > MA10 > MA20，且收盘价 > MA5）")
    print(f"   • 上根和上上根4小时K棒均处于震荡（收盘价落于前一根区间内）")
    print(f"📊 排序：按前两根日线K棒涨幅从高到低")

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
    prev3_ts_4h = get_4h_period_start_timestamp(beijing_now, -3)   # 上上上根

    prev1_ts_1d = get_daily_period_start_timestamp(beijing_now, -1)   # 昨天
    prev2_ts_1d = get_daily_period_start_timestamp(beijing_now, -2)   # 前天

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根4小时: {ts_to_beijing(prev1_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根4小时: {ts_to_beijing(prev2_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上上根4小时: {ts_to_beijing(prev3_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   排序用日线: {ts_to_beijing(prev2_ts_1d).strftime('%Y-%m-%d')} 和 {ts_to_beijing(prev1_ts_1d).strftime('%Y-%m-%d')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=100)
            if len(ohlcv_4h) < 30:
                continue

            ohlcv_1d = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1D, limit=20)
            if len(ohlcv_1d) < 5:
                continue

            k1 = find_kline_by_timestamp(ohlcv_4h, prev1_ts_4h)
            k2 = find_kline_by_timestamp(ohlcv_4h, prev2_ts_4h)
            k3 = find_kline_by_timestamp(ohlcv_4h, prev3_ts_4h)
            if not (k1 and k2 and k3):
                continue

            close1, open1 = k1[4], k1[1]
            close2, high2, low2 = k2[4], k2[2], k2[3]
            high3, low3 = k3[2], k3[3]

            # 条件1：均线多头排列（基于上根计算MA5, MA10, MA20）
            ma5 = calculate_ma_for_target_kline(ohlcv_4h, prev1_ts_4h, 5)
            ma10 = calculate_ma_for_target_kline(ohlcv_4h, prev1_ts_4h, 10)
            ma20 = calculate_ma_for_target_kline(ohlcv_4h, prev1_ts_4h, 20)
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

            # 日线涨幅
            gain_1d = calculate_daily_gain(ohlcv_1d, prev1_ts_1d, prev2_ts_1d)
            if gain_1d is None:
                continue

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain_1d': round(gain_1d, 2),
                'ma5': round(ma5, 4),
                'ma10': round(ma10, 4),
                'ma20': round(ma20, 4),
                'close1': round(close1, 4),
                'close2': round(close2, 4),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    result_list.sort(key=lambda x: x['gain_1d'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 4小时级别扫描（第五个工作流 - 无J值条件版）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根均线多头排列（MA5>MA10>MA20，且收盘>MA5）",
        f"   • 上上根震荡（收盘介于上上上根区间）",
        f"   • 上根震荡（收盘介于上上根区间）",
        f"📊 排序：按前两根日线涨幅从高到低",
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
                f"   上上根震荡: {item['close2']} ∈ 前根区间"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：均线多头+双K线区间震荡，日线级别上涨确认")
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
