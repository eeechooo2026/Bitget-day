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
    """
    根据北京时间，获取指定偏移量的日线K线的开始时间戳（毫秒，UTC）
    offset_days: -1 表示昨天，-2 表示前天
    """
    utc_date = (beijing_dt + timedelta(days=offset_days) - timedelta(hours=8)).date()
    dt_start = datetime(utc_date.year, utc_date.month, utc_date.day, tzinfo=timezone.utc)
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
    print(f"🚀 开始第15个工作流扫描（日线涨幅榜） - 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 扫描所有USDT本位永续合约")
    print(f"   • 按上根日线K棒涨幅从高到低排序")
    print(f"📊 推送：前十名")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")
    swap_symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    # 目标K线时间戳（上根日线 = 昨天）
    prev1_ts = get_daily_period_start_timestamp(beijing_now, -1)

    print(f"📅 目标K线时间段（北京时间）:")
    target_date = ts_to_beijing(prev1_ts).strftime('%Y-%m-%d')
    print(f"   上根日线: {target_date}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1D, limit=5)
            if len(ohlcv) < 2:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)
            if k1 is None:
                continue

            open1 = k1[1]
            close1 = k1[4]
            if open1 == 0:
                continue

            # 计算涨幅
            gain = (close1 - open1) / open1 * 100

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain': round(gain, 2),
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
        f"📊 Bitget 日线级别涨幅榜（第15个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 扫描所有USDT本位永续合约",
        f"   • 按上根日线K棒涨幅从高到低排序",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 涨幅榜前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   涨幅: +{item['gain']}%\n"
                f"   开盘: {item['open1']} → 收盘: {item['close1']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append("💡 解读：上根日线K棒涨幅排名")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 未找到K线数据")

    message = "\n".join(msg_lines)
    print("\n" + "="*50)
    print(message)
    print("="*50)
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
