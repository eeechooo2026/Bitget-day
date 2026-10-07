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
MA_SHORT = 5
MA_MID = 10
MA_LONG = 20
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
    """计算4小时K线起始时间戳（毫秒），offset_periods 以 4 小时为单位"""
    total_minutes = beijing_dt.hour * 60 + beijing_dt.minute
    period_minutes = total_minutes // 240 * 240   # 4小时 = 240分钟
    start_hour = period_minutes // 60
    start_minute = period_minutes % 60
    period_start = beijing_dt.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    period_start += timedelta(hours=offset_periods * 4)
    utc_start = period_start - timedelta(hours=8)
    return int(utc_start.timestamp() * 1000)

def find_kline_by_timestamp(ohlcv, target_ts):
    for k in ohlcv:
        if k[0] == target_ts:
            return k
    return None

def calculate_ma(closes, period):
    """计算简单移动平均线，返回与 closes 等长的列表，前面不足周期为 None"""
    n = len(closes)
    ma_values = [None] * n
    if n < period:
        return ma_values
    for i in range(period - 1, n):
        ma_values[i] = sum(closes[i - period + 1:i + 1]) / period
    return ma_values

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第108个工作流扫描（4小时级别 MA排列 扫描）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 策略逻辑：")
    print(f"   • 上根K棒 MA{MA_SHORT} > MA{MA_MID} > MA{MA_LONG}（多头排列）")
    print(f"     或 MA{MA_SHORT} < MA{MA_MID} < MA{MA_LONG}（空头排列）")
    print(f"   • 排序 = 上根K棒振幅（从高到低）")
    print(f"📊 推送：前十名（微信推送）")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")

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
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位永续合约")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    prev1_ts = get_4h_period_start_timestamp(beijing_now, -1)   # 上根（4小时）

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=50)
            if len(ohlcv) < MA_LONG + 5:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)   # 上根
            if k1 is None:
                continue

            high1 = k1[2]
            low1 = k1[3]
            if low1 == 0:
                continue

            # 计算MA
            closes = [k[4] for k in ohlcv]
            ma5_list = calculate_ma(closes, MA_SHORT)
            ma10_list = calculate_ma(closes, MA_MID)
            ma20_list = calculate_ma(closes, MA_LONG)

            idx1 = next((i for i, k in enumerate(ohlcv) if k[0] == prev1_ts), None)
            if idx1 is None:
                continue

            ma5 = ma5_list[idx1]
            ma10 = ma10_list[idx1]
            ma20 = ma20_list[idx1]
            if None in (ma5, ma10, ma20):
                continue

            # 条件：多头排列 或 空头排列
            bullish = ma5 > ma10 > ma20
            bearish = ma5 < ma10 < ma20
            if not (bullish or bearish):
                continue

            arrange_type = "多头排列" if bullish else "空头排列"

            # 计算振幅
            amplitude = (high1 - low1) / low1 * 100
            leverage = leverage_info[symbol]

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'amplitude': round(amplitude, 2),
                'leverage': round(leverage),
                'high1': round(high1, 4),
                'low1': round(low1, 4),
                'ma5': round(ma5, 4),
                'ma10': round(ma10, 4),
                'ma20': round(ma20, 4),
                'arrange_type': arrange_type,
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
        f"📊 Bitget 4小时级别 MA排列 扫描（第108个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📊 策略逻辑：",
        f"   • 上根K棒 MA{MA_SHORT} > MA{MA_MID} > MA{MA_LONG}（多头排列）",
        f"     或 MA{MA_SHORT} < MA{MA_MID} < MA{MA_LONG}（空头排列）",
        f"   • 排序 = 上根K棒振幅（从高到低）",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 筛选结果前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}  [{item['arrange_type']}]\n"
                f"   上根振幅: {item['amplitude']}%\n"
                f"   杠杆: {item['leverage']}x\n"
                f"   价格区间: {item['low1']} ~ {item['high1']}\n"
                f"   MA: MA5={item['ma5']} / MA10={item['ma10']} / MA20={item['ma20']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的合约")
        msg_lines.append("💡 解读：4小时级别 MA多头排列代表中期强势趋势，MA空头排列代表中期弱势趋势；振幅越大代表波动越剧烈")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 未找到符合条件的合约")

    message = "\n".join(msg_lines)
    print("\n" + "="*50)
    print(message)
    print("="*50)
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
