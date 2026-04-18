import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json
import math
import numpy as np
from collections import defaultdict

# ================== 配置区域 ==================
# WxPusher 配置（请替换成你自己的信息）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10            # 推送前N名
TIMEFRAME_1H = '1h'        # 主分析周期：1小时
TIMEFRAME_4H = '4h'        # 排序周期：4小时
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
    # 计算当前周期开始时间（北京时间）
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

def is_bullish_arrangement(ma_values):
    """判断均线是否多头排列 MA5 > MA10 > MA20"""
    if ma_values[5] is None or ma_values[10] is None or ma_values[20] is None:
        return False
    return ma_values[5] > ma_values[10] > ma_values[20]

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

def calculate_4h_gain(ohlcv_4h, target_ts, prev2_ts):
    """
    计算指定K线及其前一根4小时K线的累计涨幅
    """
    k_target = find_kline_by_timestamp(ohlcv_4h, target_ts)
    k_prev = find_kline_by_timestamp(ohlcv_4h, prev2_ts)
    
    if not (k_target and k_prev):
        return None
    
    close_target = k_target[4]
    close_prev = k_prev[4]
    
    if close_prev == 0:
        return None
    
    gain = (close_target - close_prev) / close_prev * 100
    return gain

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始扫描 - 当前UTC时间: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 上根1小时K棒均线多头排列（MA5 > MA10 > MA20，且上根K棒收盘价 > MA5）")
    print(f"   • 上根1小时K棒收阳、最低价低于上上根K棒的最低价、且KDJ的J值大于上上根")
    print(f"📊 排序：按前两根4小时K棒涨幅从高到低")
    
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
    # 4小时排序：取前两根4小时K棒，即往前推第2根和第1根
    prev1_ts_1h = get_period_start_timestamp(beijing_now, -1, 60)   # 上根1小时
    prev2_ts_1h = get_period_start_timestamp(beijing_now, -2, 60)   # 上上根1小时
    
    # 用于4小时涨幅排序：取当前周期之前的第1根和第2根
    # 注意：这里取的是已收盘的完整4小时K线
    prev1_ts_4h = get_period_start_timestamp(beijing_now, -1, 240)   # 上一根4小时
    prev2_ts_4h = get_period_start_timestamp(beijing_now, -2, 240)   # 上上一根4小时
    
    def ts_to_beijing(ts):
        return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)
    
    print("📅 目标K线时间段（北京时间）:")
    print(f"   上根1小时: {ts_to_beijing(prev1_ts_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev1_ts_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   上上根1小时: {ts_to_beijing(prev2_ts_1h).strftime('%Y-%m-%d %H:%M')} - {(ts_to_beijing(prev2_ts_1h)+timedelta(hours=1)).strftime('%H:%M')}")
    print(f"   排序用4小时K线: {ts_to_beijing(prev2_ts_4h).strftime('%m-%d %H:%M')} 和 {ts_to_beijing(prev1_ts_4h).strftime('%m-%d %H:%M')}")
    
    # ========== 第三步：获取所有合约的1小时和4小时K线数据 ==========
    print(f"⏳ 正在获取K线数据...")
    result_list = []
    
    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取1小时K线数据（需要至少30根）
            ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1H, limit=50)
            if len(ohlcv_1h) < 30:
                continue
            
            # 获取4小时K线数据（用于涨幅排序）
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=20)
            if len(ohlcv_4h) < 10:
                continue
            
            # ========== 1小时级别条件判断 ==========
            # 提取1小时收盘价序列用于计算均线
            closes_1h = [k[4] for k in ohlcv_1h]
            ma_values_1h = calculate_moving_averages(closes_1h, MA_PERIODS)
            
            # 条件1：均线多头排列
            if not is_bullish_arrangement(ma_values_1h):
                continue
            
            # 精确查找目标K线
            k_prev1_1h = find_kline_by_timestamp(ohlcv_1h, prev1_ts_1h)  # 上根
            k_prev2_1h = find_kline_by_timestamp(ohlcv_1h, prev2_ts_1h)  # 上上根
            
            if not (k_prev1_1h and k_prev2_1h):
                continue
            
            # 提取K线数据
            close1 = k_prev1_1h[4]   # 上根收盘价
            open1 = k_prev1_1h[1]    # 上根开盘价
            low1 = k_prev1_1h[3]     # 上根最低价
            
            low2 = k_prev2_1h[3]     # 上上根最低价
            
            # 条件2：上根K棒价格 > MA5
            if close1 <= ma_values_1h[5]:
                continue
            
            # 条件3：上根收阳
            if close1 <= open1:
                continue
            
            # 条件4：上根最低价 < 上上根最低价
            if low1 >= low2:
                continue
            
            # 条件5：KDJ的J值大于上上根
            highs_1h = [k[2] for k in ohlcv_1h]
            lows_1h = [k[3] for k in ohlcv_1h]
            _, _, j_vals_1h = calculate_kdj(highs_1h, lows_1h, closes_1h, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            
            # 找到上根和上上根在数组中的索引
            idx1 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev1_ts_1h), None)
            idx2 = next((i for i, k in enumerate(ohlcv_1h) if k[0] == prev2_ts_1h), None)
            if idx1 is None or idx2 is None or j_vals_1h[idx1] is None or j_vals_1h[idx2] is None:
                continue
            
            j_prev1 = j_vals_1h[idx1]
            j_prev2 = j_vals_1h[idx2]
            
            if j_prev1 <= j_prev2:
                continue
            
            # ========== 4小时级别涨幅计算 ==========
            # 计算前两根4小时K棒的累计涨幅
            gain_4h = calculate_4h_gain(ohlcv_4h, prev1_ts_4h, prev2_ts_4h)
            if gain_4h is None:
                continue
            
            # 所有条件满足，添加到结果列表
            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                'gain_4h': round(gain_4h, 2),
                'ma5': round(ma_values_1h[5], 4),
                'ma10': round(ma_values_1h[10], 4),
                'ma20': round(ma_values_1h[20], 4),
                'close1': round(close1, 4),
                'low1': round(low1, 4),
                'low2': round(low2, 4),
                'j_prev2': round(j_prev2, 2),
                'j_prev1': round(j_prev1, 2),
            })
            print(f"✓ {symbol} 满足1小时条件，4小时涨幅{gain_4h:.2f}%")
            
            if (idx + 1) % 50 == 0:
                print(f"   进度: {idx+1}/{len(swap_symbols)}")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)
    
    # ========== 第四步：按4小时涨幅排序，取前十 ==========
    result_list.sort(key=lambda x: x['gain_4h'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第五步：生成推送消息 ==========
    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 1小时级别扫描",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 上根1小时K棒均线多头排列（MA5>MA10>MA20，且收盘价>MA5）",
        f"   • 上根1小时K棒收阳、最低价低于上上根最低价",
        f"   • 上根1小时K棒的KDJ的J值 > 上上根",
        f"📊 排序：按前两根4小时K棒涨幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for i, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   4小时涨幅: +{item['gain_4h']}%\n"
                f"   均线: {item['ma5']} > {item['ma10']} > {item['ma20']}\n"
                f"   上根收盘: {item['close1']} > MA5 ✅\n"
                f"   上根最低: {item['low1']} < 上上根最低 {item['low2']}\n"
                f"   J值变化: {item['j_prev2']} → {item['j_prev1']} 📈"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：1小时级别均线多头+创新低+J值上升，4小时级别正处上涨阶段")
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
