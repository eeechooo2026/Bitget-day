import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 13
TIMEFRAME_1H = '1h'
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

def get_1h_period_start_timestamp(beijing_dt, offset_periods=0):
    total_minutes = beijing_dt.hour * 60 + beijing_dt.minute
    period_minutes = total_minutes // 60 * 60
    start_hour = period_minutes // 60
    start_minute = period_minutes % 60
    period_start = beijing_dt.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    period_start += timedelta(hours=offset_periods * 1)
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

def is_kdj_golden_cross(k, d, j):
    """判断KDJ是否金叉：J > K 且 J > D"""
    return j > k and j > d

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第79个工作流扫描（1小时级别：收阳创新低 + J值金叉 + 上上根非金叉 + 按上上根振幅×杠杆/100排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根收阳 + 最低价 < 上上根最低价 ✅")
    print(f"   • 上根KDJ：J > K 且 J > D（金叉）✅")
    print(f"   • 上上根KDJ：J < K 或 J < D（非金叉）✅")
    print(f"   • 排序 = 上上根振幅 × (最高杠杆倍数 / 100)（从高到低）")
    print(f"   • 振幅 = (最高价 - 最低价) / 最低价 × 100%")
    print(f"📊 推送：前{PUSH_TOP_N}名（微信推送）")

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
    prev1_ts = get_1h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts = get_1h_period_start_timestamp(beijing_now, -2)   # 上上根

    target_time1 = ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')
    target_time2 = ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')
    print(f"📅 目标K线时间段（北京时间）:")
    print(f"   上根: {target_time1} - {(ts_to_beijing(prev1_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上根: {target_time2} - {(ts_to_beijing(prev2_ts)+timedelta(hours=1)).strftime('%H:%M')}")

    print("⏳ 正在获取1小时K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=50)
            if len(ohlcv) < 30:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)   # 上根
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)   # 上上根
            if k1 is None or k2 is None:
                continue

            # 上根数据
            close1 = k1[4]
            open1 = k1[1]
            low1 = k1[3]
            # 上上根数据
            low2 = k2[3]
            high2 = k2[2]
            low2_val = k2[3]

            if open1 == 0 or low2 == 0 or low2_val == 0:
                continue

            # 条件1：上根收阳 + 最低价 < 上上根最低价
            if close1 <= open1:
                continue
            if low1 >= low2:
                continue

            # 计算KDJ
            closes = [k[4] for k in ohlcv]
            highs = [k[2] for k in ohlcv]
            lows = [k[3] for k in ohlcv]
            k_vals, d_vals, j_vals = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv) if k[0] == prev1_ts), None)
            idx2 = next((i for i, k in enumerate(ohlcv) if k[0] == prev2_ts), None)
            if idx1 is None or idx2 is None:
                continue
            k1_val = k_vals[idx1]
            d1_val = d_vals[idx1]
            j1_val = j_vals[idx1]
            k2_val = k_vals[idx2]
            d2_val = d_vals[idx2]
            j2_val = j_vals[idx2]
            if None in (k1_val, d1_val, j1_val, k2_val, d2_val, j2_val):
                continue

            # 条件2：上根KDJ金叉（J > K 且 J > D）
            if not is_kdj_golden_cross(k1_val, d1_val, j1_val):
                continue

            # 条件3：上上根KDJ非金叉（J < K 或 J < D）
            if is_kdj_golden_cross(k2_val, d2_val, j2_val):
                continue

            # 排序指标：上上根振幅 × 杠杆/100
            amplitude = (high2 - low2_val) / low2_val * 100
            leverage = leverage_info[symbol]
            score = amplitude * (leverage / 100)

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'amplitude': round(amplitude, 2),
                'leverage': round(leverage),
                'score': round(score, 4),
                'close1': round(close1, 4),
                'open1': round(open1, 4),
                'low1': round(low1, 4),
                'low2': round(low2, 4),
                'high2': round(high2, 4),
                'k1': round(k1_val, 2),
                'd1': round(d1_val, 2),
                'j1': round(j1_val, 2),
                'k2': round(k2_val, 2),
                'd2': round(d2_val, 2),
                'j2': round(j2_val, 2),
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
        f"📊 Bitget 1小时级别KDJ金叉+形态扫描（第79个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根收阳 + 最低价 < 上上根最低价 ✅",
        f"   • 上根KDJ金叉（J>K且J>D）✅",
        f"   • 上上根KDJ非金叉 ✅",
        f"   • 排序 = 上上根振幅 × (杠杆/100)",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 筛选结果前{PUSH_TOP_N}名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   上根: {item['open1']} → {item['close1']} (收阳 ✅) 最低 {item['low1']} < {item['low2']}\n"
                f"   上根KDJ: K={item['k1']}, D={item['d1']}, J={item['j1']} (J>K且J>D ✅)\n"
                f"   上上根KDJ: K={item['k2']}, D={item['d2']}, J={item['j2']} (非金叉 ✅)\n"
                f"   上上根振幅: {item['amplitude']}%, 杠杆: {item['leverage']}x\n"
                f"   排序值: {item['score']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：上根收阳创新低+金叉，上上根非金叉，按上上根加权波动强度排序")
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
