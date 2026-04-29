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
TOP_VOLUME = 100            # 只分析成交量前100的现货交易对
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

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第19个工作流扫描（现货日线跌幅榜 - 优化版）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📉 策略逻辑：")
    print(f"   • 按24h成交量排序，取前{TOP_VOLUME}个USDT本位现货交易对")
    print(f"   • 按上根日线K棒跌幅从高到低排序")
    print(f"📊 推送：前十名")

    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

    print("📡 第一步：获取所有现货Ticker（用于成交量排序）...")
    tickers = exchange.fetch_tickers()
    print(f"📊 共获取 {len(tickers)} 个交易对")

    # 筛选 USDT 本位现货交易对，并提取成交量
    usdt_tickers = []
    for symbol, ticker in tickers.items():
        if symbol.endswith('/USDT') and ticker.get('quoteVolume') is not None:
            usdt_tickers.append({
                'symbol': symbol,
                'volume': ticker['quoteVolume']  # 24h成交额（USDT）
            })
    print(f"📊 共找到 {len(usdt_tickers)} 个 USDT 本位现货交易对")

    if len(usdt_tickers) == 0:
        print("❌ 未找到现货交易对")
        return

    # 按成交量降序排序，取前 TOP_VOLUME 个
    usdt_tickers.sort(key=lambda x: x['volume'], reverse=True)
    top_symbols = [item['symbol'] for item in usdt_tickers[:TOP_VOLUME]]
    print(f"✅ 按24h成交量排序，取前 {len(top_symbols)} 个交易对")

    # 目标K线时间戳（上根日线 = 昨天）
    prev1_ts = get_daily_period_start_timestamp(beijing_now, -1)
    target_date = ts_to_beijing(prev1_ts).strftime('%Y-%m-%d')
    print(f"📅 目标K线时间段（北京时间）: {target_date}")

    print("⏳ 第二步：获取这些交易对的日线K线数据...")
    result_list = []

    for idx, symbol in enumerate(top_symbols):
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

            change = (close1 - open1) / open1 * 100

            result_list.append({
                'symbol': symbol.replace('/USDT', ''),
                'change': round(change, 2),
                'open1': round(open1, 8),
                'close1': round(close1, 8),
            })

            if (idx+1) % 20 == 0:
                print(f"   进度: {idx+1}/{len(top_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按跌幅从高到低排序
    result_list.sort(key=lambda x: x['change'])
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📉 Bitget 现货日线跌幅榜（第19个工作流 - 优化版）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📉 策略逻辑：",
        f"   • 扫描成交量前{TOP_VOLUME}的USDT本位现货交易对",
        f"   • 按上根日线K棒跌幅从高到低排序",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 跌幅榜前十名（共{len(result_list)}个交易对）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   涨跌幅: {item['change']}%\n"
                f"   开盘: {item['open1']} → 收盘: {item['close1']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append("💡 解读：上根日线K棒跌幅排名")
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
