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
TIMEFRAME_1W = '1w'
LOOKBACK_BARS = 7  # 前7根K棒
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

def get_weekly_period_start_timestamp(beijing_dt, offset_weeks=0):
    """获取指定偏移量的周线K线的开始时间戳（毫秒，UTC）"""
    # 获取当前日期所在周的第一天（周一）
    days_since_monday = beijing_dt.weekday()
    monday = beijing_dt - timedelta(days=days_since_monday)
    week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start += timedelta(weeks=offset_weeks)
    utc_start = week_start - timedelta(hours=8)
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
    print(f"🚀 开始第65个工作流扫描（日线：前{LOOKBACK_BARS}根中有跌破前低 + 上根收阳 + 按周线涨幅和排序）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 日线级别：前{LOOKBACK_BARS}根K棒中，至少有一根收盘价低于它前一根的最低价")
    print(f"   • 日线级别：上根K棒收阳（收盘价 > 开盘价）")
    print(f"   • 排序 = 上根周线涨幅 + 上上根周线涨幅（从高到低）")
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

    # 日线级别目标K线时间戳（上根 = 昨天）
    prev1_ts_daily = get_daily_period_start_timestamp(beijing_now, -1)

    # 周线级别目标K线时间戳（用于排序）
    prev1_ts_weekly = get_weekly_period_start_timestamp(beijing_now, -1)   # 上根周线
    prev2_ts_weekly = get_weekly_period_start_timestamp(beijing_now, -2)   # 上上根周线

    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根日线（昨天）: {ts_to_beijing(prev1_ts_daily).strftime('%Y-%m-%d')}")
    print(f"   上根周线: {ts_to_beijing(prev1_ts_weekly).strftime('%Y-%m-%d')}")
    print(f"   上上根周线: {ts_to_beijing(prev2_ts_weekly).strftime('%Y-%m-%d')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取日线K线（需要前8根以上）
            ohlcv_daily = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1D, limit=50)
            if len(ohlcv_daily) < LOOKBACK_BARS + 2:
                continue

            # 获取周线K线（用于排序）
            ohlcv_weekly = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1W, limit=10)
            if len(ohlcv_weekly) < 3:
                continue

            # 查找上根日线K线
            k1_daily = find_kline_by_timestamp(ohlcv_daily, prev1_ts_daily)
            if k1_daily is None:
                continue

            close1 = k1_daily[4]
            open1 = k1_daily[1]
            if open1 == 0:
                continue

            # 条件2：上根收阳
            if close1 <= open1:
                continue

            # 条件1：前 LOOKBACK_BARS 根K棒中，至少有一根收盘价低于它前一根的最低价
            # 找到上根K线在数组中的索引
            idx1 = None
            for i, k in enumerate(ohlcv_daily):
                if k[0] == prev1_ts_daily:
                    idx1 = i
                    break
            if idx1 is None or idx1 < LOOKBACK_BARS:
                continue

            found_breakdown = False
            for j in range(idx1 - LOOKBACK_BARS + 1, idx1 + 1):
                # 当前K线收盘价 < 前一根K线最低价
                current_close = ohlcv_daily[j][4]
                prev_low = ohlcv_daily[j - 1][3]
                if current_close < prev_low:
                    found_breakdown = True
                    break

            if not found_breakdown:
                continue

            # 排序指标：上根周线涨幅 + 上上根周线涨幅
            k1_weekly = find_kline_by_timestamp(ohlcv_weekly, prev1_ts_weekly)
            k2_weekly = find_kline_by_timestamp(ohlcv_weekly, prev2_ts_weekly)
            if k1_weekly is None or k2_weekly is None:
                continue

            open_w1 = k1_weekly[1]
            close_w1 = k1_weekly[4]
            open_w2 = k2_weekly[1]
            close_w2 = k2_weekly[4]
            if open_w1 == 0 or open_w2 == 0:
                continue

            gain_w1 = (close_w1 - open_w1) / open_w1 * 100
            gain_w2 = (close_w2 - open_w2) / open_w2 * 100
            total_gain = gain_w1 + gain_w2

            leverage = leverage_info[symbol]

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'total_gain': round(total_gain, 2),
                'gain_w1': round(gain_w1, 2),
                'gain_w2': round(gain_w2, 2),
                'leverage': round(leverage),
                'close1': round(close1, 4),
                'open1': round(open1, 4),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按周线涨幅和从高到低排序
    result_list.sort(key=lambda x: x['total_gain'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 日线级别形态扫描（第65个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 前{LOOKBACK_BARS}根日线中至少有一根收盘跌破前低 ✅",
        f"   • 上根日线收阳 ✅",
        f"   • 排序 = 上根周线涨幅 + 上上根周线涨幅",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 筛选结果前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   周线涨幅和: +{item['total_gain']}%\n"
                f"   (上上根: {item['gain_w2']}%, 上根: {item['gain_w1']}%)\n"
                f"   上根日线: {item['open1']} → {item['close1']} (收阳 ✅)\n"
                f"   杠杆: {item['leverage']}x"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：前7根中有跌破前低后收阳，按周线累计涨幅排序")
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
