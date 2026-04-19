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
TIMEFRAME_1H = '1h'        # 主分析周期：1小时
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

def get_period_start_timestamp(beijing_dt, offset_periods=0, timeframe_minutes=60):
    """
    根据北京时间，获取指定偏移量的K线周期的开始时间戳（毫秒，UTC）
    offset_periods: 0表示当前周期，-1表示上一个周期，-2表示上上个周期，以此类推
    """
    total_minutes = beijing_dt.hour * 60 + beijing_dt.minute
    period_minutes = total_minutes // timeframe_minutes * timeframe_minutes
    start_hour = period_minutes // 60
    start_minute = period_minutes % 60
    period_start = beijing_dt.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    period_start += timedelta(hours=offset_periods * (timeframe_minutes / 60))
    # 转换为UTC时间戳（毫秒）
    utc_start = period_start - timedelta(hours=8)
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

def calculate_hourly_loss(ohlcv_1h, target_ts, prev_ts):
    """
    计算前两根1小时K棒的累计跌幅（负数，值越小代表跌幅越大）
    返回：跌幅百分比（例如 -3.2 表示下跌3.2%）
    """
    k_target = find_kline_by_timestamp(ohlcv_1h, target_ts)  # 较新（上一根）
    k_prev = find_kline_by_timestamp(ohlcv_1h, prev_ts)      # 较旧（上上一根）
    
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
    print(f"🚀 开始第九个工作流扫描（1小时级别空头） - 北京时间 {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📉 策略逻辑（空头）：")
    print(f"   • 上根1小时K棒均线空头排列（MA5 < MA10 < MA20，且上根K棒收盘价 < MA5）")
    print(f"   • 上根1小时K棒收阴、最高价高于上上根K棒的最高价、且KDJ的J值小于上上根")
    print(f"📊 排序：按前两根1小时K棒跌幅从高到低（跌幅越大越靠前）")
    
    # 初始化 Bitget 合约接口
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',  # 永续合约
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
    # 上根 = 上一个完整1小时周期 (offset=-1)
    # 上上根 = 上上个周期 (offset=-2)
    prev1_ts = get_period_start_timestamp(beijing_now, -1, 60)   # 上根1小时
    prev2_ts = get_period_start_timestamp(beijing_now, -2, 60)   # 上上根1小时
    
    # 用于跌幅排序：取前两根1小时K线（与上根、上上根相同）
    sort_prev1_ts = prev1_ts
    sort_prev2_ts = prev2_ts
    
    def ts_to_beijing(ts):
        return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)
    
    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根1小时: {ts_to_beijing(prev1_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上根1小时: {ts_to_beijing(prev2_ts).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   排序用1小时K线: 同上（前两根1小时K棒）")
    
    # ========== 第三步：获取所有合约的1小时K线数据 ==========
    print(f"⏳ 正在获取1小时K线数据...")
    result_list = []
    
    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取足够多的1小时K线数据（需要至少30根）
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=50)
            if len(ohlcv) < 30:
                continue
            
            # 提取收盘价序列用于计算均线
            closes = [k[4] for k in ohlcv]
            ma_values = calculate_moving_averages(closes, MA_PERIODS)
            
            # 条件1：均线空头排列
            if not is_bearish_arrangement(ma_values):
                continue
            
            # 精确查找目标K线
            k_prev1 = find_kline_by_timestamp(ohlcv, prev1_ts)  # 上根
            k_prev2 = find_kline_by_timestamp(ohlcv, prev2_ts)  # 上上根
            
            if not (k_prev1 and k_prev2):
                continue
            
            # 提取K线数据
            close1 = k_prev1[4]   # 上根收盘价
            open1 = k_prev1[1]    # 上根开盘价
            high1 = k_prev1[2]    # 上根最高价
            high2 = k_prev2[2]    # 上上根最高价
            
            # 条件2：上根K棒收盘价 < MA5
            if close1 >= ma_values[5]:
                continue
            
            # 条件3：上根收阴
            if close1 >= open1:
                continue
            
            # 条件4：上根最高价 > 上上根最高价
            if high1 <= high2:
                continue
            
            # 条件5：KDJ的J值小于上上根
            highs = [k[2] for k in ohlcv]
            lows = [k[3] for k in ohlcv]
            _, _, j_vals = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            
            idx1 = next((i for i, k in enumerate(ohlcv) if k[0] == prev1_ts), None)
            idx2 = next((i for i, k in enumerate(ohlcv) if k[0] == prev2_ts), None)
            if idx1 is None or idx2 is None or j_vals[idx1] is None or j_vals[idx2] is None:
                continue
            
            j_prev1 = j_vals[idx1]
            j_prev2 = j_vals[idx2]
            
            if j_prev1 >= j_prev2:
                continue
            
            # ========== 跌幅计算（前两根1小时K棒累计跌幅） ==========
            loss = calculate_hourly_loss(ohlcv, prev1_ts, prev2_ts)
            if loss is None:
                continue
            
            # 所有条件满足，添加到结果列表
            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                'loss': round(loss, 2),
                'ma5': round(ma_values[5], 4),
                'ma10': round(ma_values[10], 4),
                'ma20': round(ma_values[20], 4),
                'close1': round(close1, 4),
                'high1': round(high1, 4),
                'high2': round(high2, 4),
                'j_prev2': round(j_prev2, 2),
                'j_prev1': round(j_prev1, 2),
            })
            print(f"✓ {symbol} 满足空头条件，累计跌幅{loss:.2f}%")
            
            if (idx + 1) % 50 == 0:
                print(f"   进度: {idx+1}/{len(swap_symbols)}")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)
    
    # ========== 第四步：按跌幅从高到低排序（跌幅越负越靠前） ==========
    # 跌幅是负数，比如 -5% 比 -3% 更小，所以直接升序排序即可（最负的排最前）
    result_list.sort(key=lambda x: x['loss'])  # 升序：-5, -3, -1, ...
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第五步：生成推送消息 ==========
    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 1小时级别空头扫描（第九个工作流）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📉 策略逻辑（空头）：",
        f"   • 上根1小时K棒均线空头排列（MA5<MA10<MA20，且收盘价<MA5）",
        f"   • 上根1小时K棒收阴、最高价高于上上根最高价、KDJ的J值小于上上根",
        f"📊 排序：按前两根1小时K棒累计跌幅从高到低（跌幅越大越靠前）",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for i, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   累计跌幅: {item['loss']}%\n"
                f"   均线: {item['ma5']} < {item['ma10']} < {item['ma20']}\n"
                f"   上根收盘: {item['close1']} < MA5 ✅\n"
                f"   上根最高: {item['high1']} > 上上根最高 {item['high2']}\n"
                f"   J值变化: {item['j_prev2']} → {item['j_prev1']} 📉"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：1小时级别均线空头+创新高+J值下降，下跌趋势加速")
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
