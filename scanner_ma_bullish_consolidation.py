import ccxt
import time
from datetime import datetime, timezone, timedelta
import requests
import json
import math

# ================== 配置区域 ==================
# WxPusher 配置（已自动填充）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10            # 推送前N名
TIMEFRAME_4H = '4h'        # 4小时K线周期
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

def get_4h_period_start_time(beijing_dt):
    """
    根据北京时间，返回该时间所属的4小时K线周期的开始时间（UTC时间戳）
    4小时K线周期：00:00-04:00, 04:00-08:00, 08:00-12:00, 12:00-16:00, 16:00-20:00, 20:00-24:00
    """
    hour = beijing_dt.hour
    if 0 <= hour < 4:
        period_start = beijing_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif 4 <= hour < 8:
        period_start = beijing_dt.replace(hour=4, minute=0, second=0, microsecond=0)
    elif 8 <= hour < 12:
        period_start = beijing_dt.replace(hour=8, minute=0, second=0, microsecond=0)
    elif 12 <= hour < 16:
        period_start = beijing_dt.replace(hour=12, minute=0, second=0, microsecond=0)
    elif 16 <= hour < 20:
        period_start = beijing_dt.replace(hour=16, minute=0, second=0, microsecond=0)
    else:
        period_start = beijing_dt.replace(hour=20, minute=0, second=0, microsecond=0)
    
    # 转换为UTC时间戳（毫秒）
    period_start_utc = period_start - timedelta(hours=8)
    return int(period_start_utc.timestamp() * 1000)

def find_kline_by_time(ohlcv_list, target_timestamp):
    """
    在K线列表中查找指定时间戳的K线（按开始时间匹配）
    返回K线数据，如果未找到返回None
    """
    for kline in ohlcv_list:
        if kline[0] == target_timestamp:
            return kline
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

def is_consolidation_kline(current_close, prev_high, prev_low):
    """
    判断当前K线是否处于震荡（收盘价落在前一根K线的高低点区间内）
    """
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

