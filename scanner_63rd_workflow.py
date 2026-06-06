import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10
TIMEFRAME_1M = '1M'  # 月线
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

def get_monthly_period_start_timestamp(beijing_dt, offset_months=0):
    """获取指定偏移量的月线K线的开始时间戳（毫秒，UTC）"""
    year = beijing_dt.year
    month = beijing_dt.month
    # 计算目标月份
    target_year = year
    target_month = month + offset_months
    while target_month <= 0:
        target_month += 12
        target_year -= 1
    while target_month > 12:
        target_month -= 12
        target_year += 1
    # 月线开始时间为该月1日 00:00:00 UTC
    dt_start = datetime(target_year, target_month, 1, tzinfo=timezone.utc)
    return int(dt_start.timestamp() * 1000)

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
    print(f"🚀 开始第63个工作流扫描（月线级别：上根收阳 + 按涨幅排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 扫描所有USDT本位永续合约")
    print(f"   • 上根月线K棒收阳（收盘价 > 开盘价）")
    print(f"   • 排序 = 上根月线K棒涨幅（从高到低）")
    print(f"📊 推送：前十名（微信推送）")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")

    # 筛选 USDT 本位永续合约，并提取杠杆信息（用于显示）
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

    # 目标K线时间戳（上根月线 = 上个月）
    prev1_ts = get_monthly_period_start_timestamp(beijing_now, -1)
    target_month = ts_to_beijing(prev1_ts).strftime('%Y-%m')
    print(f"📅 目标K线时间段: {target_month}")

    print("⏳ 正在获取月线K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1M, limit=5)
            if len(ohlcv) < 2:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)
            if k1 is None:
                continue

            open1 = k1[1]
            close1 = k1[4]
            if open1 == 0:
                continue

            # 条件：上根收阳
            if close1 <= open1:
                continue

            # 计算涨幅
            gain = (close1 - open1) / open1 * 100
            leverage = leverage_info[symbol]

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain': round(gain, 2),
                'leverage': round(leverage),
                'open1': round(open1, 4),
                'close1': round(close1, 4),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按涨幅从高到低排序
    result_list.sort(key=lambda x: x['gain'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 月线级别涨幅榜（第63个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 扫描所有USDT本位永续合约",
        f"   • 上根月线收阳",
        f"   • 排序 = 上根月线涨幅",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 涨幅榜前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   月线涨幅: +{item['gain']}%\n"
                f"   开盘: {item['open1']} → 收盘: {item['close1']} (收阳 ✅)\n"
                f"   杠杆: {item['leverage']}x"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个合约")
        msg_lines.append("💡 解读：上根月线收阳，按涨幅排序")
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
