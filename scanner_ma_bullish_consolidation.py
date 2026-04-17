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
    参数：
        current_close: 当前K线收盘价
        prev_high: 前一根K线最高价
        prev_low: 前一根K线最低价
    """
    return current_close < prev_high and current_close > prev_low

def calculate_kdj(highs, lows, closes, rsv_period=9, smooth=3):
    """
    计算KDJ指标
    返回两个数组：k_values, d_values, j_values
    每个数组长度与输入数据相同，前若干元素为None
    """
    n = len(closes)
    k_values = [None] * n
    d_values = [None] * n
    j_values = [None] * n
    
    if n < rsv_period:
        return k_values, d_values, j_values
    
    k_prev = 50  # 初始值使用50（中性值）
    d_prev = 50
    
    for i in range(rsv_period - 1, n):
        # 计算RSV
        period_high = max(highs[i - rsv_period + 1:i + 1])
        period_low = min(lows[i - rsv_period + 1:i + 1])
        
        if period_high == period_low:
            rsv = 50  # 无波动时中性值
        else:
            rsv = (closes[i] - period_low) / (period_high - period_low) * 100
        
        # 计算K值（平滑）
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
    
    # 筛选 USDT 本位永续合约
    swap_symbols = []
    for symbol, market in markets.items():
        if market.get('type') == 'swap' and symbol.endswith('/USDT:USDT'):
            swap_symbols.append(symbol)
    
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")
    
    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return
    
    # ========== 第二步：获取24h涨幅数据（用于排序和展示） ==========
    print("📡 正在获取所有合约的24h涨幅数据...")
    try:
        tickers = exchange.fetch_tickers()
        print(f"📊 共获取 {len(tickers)} 个交易对数据")
    except Exception as e:
        print(f"❌ 获取市场数据失败: {e}")
        return
    
    # 构建24h涨幅字典
    daily_gain_dict = {}
    for symbol, ticker in tickers.items():
        if '/USDT:USDT' in symbol and ticker.get('percentage') is not None:
            daily_gain_dict[symbol] = ticker['percentage']
    
    # ========== 第三步：获取4小时K线数据并分析 ==========
    print(f"⏳ 正在获取4小时K线数据（需要至少30根K线计算MA20和KDJ）...")
    result_list = []
    
    for i, symbol in enumerate(swap_symbols):
        try:
            # 获取足够多的4小时K线（需要至少30根计算MA20和KDJ，取40根确保足够）
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=40)
            if len(ohlcv_4h) < 30:
                continue
            
            # 提取收盘价序列用于计算均线
            closes = [kline[4] for kline in ohlcv_4h]
            
            # 计算移动平均线
            ma_values = calculate_moving_averages(closes, MA_PERIODS)
            
            # 条件1：均线多头排列
            if not is_bullish_arrangement(ma_values):
                continue
            
            # 条件2：当前收盘价 > MA5（价格在短期均线上方）
            # 注意：使用最近一根已收盘K线的价格
            current_close = ohlcv_4h[-1][4]
            if current_close <= ma_values[5]:
                continue
            
            # ========== 关键修正：确保有足够的K线用于震荡判断 ==========
            if len(ohlcv_4h) < 6:
                continue
            
            # 固定偏移量：从列表末尾往前取
            # ohlcv_4h[-5] = 上上上根
            # ohlcv_4h[-4] = 上上根
            # ohlcv_4h[-3] = 上根
            # ohlcv_4h[-2] = 不参与判断
            # ohlcv_4h[-1] = 当前K线（已收盘，用于价格比较）
            
            # 上上上根（索引-5）
            high_prev3 = ohlcv_4h[-5][2]
            low_prev3 = ohlcv_4h[-5][3]
            
            # 上上根（索引-4）
            close_prev2 = ohlcv_4h[-4][4]
            high_prev2 = ohlcv_4h[-4][2]
            low_prev2 = ohlcv_4h[-4][3]
            
            # 上根（索引-3）
            close_prev1 = ohlcv_4h[-3][4]
            high_prev1 = ohlcv_4h[-3][2]
            low_prev1 = ohlcv_4h[-3][3]
            
            # 判断上上根是否震荡（相对于上上上根）
            is_consolidation_prev2 = is_consolidation_kline(close_prev2, high_prev3, low_prev3)
            
            # 判断上根是否震荡（相对于上上根）
            is_consolidation_prev1 = is_consolidation_kline(close_prev1, high_prev2, low_prev2)
            
            if not (is_consolidation_prev2 and is_consolidation_prev1):
                continue
            
            # ========== 计算KDJ指标 ==========
            # 提取足够的高、低、收数据
            highs = [kline[2] for kline in ohlcv_4h]
            lows = [kline[3] for kline in ohlcv_4h]
            
            # 计算KDJ
            k_values, d_values, j_values = calculate_kdj(highs, lows, closes, KDJ_RSV_PERIOD, KDJ_SMOOTH)
            
            # 获取上上根（索引-4）和上根（索引-3）的J值
            idx_prev2 = len(j_values) - 5  # 上上根索引
            idx_prev1 = len(j_values) - 4  # 上根索引
            
            if idx_prev2 < 0 or idx_prev1 < 0 or j_values[idx_prev2] is None or j_values[idx_prev1] is None:
                continue
            
            j_prev2 = j_values[idx_prev2]
            j_prev1 = j_values[idx_prev1]
            
            # 条件3：上根的J值 > 上上根的J值（J值上升）
            if not (j_prev1 > j_prev2):
                continue
            
            # 所有条件满足，添加到结果列表
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
    
    # ========== 第四步：按24小时涨幅排序，取前十 ==========
    result_list.sort(key=lambda x: x['daily_gain'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第五步：生成推送消息 ==========
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
    
    # ========== 第六步：推送消息 ==========
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
