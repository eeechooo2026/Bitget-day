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
    print(f"🚀 开始第30个工作流扫描（1小时顶背离 + 收盘<MA20 + 按上上根+上上上根跌幅×杠杆/100排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 1小时顶背离：上根最高价 > 上上根最高价（价格创新高）")
    print(f"   • 1小时顶背离：上根KDJ的J值 < 上上根J值（指标走低）")
    print(f"   • 上根收盘价 < MA20")
    print(f"   • 排序指标 = |上上根跌幅 + 上上上根跌幅| × (最高杠杆倍数 / 100)")
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
    prev1_ts = get_1h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts = get_1h_period_start_timestamp(beijing_now, -2)   # 上上根
    prev3_ts = get_1h_period_start_timestamp(beijing_now, -3)   # 上上上根

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上根: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上上根: {ts_to_beijing(prev3_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts)+timedelta(hours=1)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=50)
            if len(ohlcv) < 35:
                continue

            # ========== 顶背离判断 ==========
            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)   # 上根
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)   # 上上根
            if not (k1 and k2):
                continue

            high1 = k1[2]      # 上根最高价
            high2 = k2[2]      # 上上根最高价
            close1 = k1[4]     # 上根收盘价

            # 条件1：价格创新高
            if high1 <= high2:
                continue

            # 计算KDJ的J值
            closes = [k[4] for k in ohlcv]
            highs = [k[2] for k in ohlcv]
            lows = [k[3] for k in ohlcv]
            k_vals, d_vals, j_vals = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv) if k[0] == prev1_ts), None)
            idx2 = next((i for i, k in enumerate(ohlcv) if k[0] == prev2_ts), None)
            if idx1 is None or idx2 is None or j_vals[idx1] is None or j_vals[idx2] is None:
                continue

            j1 = j_vals[idx1]
            j2 = j_vals[idx2]

            # 条件2：J值走低（顶背离）
            if j1 >= j2:
                continue

            # 条件3：收盘价 < MA20
            ma20 = calculate_ma_for_target_kline(ohlcv, prev1_ts, MA20_PERIOD)
            if ma20 is None or close1 >= ma20:
                continue

            # ========== 上上根和上上上根跌幅计算 ==========
            k3 = find_kline_by_timestamp(ohlcv, prev3_ts)   # 上上上根
            if not k3:
                continue

            open2 = k2[1]
            close2 = k2[4]
            open3 = k3[1]
            close3 = k3[4]

            if open2 == 0 or open3 == 0:
                continue

            decline2 = (close2 - open2) / open2 * 100   # 上上根跌幅（负值）
            decline3 = (close3 - open3) / open3 * 100   # 上上上根跌幅（负值）
            total_decline = abs(decline2 + decline3)

            leverage = leverage_info[symbol]
            score = total_decline * (leverage / 100)

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'high1': round(high1, 4),
                'high2': round(high2, 4),
                'j1': round(j1, 2),
                'j2': round(j2, 2),
                'close1': round(close1, 4),
                'ma20': round(ma20, 4),
                'decline2': round(decline2, 2),
                'decline3': round(decline3, 2),
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
        f"📊 Bitget 1小时级别顶背离扫描（第30个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 顶背离：价格创新高（高点 {item['high2']}→{item['high1']}↑）+ J值走低（{j2}→{j1}↓）",
        f"   • 收盘价 < MA20",
        f"   • 排序 = |上上根跌幅 + 上上上根跌幅| × (杠杆/100)",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 顶背离 | 前两周期跌幅×杠杆 前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   顶背离: 高点 {item['high2']} → {item['high1']} (↑), J值 {item['j2']} → {item['j1']} (↓)\n"
                f"   收盘 {item['close1']} < MA20({item['ma20']})\n"
                f"   上上上根跌幅: {item['decline3']}%, 上上根跌幅: {item['decline2']}%\n"
                f"   总跌幅: {item['total_decline']}%, 杠杆: {item['leverage']}x\n"
                f"   排序值: {item['score']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：顶背离 + MA20下方 + 前两周期下跌能量排序")
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
