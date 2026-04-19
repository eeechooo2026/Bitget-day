import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
# WxPusher 配置（请替换成你自己的信息）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10            # 推送前N名
TIMEFRAME_4H = '4h'        # 主分析周期：4小时
TIMEFRAME_1D = '1d'        # 排序周期：日线
MA_PERIODS = [5, 10, 20]   # 均线周期
KDJ_RSV_PERIOD = 9         # KDJ指标中RSV的周期
KDJ_SMOOTH = 3             # K、D的平滑周期
# =============================================

def send_push_wxpusher(message):
    """使用 WxPusher 推送消息到微信"""
    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": WX_PUSHER_APP_TOKEN,
        "content": message,
        "summary": message[:50] if len(message) > 50 else message,
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
            return True
        else:
            print(f"❌ WxPusher 推送失败: {result}")
            return False
    except Exception as e:
        print(f"❌ 推送异常: {e}")
        return False

def get_utc_now():
    """获取当前UTC时间的datetime对象（无时区信息）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_4h_period_start_timestamp(beijing_dt, offset_periods=0):
    """
    根据北京时间，获取指定偏移量的4小时K线周期的开始时间戳（毫秒，UTC）
    offset_periods: 0表示当前周期，-1表示上一个周期，-2表示上上个周期，以此类推
    """
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
    # 转换为UTC时间戳（毫秒）
    utc_start = period_start - timedelta(hours=8)
    return int(utc_start.timestamp() * 1000)

def get_daily_period_start_timestamp(beijing_dt, offset_days=0):
    """
    根据北京时间，获取指定偏移量的日线K线的开始时间戳（毫秒，UTC）
    offset_days: 0表示今天，-1表示昨天，-2表示前天，以此类推
    """
    day_start = beijing_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start += timedelta(days=offset_days)
    utc_start = day_start - timedelta(hours=8)
    return int(utc_start.timestamp() * 1000)

def find_kline_by_timestamp(ohlcv, target_ts):
    """在K线列表中查找指定开始时间戳的K线"""
    for k in ohlcv:
        if k[0] == target_ts:
            return k
    return None

def calculate_moving_averages(closes, periods):
    """计算移动平均线"""
    ma_values = {}
    for period in periods:
        if len(closes) >= period:
            ma_values[period] = sum(closes[-period:]) / period
        else:
            ma_values[period] = None
    return ma_values

def is_bearish_arrangement(ma_values):
    """判断均线是否空头排列 MA5 < MA10 < MA20"""
    if ma_values[5] is None or ma_values[10] is None or ma_values[20] is None:
        return False
    return ma_values[5] < ma_values[10] < ma_values[20]

def is_consolidation_kline(current_close, prev_high, prev_low):
    """判断当前K线是否处于震荡（收盘价落在前一根K线的高低点区间内）"""
    return current_close < prev_high and current_close > prev_low

def calculate_kdj(highs, lows, closes, rsv_period=9, smooth=3):
    """
    计算KDJ指标
    返回：k_values, d_values, j_values 数组
    """
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
        
        k_prev = k
        d_prev = d
    
    return k_values, d_values, j_values

def calculate_daily_loss(ohlcv_1d, target_ts, prev_ts):
    """
    计算前两根日线K棒的累计跌幅（负数，值越小代表跌幅越大）
    target_ts: 前一根日线（较新）的时间戳
    prev_ts:   前前一根日线（较旧）的时间戳
    """
    k_target = find_kline_by_timestamp(ohlcv_1d, target_ts)
    k_prev = find_kline_by_timestamp(ohlcv_1d, prev_ts)
    
    if not (k_target and k_prev):
        return None
    
    close_target = k_target[4]
    close_prev = k_prev[4]
    
    if close_prev == 0:
        return None
    
    loss = (close_target - close_prev) / close_prev * 100  # 负值表示下跌
    return loss

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第十一个工作流扫描（4小时级别空头，基于第五个逻辑） - 北京时间 {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📉 策略逻辑（空头）：")
    print(f"   • 4小时图均线空头排列（MA5 < MA10 < MA20，且上根K棒收盘价 < MA5）")
    print(f"   • 上根和上上根4小时K棒均处于震荡（收盘价落于前一根区间内）")
    print(f"   • 上根KDJ的J值 < 上上根KDJ的J值")
    print(f"📊 排序：按前两根日线K棒跌幅从高到低（跌幅越大越靠前）")
    
    # 初始化 Bitget 合约接口
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
        },
    })
    
    # ========== 第一步：获取所有USDT本位永续合约 ==========
    print("📡 正在加载合约市场数据...")
    try:
        markets = exchange.load_markets()
        print(f"📊 共加载 {len(markets)} 个交易对")
    except Exception as e:
        print(f"❌ 加载市场数据失败: {e}")
        return
    
    swap_symbols = []
    for symbol, market in markets.items():
        if market.get('type') == 'swap' and symbol.endswith('/USDT:USDT'):
            swap_symbols.append(symbol)
    
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")
    
    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return
    
    # ========== 第二步：计算目标K线的时间戳 ==========
    # 4小时级别
    prev1_ts_4h = get_4h_period_start_timestamp(beijing_now, -1)   # 上根4小时
    prev2_ts_4h = get_4h_period_start_timestamp(beijing_now, -2)   # 上上根4小时
    prev3_ts_4h = get_4h_period_start_timestamp(beijing_now, -3)   # 上上上根4小时（用于震荡判断）
    
    # 日线级别（用于排序）：取昨天和前天两根已收盘的日线
    prev1_ts_1d = get_daily_period_start_timestamp(beijing_now, -1)   # 昨天日线
    prev2_ts_1d = get_daily_period_start_timestamp(beijing_now, -2)   # 前天日线
    
    def ts_to_beijing(ts):
        return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)
    
    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根4小时: {ts_to_beijing(prev1_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上根4小时: {ts_to_beijing(prev2_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   上上上根4小时: {ts_to_beijing(prev3_ts_4h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev3_ts_4h)+timedelta(hours=4)).strftime('%H:%M')}")
    print(f"   排序用日线: {ts_to_beijing(prev2_ts_1d).strftime('%Y-%m-%d')} 和 {ts_to_beijing(prev1_ts_1d).strftime('%Y-%m-%d')}")
    
    # ========== 第三步：获取所有合约的4小时和日线K线数据 ==========
    print(f"⏳ 正在获取K线数据...")
    result_list = []
    
    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取4小时K线数据（需要至少30根）
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=50)
            if len(ohlcv_4h) < 30:
                continue
            
            # 获取日线K线数据（需要至少5根）
            ohlcv_1d = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1D, limit=10)
            if len(ohlcv_1d) < 5:
                continue
            
            # ========== 4小时级别条件判断 ==========
            closes_4h = [k[4] for k in ohlcv_4h]
            ma_values = calculate_moving_averages(closes_4h, MA_PERIODS)
            
            # 条件1：均线空头排列
            if not is_bearish_arrangement(ma_values):
                continue
            
            # 精确查找4小时K线
            k_prev1 = find_kline_by_timestamp(ohlcv_4h, prev1_ts_4h)  # 上根
            k_prev2 = find_kline_by_timestamp(ohlcv_4h, prev2_ts_4h)  # 上上根
            k_prev3 = find_kline_by_timestamp(ohlcv_4h, prev3_ts_4h)  # 上上上根
            
            if not (k_prev1 and k_prev2 and k_prev3):
                continue
            
            close1 = k_prev1[4]
            open1 = k_prev1[1]
            close2 = k_prev2[4]
            high2 = k_prev2[2]
            low2 = k_prev2[3]
            high3 = k_prev3[2]
            low3 = k_prev3[3]
            
            # 条件2：上根K棒收盘价 < MA5（空头）
            if close1 >= ma_values[5]:
                continue
            
            # 条件3：上上根震荡（收盘价介于上上上根高低点之间）
            if not is_consolidation_kline(close2, high3, low3):
                continue
            
            # 条件4：上根震荡（收盘价介于上上根高低点之间）
            if not is_consolidation_kline(close1, high2, low2):
                continue
            
            # 条件5：KDJ的J值小于上上根（空头）
            highs_4h = [k[2] for k in ohlcv_4h]
            lows_4h = [k[3] for k in ohlcv_4h]
            _, _, j_vals = calculate_kdj(highs_4h, lows_4h, closes_4h, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            
            idx1 = next((i for i, k in enumerate(ohlcv_4h) if k[0] == prev1_ts_4h), None)
            idx2 = next((i for i, k in enumerate(ohlcv_4h) if k[0] == prev2_ts_4h), None)
            if idx1 is None or idx2 is None or j_vals[idx1] is None or j_vals[idx2] is None:
                continue
            
            if j_vals[idx1] >= j_vals[idx2]:
                continue
            
            # ========== 日线级别跌幅计算 ==========
            loss_1d = calculate_daily_loss(ohlcv_1d, prev1_ts_1d, prev2_ts_1d)
            if loss_1d is None:
                continue
            
            # 所有条件满足，添加到结果列表
            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                'loss_1d': round(loss_1d, 2),
                'ma5': round(ma_values[5], 4),
                'ma10': round(ma_values[10], 4),
                'ma20': round(ma_values[20], 4),
                'close1': round(close1, 4),
                'j_prev2': round(j_vals[idx2], 2),
                'j_prev1': round(j_vals[idx1], 2),
                'close2': round(close2, 4),
                'high3': round(high3, 4),
                'low3': round(low3, 4),
                'high2': round(high2, 4),
                'low2': round(low2, 4),
            })
            print(f"✓ {symbol} 满足空头条件，日线累计跌幅{loss_1d:.2f}%")
            
            if (idx + 1) % 50 == 0:
                print(f"   进度: {idx+1}/{len(swap_symbols)}")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)
    
    # ========== 第四步：按日线跌幅从高到低排序（跌幅越负越靠前） ==========
    result_list.sort(key=lambda x: x['loss_1d'])  # 升序：-8, -5, -3, ...
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第五步：生成推送消息 ==========
    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 4小时级别空头扫描（第十一个工作流 - 基于第五个逻辑）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📉 策略逻辑（空头）：",
        f"   • 4小时图均线空头排列（MA5<MA10<MA20，且上根收盘价<MA5）",
        f"   • 上根和上上根4小时K棒均处于震荡（收盘价落于前一根区间内）",
        f"   • 上根KDJ的J值 < 上上根KDJ的J值",
        f"📊 排序：按前两根日线K棒累计跌幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for i, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   日线累计跌幅: {item['loss_1d']}%\n"
                f"   均线: {item['ma5']} < {item['ma10']} < {item['ma20']}\n"
                f"   上根收盘: {item['close1']} < MA5 ✅\n"
                f"   J值变化: {item['j_prev2']} → {item['j_prev1']} 📉\n"
                f"   上上根震荡: 收盘{item['close2']} 落于区间[{item['low3']}-{item['high3']}]\n"
                f"   上根震荡: 收盘{item['close1']} 落于区间[{item['low2']}-{item['high2']}]"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：均线空头+双K线区间震荡+J值下降，日线级别下跌趋势确认")
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
