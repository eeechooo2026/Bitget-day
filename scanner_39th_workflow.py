import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10
TIMEFRAME_1D = '1d'
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

def get_daily_period_start_timestamp(beijing_dt, offset_days=0):
    utc_date = (beijing_dt + timedelta(days=offset_days) - timedelta(hours=8)).date()
    dt_start = datetime(utc_date.year, utc_date.month, utc_date.day, tzinfo=timezone.utc)
    return int(dt_start.timestamp() * 1000)

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

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第39个工作流扫描（日线级别KDJ金叉 + J值前低 + 按上根振幅排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 日线级别：上根J值 > 上上根J值（金叉）")
    print(f"   • 日线级别：上上根J值 < 上上上根J值（前低）")
    print(f"   • 排序指标 = 上根日线K棒振幅")
    print(f"   • 振幅 = (最高价 - 最低价) / 最低价 × 100%")
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

    # 目标K线时间戳（日线）
    prev1_ts = get_daily_period_start_timestamp(beijing_now, -1)   # 上根（昨天）
    prev2_ts = get_daily_period_start_timestamp(beijing_now, -2)   # 上上根（前天）
    prev3_ts = get_daily_period_start_timestamp(beijing_now, -3)   # 上上上根（大前天）

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根（昨天）: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d')}")
    print(f"   上上根（前天）: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d')}")
    print(f"   上上上根（大前天）: {ts_to_beijing(prev3_ts).strftime('%Y-%m-%d')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1D, limit=50)
            if len(ohlcv) < 30:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)   # 上根
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)   # 上上根
            k3 = find_kline_by_timestamp(ohlcv, prev3_ts)   # 上上上根
            if not (k1 and k2 and k3):
                continue

            high1 = k1[2]
            low1 = k1[3]
            if low1 == 0:
                continue

            # 计算KDJ的J值
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

            # 条件1：上根J值 > 上上根J值（金叉）
            if j1 <= j2:
                continue
            # 条件2：上上根J值 < 上上上根J值（前低）
            if j2 >= j3:
                continue

            # 排序指标：上根振幅
            amplitude = (high1 - low1) / low1 * 100
            leverage = leverage_info[symbol]

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'j3': round(j3, 2),
                'j2': round(j2, 2),
                'j1': round(j1, 2),
                'amplitude': round(amplitude, 2),
                'leverage': round(leverage),
                'high1': round(high1, 4),
                'low1': round(low1, 4),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按振幅从高到低排序
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 日线级别KDJ金叉+前低扫描（第39个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 日线级别：上根J值 > 上上根J值（金叉）",
        f"   • 日线级别：上上根J值 < 上上上根J值（前低）",
        f"   • 排序 = 上根日线K棒振幅",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 金叉+前低 | 上根振幅 前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   J值: {item['j3']} → {item['j2']} → {item['j1']}\n"
                f"   J2<J3 ✅, J1>J2 ✅\n"
                f"   上根振幅: {item['amplitude']}%, 杠杆: {item['leverage']}x\n"
                f"   上根高低: [{item['low1']}, {item['high1']}]"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：日线KDJ金叉确认，J值处于前低位置，按上根波动强度排序（看涨信号）")
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
