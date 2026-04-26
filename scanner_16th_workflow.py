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
    """根据北京时间，获取指定偏移量的1小时K线周期的开始时间戳（毫秒，UTC）"""
    total_minutes = beijing_dt.hour * 60 + beijing_dt.minute
    period_minutes = total_minutes // 60 * 60  # 1小时 = 60分钟
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
    print(f"🚀 开始第16个工作流扫描（1小时涨幅榜 - 手动运行）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 扫描所有USDT本位永续合约")
    print(f"   • 按上根1小时K棒涨幅从高到低排序")
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

    # 目标K线时间戳（上根1小时）
    prev1_ts = get_1h_period_start_timestamp(beijing_now, -1)

    print(f"📅 目标K线时间段（北京时间）:")
    print(f"   上根1小时: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=1)).strftime('%H:%M')}")

    print("⏳ 正在获取K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=5)
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

    print("\n" + "="*60)
    print(f"📊 Bitget 1小时级别涨幅榜（共{len(result_list)}个合约）")
    print(f"📈 上根1小时K棒涨幅排行榜 Top {len(top)}")
    print("="*60)
    if top:
        for i, item in enumerate(top, 1):
            print(f"{i}. {item['symbol']}")
            print(f"   涨幅: +{item['gain']}%")
            print(f"   开盘: {item['open1']} → 收盘: {item['close1']}")
            print("-"*40)
    else:
        print("😔 未找到K线数据")
    print("="*60)
    print("💡 此信息仅供参考，不构成投资建议")

if __name__ == "__main__":
    main()
