import ccxt
import time
from datetime import datetime, timedelta, timezone

# ================== 配置区域 ==================
TIMEFRAME_1H = '1h'
PUSH_TOP_N = 10
MA_PERIODS = [5, 10, 20]
KDJ_RSV_PERIOD = 9
KDJ_SMOOTH = 3
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

def calculate_kdj(highs, lows, closes, rsv_period=9, smooth=3):
    n = len(closes)
    k_values = [None] * n
    d_values = [None] * n
    j_values = [None] * n
    if n < rsv_period:
        return k_values, d_values, j_values
    k_prev = 50
    d_prev = 50
    for i in range(rsv_period - 1, n):
        period_high = max(highs[i - rsv_period + 1:i + 1])
        period_low = min(lows[i - rsv_period + 1:i + 1])
        if period_high == period_low:
            rsv = 50
        else:
            rsv = (closes[i] - period_low) / (period_high - period_low) * 100
        k = (k_prev * (smooth - 1) + rsv) / smooth
        d = (d_prev * (smooth - 1) + k) / smooth
        j = 3 * k - 2 * d
        k_values[i] = k
        d_values[i] = d
        j_values[i] = j
        k_prev, d_prev = k, d
    return k_values, d_values, j_values

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第16个工作流扫描（手动运行）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根收盘价 > MA5，且 MA5 > MA10 > MA20")
    print(f"   • 上根KDJ: J > K 且 J > D")
    print(f"   • 上上根KDJ: J < K 且 J < D")
    print(f"   • 按前两根1小时K棒涨幅总和从高到低排序")
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
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=50)
            if len(ohlcv) < 30:
                continue

            k1 = find_kline_by_timestamp(ohlcv, prev1_ts)
            k2 = find_kline_by_timestamp(ohlcv, prev2_ts)
            if not (k1 and k2):
                continue

            # 上根数据
            close1 = k1[4]
            open1 = k1[1]
            # 上上根数据
            close2 = k2[4]
            open2 = k2[1]

            # 计算MA5, MA10, MA20（基于上根）
            ma5 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 5)
            ma10 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 10)
            ma20 = calculate_ma_for_target_kline(ohlcv, prev1_ts, 20)
            if ma5 is None or ma10 is None or ma20 is None:
                continue

            # 条件1：收盘价 > MA5 且 MA5 > MA10 > MA20
            if not (close1 > ma5 and ma5 > ma10 > ma20):
                continue

            # 计算KDJ
            highs = [k[2] for k in ohlcv]
            lows = [k[3] for k in ohlcv]
            closes = [k[4] for k in ohlcv]
            k_vals, d_vals, j_vals = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            idx1 = next((i for i, k in enumerate(ohlcv) if k[0] == prev1_ts), None)
            idx2 = next((i for i, k in enumerate(ohlcv) if k[0] == prev2_ts), None)
            if idx1 is None or idx2 is None:
                continue
            j1 = j_vals[idx1]
            k1_val = k_vals[idx1]
            d1_val = d_vals[idx1]
            j2 = j_vals[idx2]
            k2_val = k_vals[idx2]
            d2_val = d_vals[idx2]
            if None in (j1, k1_val, d1_val, j2, k2_val, d2_val):
                continue

            # 条件2：上根 J > K 且 J > D
            if not (j1 > k1_val and j1 > d1_val):
                continue
            # 条件3：上上根 J < K 且 J < D
            if not (j2 < k2_val and j2 < d2_val):
                continue

            # 计算涨幅
            gain1 = (close1 - open1) / open1 * 100 if open1 != 0 else 0
            gain2 = (close2 - open2) / open2 * 100 if open2 != 0 else 0
            total_gain = gain1 + gain2

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain1': round(gain1, 2),
                'gain2': round(gain2, 2),
                'total_gain': round(total_gain, 2),
                'close1': round(close1, 4),
                'open1': round(open1, 4),
                'close2': round(close2, 4),
                'open2': round(open2, 4),
                'ma5': round(ma5, 4),
                'ma10': round(ma10, 4),
                'ma20': round(ma20, 4),
                'j1': round(j1, 2),
                'k1': round(k1_val, 2),
                'd1': round(d1_val, 2),
                'j2': round(j2, 2),
                'k2': round(k2_val, 2),
                'd2': round(d2_val, 2),
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

    print("\n" + "="*70)
    print(f"📊 Bitget 1小时级别双K线涨幅榜（满足均线多头+KDJ条件）")
    print(f"📈 共筛选出 {len(result_list)} 个符合条件的币种")
    print(f"📋 涨幅总和前十名：")
    print("="*70)
    if top:
        for i, item in enumerate(top, 1):
            print(f"{i}. {item['symbol']}")
            print(f"   上根涨幅: +{item['gain1']}%  ({item['open1']} → {item['close1']})")
            print(f"   上上根涨幅: +{item['gain2']}%  ({item['open2']} → {item['close2']})")
            print(f"   总涨幅: +{item['total_gain']}%")
            print(f"   均线: MA5={item['ma5']} > MA10={item['ma10']} > MA20={item['ma20']}")
            print(f"   上根KDJ: K={item['k1']}, D={item['d1']}, J={item['j1']} (J>K且J>D ✅)")
            print(f"   上上根KDJ: K={item['k2']}, D={item['d2']}, J={item['j2']} (J<K且J<D ✅)")
            print("-"*60)
    else:
        print("😔 未找到符合条件的币种")
    print("="*70)
    print("💡 解读：均线多头 + 上根金叉 + 上上根死叉 + 双K线涨幅领先")
    print("   此信息仅供参考，不构成投资建议")

if __name__ == "__main__":
    main()
