import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10            # 推送前N名
TIMEFRAME_4H = '4h'
MIN_LEVERAGE_REQUIRED = 50  # 最小杠杆要求（50倍或以上）
# =============================================

def send_push_wxpusher(message):
    """使用 WxPusher 推送消息到微信"""
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
            print(f"❌ WxPusher 推送失败: {result}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")

def get_utc_now():
    """获取当前UTC时间的datetime对象（无时区信息）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_4h_period_start_timestamp(beijing_dt, offset_periods=0):
    """根据北京时间，获取指定偏移量的4小时K线周期的开始时间戳（毫秒，UTC）"""
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
    """在K线列表中查找指定开始时间戳的K线"""
    for k in ohlcv:
        if k[0] == target_ts:
            return k
    return None

def ts_to_beijing(ts):
    """UTC时间戳转北京时间"""
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第14个工作流扫描（杠杆筛选版） - 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 只扫描最大杠杆 ≥ {MIN_LEVERAGE_REQUIRED} 倍的USDT本位永续合约")
    print(f"   • 按上根4小时K棒涨幅从高到低排序")
    print(f"📊 推送：前十名（微信推送）")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据及杠杆信息...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")

    # 第一步：筛选出满足杠杆要求的合约
    qualified_symbols = []
    leverage_info = {}
    for symbol, market in markets.items():
        # 只筛选 USDT 本位永续合约
        if market['type'] == 'swap' and symbol.endswith('/USDT:USDT'):
            max_leverage = 0
            # 尝试从不同字段获取最大杠杆信息
            if 'limits' in market and 'leverage' in market['limits'] and 'max' in market['limits']['leverage']:
                max_leverage = float(market['limits']['leverage']['max'])
            elif 'info' in market and 'maxLeverage' in market['info']:
                max_leverage = float(market['info']['maxLeverage'])
            elif 'leverage' in market:
                max_leverage = float(market['leverage']) if isinstance(market['leverage'], (int, float)) else 0

            if max_leverage >= MIN_LEVERAGE_REQUIRED:
                qualified_symbols.append(symbol)
                leverage_info[symbol] = max_leverage

    print(f"✅ 杠杆筛选完成：共 {len(qualified_symbols)} 个合约满足杠杆 ≥ {MIN_LEVERAGE_REQUIRED}倍")
    if len(qualified_symbols) == 0:
        print("❌ 未找到符合条件的合约交易对")
        return

    # 第二步：计算这些合约的上根4小时K线涨幅
    prev1_ts = get_4h_period_start_timestamp(beijing_now, -1)   # 上根

    print(f"📅 目标K线时间段（北京时间）:")
    print(f"   上根4小时: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(qualified_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=10)
            if len(ohlcv) < 2:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)
            if k1 is None:
                continue

            open1 = k1[1]
            close1 = k1[4]
            if open1 == 0:
                continue
            gain = (close1 - open1) / open1 * 100

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain': round(gain, 2),
                'leverage': leverage_info[symbol],
                'open1': round(open1, 4),
                'close1': round(close1, 4),
            })

            if (idx+1) % 50 == 0:
                print(f"   进度: {idx+1}/{len(qualified_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 第三步：按涨幅排序，推送前十名
    result_list.sort(key=lambda x: x['gain'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 4小时级别涨幅榜（杠杆≥{MIN_LEVERAGE_REQUIRED}倍）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 扫描最大杠杆 ≥ {MIN_LEVERAGE_REQUIRED} 倍的USDT本位永续合约",
        f"   • 按上根4小时K棒涨幅从高到低排序",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 涨幅榜前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   涨幅: +{item['gain']}%\n"
                f"   杠杆: {item['leverage']:.0f}x\n"
                f"   开盘: {item['open1']} → 收盘: {item['close1']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的合约")
        msg_lines.append("💡 解读：上根4小时K棒涨幅排名")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 未找到符合条件的合约数据")

    message = "\n".join(msg_lines)
    print("\n" + "="*50)
    print(message)
    print("="*50)
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
