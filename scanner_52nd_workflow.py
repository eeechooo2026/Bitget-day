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

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第52个工作流扫描（1小时：空头版四重形态组合 + 按|4小时跌幅|×杠杆/100排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📉 策略逻辑（空头）：")
    print(f"   • 上根收阴 + 收盘 ∈ [上上根区间]（震荡）")
    print(f"   • 上上根收阳 + 收盘 ∈ [上上上根区间]（震荡）")
    print(f"   • 上上上根收阳 + 收盘 ∈ [上上上上根区间]（震荡）")
    print(f"   • 上上上上根收阴 + 收盘 < 上上上上上根最低价（跌破前低）")
    print(f"   • 排序 = |4小时上根跌幅| × (杠杆/100)（从高到低）")
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
    prev1_ts = get_period_start_timestamp(beijing_now, -1, 60)   # 上根
    prev2_ts = get_period_start_timestamp(beijing_now, -2, 60)   # 上上根
    prev3_ts = get_period_start_timestamp(beijing_now, -3, 60)   # 上上上根
    prev4_ts = get_period_start_timestamp(beijing_now, -4, 60)   # 上上上上根
    prev5_ts = get_period_start_timestamp(beijing_now, -5, 60)   # 上上上上上根

    # 4小时级别目标K线时间戳（用于排序）
    prev1_ts_4h = get_period_start_timestamp(beijing_now, -1, 240)   # 上根4小时

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根（1小时）: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上根（1小时）: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上上根（1小时）: {ts_to_beijing(prev3_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上上上根（1小时）: {ts_to_beijing(prev4_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev4_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上上上上根（1小时）: {ts_to_beijing(prev5_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev5_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   排序用4小时上根: {ts_to_beijing(prev1_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取1小时K线（需要至少50根）
            ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=60)
            if len(ohlcv_1h) < 50:
                continue

            # 获取4小时K线（用于排序）
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=10)
            if len(ohlcv_4h) < 5:
                continue

            # 查找1小时K线
            k1 = find_kline_by_timestamp(ohlcv_1h, prev1_ts)   # 上根
            k2 = find_kline_by_timestamp(ohlcv_1h, prev2_ts)   # 上上根
            k3 = find_kline_by_timestamp(ohlcv_1h, prev3_ts)   # 上上上根
            k4 = find_kline_by_timestamp(ohlcv_1h, prev4_ts)   # 上上上上根
            k5 = find_kline_by_timestamp(ohlcv_1h, prev5_ts)   # 上上上上上根
            if not (k1 and k2 and k3 and k4 and k5):
                continue

            # 上根数据
            close1 = k1[4]
            open1 = k1[1]
            # 上上根数据
            close2 = k2[4]
            open2 = k2[1]
            high2 = k2[2]
            low2 = k2[3]
            # 上上上根数据
            close3 = k3[4]
            open3 = k3[1]
            high3 = k3[2]
            low3 = k3[3]
            # 上上上上根数据
            close4 = k4[4]
            open4 = k4[1]
            high4 = k4[2]
            low4 = k4[3]
            # 上上上上上根数据
            low5 = k5[3]

            if open1 == 0 or open2 == 0 or open3 == 0 or open4 == 0:
                continue
            if low2 == 0 or low3 == 0 or low4 == 0:
                continue

            # 条件1（空头）：上根收阴 + 收盘在上上根区间内
            if close1 >= open1:
                continue
            if not (low2 < close1 < high2):
                continue

            # 条件2（空头）：上上根收阳 + 收盘在上上上根区间内
            if close2 <= open2:
                continue
            if not (low3 < close2 < high3):
                continue

            # 条件3（空头）：上上上根收阳 + 收盘在上上上上根区间内
            if close3 <= open3:
                continue
            if not (low4 < close3 < high4):
                continue

            # 条件4（空头）：上上上上根收阴 + 收盘 < 上上上上上根最低价
            if close4 >= open4:
                continue
            if close4 >= low5:
                continue

            # 排序指标：|4小时上根跌幅| × 杠杆/100
            k4h = find_kline_by_timestamp(ohlcv_4h, prev1_ts_4h)
            if k4h is None:
                continue
            open_4h = k4h[1]
            close_4h = k4h[4]
            if open_4h == 0:
                continue
            change_4h = (close_4h - open_4h) / open_4h * 100
            leverage = leverage_info[symbol]
            score = abs(change_4h) * (leverage / 100)

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'change_4h': round(change_4h, 2),
                'leverage': round(leverage),
                'score': round(score, 4),
                'close1': round(close1, 4),
                'open1': round(open1, 4),
                'close2': round(close2, 4),
                'open2': round(open2, 4),
                'high2': round(high2, 4),
                'low2': round(low2, 4),
                'close3': round(close3, 4),
                'open3': round(open3, 4),
                'high3': round(high3, 4),
                'low3': round(low3, 4),
                'close4': round(close4, 4),
                'open4': round(open4, 4),
                'high4': round(high4, 4),
                'low4': round(low4, 4),
                'low5': round(low5, 4),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按 score 从高到低排序（绝对值越大排越前）
    result_list.sort(key=lambda x: x['score'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📉 Bitget 1小时级别四重形态扫描（第52个工作流 - 空头版）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📉 策略逻辑（空头）：",
        f"   • 上根收阴 + 收盘 ∈ [上上根区间]",
        f"   • 上上根收阳 + 收盘 ∈ [上上上根区间]",
        f"   • 上上上根收阳 + 收盘 ∈ [上上上上根区间]",
        f"   • 上上上上根收阴 + 收盘 < 上上上上上根最低价",
        f"   • 排序 = |4小时上根跌幅| × (杠杆/100)",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 筛选结果前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   上上上上上根最低: {item['low5']}\n"
                f"   上上上上根: {item['open4']} → {item['close4']} (收阴 ✅) 跌破前低 ✅\n"
                f"   上上上根: {item['open3']} → {item['close3']} (收阳 ✅) 收盘 ∈ [{item['low4']}, {item['high4']}] ✅\n"
                f"   上上根: {item['open2']} → {item['close2']} (收阳 ✅) 收盘 ∈ [{item['low3']}, {item['high3']}] ✅\n"
                f"   上根: {item['open1']} → {item['close1']} (收阴 ✅) 收盘 ∈ [{item['low2']}, {item['high2']}] ✅\n"
                f"   4小时涨跌幅: {item['change_4h']}%, 杠杆: {item['leverage']}x\n"
                f"   排序值: {item['score']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：空头版四重形态组合（跌破前低+三重震荡），按4小时加权下跌幅度排序")
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