def main():
    beijing_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🚀 开始均线多头+双K线震荡+KDJ上升扫描 - 北京时间 {beijing_time}")
    print(f"📈 策略逻辑：")
    print(f"   • 4小时图均线多头排列（MA5 > MA10 > MA20，且收盘价 > MA5）")
    print(f"   • 上根和上上根4小时K棒均处于震荡（收盘价落于前一根区间内）")
    print(f"   • 上根4小时K棒的KDJ的J值 > 上上根4小时K棒的J值")
    print(f"📊 排序：按24小时涨幅从高到低")
    
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
    
    # ========== 第二步：获取24h涨幅数据 ==========
    print("📡 正在获取所有合约的24h涨幅数据...")
    try:
        tickers = exchange.fetch_tickers()
        print(f"📊 共获取 {len(tickers)} 个交易对数据")
    except Exception as e:
        print(f"❌ 获取市场数据失败: {e}")
        return
    
    daily_gain_dict = {}
    for symbol, ticker in tickers.items():
        if '/USDT:USDT' in symbol and ticker.get('percentage') is not None:
            daily_gain_dict[symbol] = ticker['percentage']
    
    # ========== 第三步：计算目标K线的时间段 ==========
    now_beijing = datetime.now()
    print(f"📅 当前北京时间: {now_beijing.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 获取当前K线周期的开始时间
    current_period_start = get_4h_period_start_time(now_beijing)
    
    # 上根（往前推一个4小时周期）
    prev_period_start = current_period_start - 4 * 60 * 60 * 1000
    # 上上根（往前推两个4小时周期）
    prev2_period_start = current_period_start - 8 * 60 * 60 * 1000
    # 上上上根（往前推三个4小时周期，用于震荡判断）
    prev3_period_start = current_period_start - 12 * 60 * 60 * 1000
    
    print(f"📅 目标K线时间段：")
    print(f"   上根: {datetime.fromtimestamp(prev_period_start/1000).strftime('%Y-%m-%d %H:%M')} - {datetime.fromtimestamp((prev_period_start+4*3600000)/1000).strftime('%H:%M')}")
    print(f"   上上根: {datetime.fromtimestamp(prev2_period_start/1000).strftime('%Y-%m-%d %H:%M')} - {datetime.fromtimestamp((prev2_period_start+4*3600000)/1000).strftime('%H:%M')}")
    
    # ========== 第四步：获取4小时K线数据并分析 ==========
    print(f"⏳ 正在获取4小时K线数据...")
    result_list = []
    
    for i, symbol in enumerate(swap_symbols):
        try:
            # 获取足够多的4小时K线（需要至少30根计算MA20和KDJ）
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=50)
            if len(ohlcv_4h) < 30:
                continue
            
            # ========== 根据时间戳精确查找目标K线 ==========
            kline_prev1 = find_kline_by_time(ohlcv_4h, prev_period_start)   # 上根
            kline_prev2 = find_kline_by_time(ohlcv_4h, prev2_period_start)  # 上上根
            kline_prev3 = find_kline_by_time(ohlcv_4h, prev3_period_start)  # 上上上根
            
            if not (kline_prev1 and kline_prev2 and kline_prev3):
                continue
            
            # 提取K线数据
            close_prev1 = kline_prev1[4]   # 上根收盘价
            high_prev1 = kline_prev1[2]    # 上根最高价
            low_prev1 = kline_prev1[3]     # 上根最低价
            
            close_prev2 = kline_prev2[4]   # 上上根收盘价
            high_prev2 = kline_prev2[2]    # 上上根最高价
            low_prev2 = kline_prev2[3]     # 上上根最低价
            
            high_prev3 = kline_prev3[2]    # 上上上根最高价
            low_prev3 = kline_prev3[3]     # 上上上根最低价
            
            # ========== 均线计算（使用所有K线数据） ==========
            closes = [k[4] for k in ohlcv_4h]
            ma_values = calculate_moving_averages(closes, MA_PERIODS)
            
            if not is_bullish_arrangement(ma_values):
                continue
            
            # 当前收盘价（最近一根已收盘K线）与MA5比较
            current_close = ohlcv_4h[-1][4]
            if current_close <= ma_values[5]:
                continue
            
            # ========== 震荡判断 ==========
            is_consolidation_prev2 = is_consolidation_kline(close_prev2, high_prev3, low_prev3)
            is_consolidation_prev1 = is_consolidation_kline(close_prev1, high_prev2, low_prev2)
            
            if not (is_consolidation_prev2 and is_consolidation_prev1):
                continue
            
            # ========== KDJ指标计算 ==========
            highs = [k[2] for k in ohlcv_4h]
            lows = [k[3] for k in ohlcv_4h]
            
            k_values, d_values, j_values = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            
            # 找到上根和上上根在列表中的索引
            idx_prev1 = None
            idx_prev2 = None
            for idx, kline in enumerate(ohlcv_4h):
                if kline[0] == prev_period_start:
                    idx_prev1 = idx
                if kline[0] == prev2_period_start:
                    idx_prev2 = idx
            
            if idx_prev1 is None or idx_prev2 is None:
                continue
            if j_values[idx_prev1] is None or j_values[idx_prev2] is None:
                continue
            
            j_prev1 = j_values[idx_prev1]
            j_prev2 = j_values[idx_prev2]
            
            if not (j_prev1 > j_prev2):
                continue
            
            # 所有条件满足
            daily_gain = daily_gain_dict.get(symbol, 0)
            
            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                'daily_gain': round(daily_gain, 2),
                'ma5': round(ma_values[5], 4),
                'ma10': round(ma_values[10], 4),
                'ma20': round(ma_values[20], 4),
                'current_close': round(current_close, 4),
                'j_prev2': round(j_prev2, 2),
                'j_prev1': round(j_prev1, 2),
                'close_prev2': round(close_prev2, 4),
                'high_prev3': round(high_prev3, 4),
                'low_prev3': round(low_prev3, 4),
                'close_prev1': round(close_prev1, 4),
                'high_prev2': round(high_prev2, 4),
                'low_prev2': round(low_prev2, 4),
            })
            print(f"✓ {symbol} 均线多头+双K线震荡+J值上升({j_prev2:.2f}→{j_prev1:.2f})，24h涨幅{daily_gain:.2f}%")
            
            if (i + 1) % 50 == 0:
                print(f"   进度: {i+1}/{len(swap_symbols)}")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)
    
    # ========== 第五步：排序推送 ==========
    result_list.sort(key=lambda x: x['daily_gain'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 均线多头+双K线震荡+KDJ上升扫描",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 4小时图均线多头排列（MA5 > MA10 > MA20，价格 > MA5）",
        f"   • 上根和上上根4小时K棒均处于震荡（收盘价落于前一根区间内）",
        f"   • 上根KDJ的J值 > 上上根KDJ的J值",
        f"📊 排序：按24小时涨幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   24h涨幅: +{item['daily_gain']}%\n"
                f"   均线: MA5={item['ma5']} > MA10={item['ma10']} > MA20={item['ma20']}\n"
                f"   当前价: {item['current_close']} > MA5 ✅\n"
                f"   J值变化: {item['j_prev2']:.2f} → {item['j_prev1']:.2f} 📈\n"
                f"   上上根震荡: 收盘{item['close_prev2']} 落于区间[{item['low_prev3']}-{item['high_prev3']}]\n"
                f"   上根震荡: 收盘{item['close_prev1']} 落于区间[{item['low_prev2']}-{item['high_prev2']}]"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：均线多头+双K线区间震荡+J值上升，动能增强，蓄势待涨")
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
