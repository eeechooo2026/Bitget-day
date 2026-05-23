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

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第37个工作流扫描（4小时级别：上根震荡 + 上上根收阴 + 按上上根振幅×杠杆/100排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根K棒收盘价在上上根K棒的最高价和最低价之间（震荡）")
    print(f"   • 上上根K棒收阴（收盘价 < 开盘价）")
    print(f"   • 排序指标 = 上上根振幅 × (最高杠杆倍数 / 100)")
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

    # 目标K线时间戳
    prev1_ts = get_4h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts = get_4h_period_start_timestamp(beijing_now, -2)   # 上上根

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=30)
            if len(ohlcv) < 10:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)
            if not (k1 and k2):
                continue

            # 上根数据
            close1 = k1[4]
            # 上上根数据
            open2 = k2[1]
            close2 = k2[4]
            high2 = k2[2]
            low2 = k2[3]

            if open2 == 0 or low2 == 0:
                continue

            # 条件1：上根收盘价在上上根的最高价和最低价之间
            if not (low2 < close1 < high2):
                continue

            # 条件2：上上根收阴（收盘价 < 开盘价）
            if close2 >= open2:
                continue

            # 计算上上根振幅
            amplitude = (high2 - low2) / low2 * 100
            leverage = leverage_info[symbol]
            score = amplitude * (leverage / 100)

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'close1': round(close1, 4),
                'high2': round(high2, 4),
                'low2': round(low2, 4),
                'open2': round(open2, 4),
                'close2': round(close2, 4),
                'amplitude': round(amplitude, 2),
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
        f"📊 Bitget 4小时级别震荡+收阴扫描（第37个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根收盘价 ∈ [上上根最低价, 上上根最高价]（震荡）",
        f"   • 上上根收阴（收盘 < 开盘）",
        f"   • 排序 = 上上根振幅 × (杠杆/100)",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 筛选结果前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   上上根区间: [{item['low2']}, {item['high2']}], 上根收盘: {item['close1']} ✅\n"
                f"   上上根: {item['open2']} → {item['close2']} (收阴 ✅)\n"
                f"   上上根振幅: {item['amplitude']}%, 杠杆: {item['leverage']}x\n"
                f"   排序值: {item['score']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：上根在上上根区间内震荡，上上根收阴，按上上根波动强度排序")
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
