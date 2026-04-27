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
MA20_PERIOD = 20
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

def calculate_ma_for_target_kline(ohlcv, target_ts, period):
    """
    基于目标K线向前取 period 根K线（包含本身）计算移动平均
    返回 MA 值，如果数据不足则返回 None
    """
    target_idx = None
    for i, k in enumerate(ohlcv):
        if k[0] == target_ts:
            target_idx = i
            break
    if target_idx is None or target_idx < period - 1:
        return None
    closes = [ohlcv[j][4] for j in range(target_idx - period + 1, target_idx + 1)]
    return sum(closes) / period

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第17个工作流扫描（收盘突破前高但低于MA20） - 当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根4小时K棒收盘价 > 上上根最高价（突破前高）")
    print(f"   • 上根4小时K棒收盘价 < MA20")
    print(f"📊 排序：按上根4小时K棒涨幅从高到低")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")
    swap_symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    # 计算目标K线时间戳
    prev1_ts = get_4h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts = get_4h_period_start_timestamp(beijing_now, -2)   # 上上根

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=4)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取足够多的4小时K线（需要至少20根计算MA20）
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=50)
            if len(ohlcv) < 25:  # 至少需要20根K线，多取一些
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)
            if not (k1 and k2):
                continue

            close1 = k1[4]
            open1 = k1[1]
            high2 = k2[2]

            # 条件1：收盘价突破上上根最高价
            if close1 <= high2:
                continue

            # 条件2：收盘价 < MA20
            ma20 = calculate_ma_for_target_kline(ohlcv, prev1_ts, MA20_PERIOD)
            if ma20 is None or close1 >= ma20:
                continue

            # 计算涨幅
            gain = (close1 - open1) / open1 * 100

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain': round(gain, 2),
                'close1': round(close1, 4),
                'high2': round(high2, 4),
                'ma20': round(ma20, 4),
                'open1': round(open1, 4),
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
        f"📊 Bitget 4小时级别扫描（第17个工作流 - 突破前高但低于MA20）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根收盘价 > 上上根最高价（突破前高）",
        f"   • 上根收盘价 < MA20",
        f"📊 排序：按上根涨幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   上根涨幅: +{item['gain']}%\n"
                f"   上根收盘: {item['close1']}\n"
                f"   突破前高: 上上根最高 {item['high2']} → {item['close1']} ✅\n"
                f"   MA20: {item['ma20']} (收盘 < MA20 ✅)"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：价格突破前高但仍在牛熊线（MA20）下方，关注能否站稳")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 今日未找到符合条件的币种")

    message = "\n".join(msg_lines)
    print("\n" + "="*50)
    print(message)
    print("="*50)
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
