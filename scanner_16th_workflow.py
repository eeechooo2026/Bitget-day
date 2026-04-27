import ccxt
import time
from datetime import datetime, timedelta, timezone

# ================== 配置区域 ==================
TIMEFRAME_1H = '1h'
PUSH_TOP_N = 10
# =============================================

def get_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_1h_period_start_timestamp(beijing_dt, offset_periods=0):
    total_minutes = beijing_dt.hour * 60 + beijing_dt.minute
    period_minutes = total_minutes // 60 * 60
    start_hour = period_minutes // 60
    start_minute = period_minutes % 60
    period_start = beijing_dt.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    period_start += timedelta(hours=offset_periods * 1)
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
    print(f"🚀 开始第16个工作流扫描（手动运行 - 原始版本）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 扫描所有USDT本位永续合约")
    print(f"   • 按前两根1小时K棒（上根 + 上上根）的涨幅总和从高到低排序")
    print(f"📊 输出：前十名（仅控制台，不推送微信）")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")
    swap_symbols = [s for s, m in markets.items() if m['type'] == 'swap' and s.endswith('/USDT:USDT')]
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    # 目标K线时间戳
    prev1_ts = get_1h_period_start_timestamp(beijing_now, -1)   # 上根
    prev2_ts = get_1h_period_start_timestamp(beijing_now, -2)   # 上上根

    print(f"📅 目标K线时间段（北京时间）:")
    print(f"   上根: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上根: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=1)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=10)
            if len(ohlcv) < 3:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)   # 上根
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)   # 上上根
            if k1 is None or k2 is None:
                continue

            # 上根涨幅
            open1 = k1[1]
            close1 = k1[4]
            if open1 == 0:
                continue
            gain1 = (close1 - open1) / open1 * 100

            # 上上根涨幅
            open2 = k2[1]
            close2 = k2[4]
            if open2 == 0:
                continue
            gain2 = (close2 - open2) / open2 * 100

            total_gain = gain1 + gain2

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain1': round(gain1, 2),
                'gain2': round(gain2, 2),
                'total_gain': round(total_gain, 2),
                'open1': round(open1, 4),
                'close1': round(close1, 4),
                'open2': round(open2, 4),
                'close2': round(close2, 4),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按总涨幅从高到低排序
    result_list.sort(key=lambda x: x['total_gain'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    print("\n" + "="*60)
    print(f"📊 Bitget 1小时级别双K线涨幅榜（无筛选条件）")
    print(f"📈 共扫描 {len(result_list)} 个有数据合约")
    print(f"📋 涨幅总和前十名：")
    print("="*60)
    if top:
        for i, item in enumerate(top, 1):
            print(f"{i}. {item['symbol']}")
            print(f"   上根涨幅: +{item['gain1']}%  ({item['open1']} → {item['close1']})")
            print(f"   上上根涨幅: +{item['gain2']}%  ({item['open2']} → {item['close2']})")
            print(f"   总涨幅: +{item['total_gain']}%")
            print("-"*40)
    else:
        print("😔 未找到K线数据")
    print("="*60)
    print("💡 此信息仅供参考，不构成投资建议")

if __name__ == "__main__":
    main()
