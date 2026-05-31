import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10
TIMEFRAME_15M = '15m'
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

def get_15m_period_start_timestamp(beijing_dt, offset_periods=0):
    total_minutes = beijing_dt.hour * 60 + beijing_dt.minute
    period_minutes = total_minutes // 15 * 15
    start_hour = period_minutes // 60
    start_minute = period_minutes % 60
    period_start = beijing_dt.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    period_start += timedelta(minutes=offset_periods * 15)
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

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第57个工作流扫描（15分钟：均线多头 + 收阴 + 按24h涨幅×杠杆/100排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根15分钟K棒均线多头排列（MA5 > MA10 > MA20）")
    print(f"   • 上根15分钟K棒收阴（收盘价 < 开盘价）")
    print(f"   • 排序 = 24小时涨幅 × (最高杠杆倍数 / 100)")
    print(f"📊 推送：前十名（微信推送）")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")

    # 筛选 USDT 本位永续合约，并提取杠杆信息和24h涨幅
    swap_symbols = []
    leverage_info = {}
    daily_gain_info = {}
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

    # 获取24h涨幅数据
    print("📡 正在获取24h涨幅数据...")
    tickers = exchange.fetch_tickers()
    for symbol, ticker in tickers.items():
        if symbol in leverage_info and ticker.get('percentage') is not None:
            daily_gain_info[symbol] = ticker['percentage']

    # 目标K线时间戳（上根15分钟）
    prev1_ts = get_15m_period_start_timestamp(beijing_now, -1)
    target_start = ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')
    target_end = (ts_to_beijing(prev1_ts) + timedelta(minutes=15)).strftime('%H:%M')
    print(f"📅 目标K线时间段（北京时间）: {target_start} - {target_end}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_15M, limit=50)
            if len(ohlcv) < 25:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)
            if k1 is None:
                continue

            close1 = k1[4]
            open1 = k1[1]

            if open1 == 0:
                continue

            # 条件1：均线多头排列
            ma5 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 5)
            ma10 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 10)
            ma20 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 20)
            if not is_bullish_arrangement(ma5, ma10, ma20):
                continue

            # 条件2：上根收阴
            if close1 >= open1:
                continue

            # 排序指标：24h涨幅 × 杠杆/100
            daily_gain = daily_gain_info.get(symbol, 0)
            leverage = leverage_info[symbol]
            score = daily_gain * (leverage / 100)

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'daily_gain': round(daily_gain, 2),
                'leverage': round(leverage),
                'score': round(score, 4),
                'close1': round(close1, 4),
                'open1': round(open1, 4),
                'ma5': round(ma5, 4),
                'ma10': round(ma10, 4),
                'ma20': round(ma20, 4),
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
        f"📊 Bitget 15分钟级别均线多头+收阴扫描（第57个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根15分钟K棒均线多头排列（MA5 > MA10 > MA20）",
        f"   • 上根15分钟K棒收阴",
        f"   • 排序 = 24小时涨幅 × (杠杆/100)",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 筛选结果前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   24h涨幅: +{item['daily_gain']}%\n"
                f"   杠杆: {item['leverage']}x\n"
                f"   排序值: {item['score']}\n"
                f"   均线: {item['ma5']} > {item['ma10']} > {item['ma20']} ✅\n"
                f"   上根: {item['open1']} → {item['close1']} (收阴 ✅)"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：15分钟均线多头但收阴，按24h加权涨幅排序")
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
