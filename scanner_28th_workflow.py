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
    print(f"🚀 开始第28个工作流扫描（1小时KDJ死叉 + J值前高 + 收盘<MA20，按4小时跌幅×杠杆/100排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 1小时级别：上根J值 < 上上根J值（死叉）")
    print(f"   • 1小时级别：上上根J值 > 上上上根J值（前高）")
    print(f"   • 1小时级别：上根收盘价 < MA20")
    print(f"   • 排序指标 = |上根4小时跌幅 + 上上根4小时跌幅| × (最高杠杆倍数 / 100)")
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

    # 1小时级别目标K线时间戳
    prev1_ts_1h = get_period_start_timestamp(beijing_now, -1, 60)   # 上根
    prev2_ts_1h = get_period_start_timestamp(beijing_now, -2, 60)   # 上上根
    prev3_ts_1h = get_period_start_timestamp(beijing_now, -3, 60)   # 上上上根

    # 4小时级别目标K线时间戳（用于排序）
    prev1_ts_4h = get_period_start_timestamp(beijing_now, -1, 240)   # 上根4小时
    prev2_ts_4h = get_period_start_timestamp(beijing_now, -2, 240)   # 上上根4小时

    print("📅 目标K线时间段（北京时间）:")
    print(f"   1小时上根: {ts_to_beijing(prev1_ts_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   1小时上上根: {ts_to_beijing(prev2_ts_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   1小时上上上根: {ts_to_beijing(prev3_ts_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   4小时上根: {ts_to_beijing(prev1_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   4小时上上根: {ts_to_beijing(prev2_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取1小时K线（至少需要35根计算MA20和KDJ）
            ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=50)
            if len(ohlcv_1h) < 35:
                continue

            # 获取4小时K线
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=10)
            if len(ohlcv_4h) < 5:
                continue

            # ========== 1小时级别条件判断 ==========
            # 查找K线
            k1 = find_kline_by_timestamp(ohlcv_1h, prev1_ts_1h)   # 上根
            k2 = find_kline_by_timestamp(ohlcv_1h, prev2_ts_1h)   # 上上根
            k3 = find_kline_by_timestamp(ohlcv_1h, prev3_ts_1h)   # 上上上根
            if not (k1 and k2 and k3):
                continue

            close1 = k1[4]   # 上根收盘价

            # 计算KDJ
            closes_1h = [k[4] for k in ohlcv_1h]
            highs_1h = [k[2] for k in ohlcv_1h]
            lows_1h = [k[3] for k in ohlcv_1h]
            k_vals, d_vals, j_vals = calculate_kdj(highs_1h, lows_1h, closes_1h, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev1_ts_1h), None)
            idx2 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev2_ts_1h), None)
            idx3 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev3_ts_1h), None)
            if None in (idx1, idx2, idx3):
                continue
            j1 = j_vals[idx1]
            j2 = j_vals[idx2]
            j3 = j_vals[idx3]
            if None in (j1, j2, j3):
                continue

            # 条件1：上根J值 < 上上根J值（死叉）
            if j1 >= j2:
                continue
            # 条件2：上上根J值 > 上上上根J值（前高）
            if j2 <= j3:
                continue

            # 条件3：上根收盘价 < MA20
            ma20 = calculate_ma_for_target_kline(ohlcv_1h, prev1_ts_1h, MA20_PERIOD)
            if ma20 is None or close1 >= ma20:
                continue

            # ========== 4小时级别跌幅计算 ==========
            k1_4h = find_kline_by_timestamp(ohlcv_4h, prev1_ts_4h)
            k2_4h = find_kline_by_timestamp(ohlcv_4h, prev2_ts_4h)
            if not (k1_4h and k2_4h):
                continue

            open4h1 = k1_4h[1]
            close4h1 = k1_4h[4]
            open4h2 = k2_4h[1]
            close4h2 = k2_4h[4]
            if open4h1 == 0 or open4h2 == 0:
                continue

            gain1 = (close4h1 - open4h1) / open4h1 * 100   # 上根4小时涨幅
            gain2 = (close4h2 - open4h2) / open4h2 * 100   # 上上根4小时涨幅

            # 只取下跌部分（负值），计算总跌幅
            if gain1 >= 0:
                gain1 = 0
            if gain2 >= 0:
                gain2 = 0
            total_decline = abs(gain1 + gain2)   # 跌幅总和绝对值

            # 排序指标 = 跌幅总和 × (杠杆 / 100)
            leverage = leverage_info[symbol]
            score = total_decline * (leverage / 100)

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'j3': round(j3, 2),
                'j2': round(j2, 2),
                'j1': round(j1, 2),
                'close1': round(close1, 4),
                'ma20': round(ma20, 4),
                'gain1': round(gain1, 2),
                'gain2': round(gain2, 2),
                'total_decline': round(total_decline, 2),
                'leverage': round(leverage),
                'score': round(score, 4),
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
        f"📊 Bitget 1小时级别KDJ死叉+前高+收盘<MA20扫描（第28个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 1小时KDJ死叉：上根J值 < 上上根J值",
        f"   • 1小时J值前高：上上根J值 > 上上上根J值",
        f"   • 收盘价 < MA20",
        f"   • 排序 = |上根4小时跌幅 + 上上根4小时跌幅| × (杠杆/100)",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 死叉+前高 | 4小时跌幅×杠杆 前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   J值: {item['j3']} → {item['j2']} → {item['j1']}\n"
                f"   J2>J3 ✅, J1<J2 ✅\n"
                f"   收盘 {item['close1']} < MA20({item['ma20']})\n"
                f"   4小时跌幅: 上上根 {item['gain2']}%, 上根 {item['gain1']}%\n"
                f"   总跌幅: {item['total_decline']}%, 杠杆: {item['leverage']}x\n"
                f"   排序值: {item['score']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：1小时KDJ死叉确认 + MA20下方 + 4小时级别下跌能量排序")
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
