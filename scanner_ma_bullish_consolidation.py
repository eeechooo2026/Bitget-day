import ccxt
import time
from datetime import datetime, timezone, timedelta
import requests
import json

# ================== 配置区域 ==================
# WxPusher 配置（已自动填充）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10            # 推送前N名
TIMEFRAME_4H = '4h'        # 4小时K线周期
MA_PERIODS = [5, 10, 20]   # 均线周期
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

def calculate_total_volume(ohlcv, start_index, end_index):
    """
    计算指定K线区间内的总成交量（作为资金流入量的代理指标）
    参数：
        ohlcv: K线数据列表
        start_index: 起始索引（包含）
        end_index: 结束索引（包含）
    """
    total_volume = 0
    for i in range(start_index, end_index + 1):
        total_volume += ohlcv[i][5]  # 索引5是成交量
    return total_volume

def main():
    beijing_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🚀 开始均线多头+双K线震荡扫描 - 北京时间 {beijing_time}")
    print(f"📈 策略逻辑：")
    print(f"   • 4小时图均线多头排列（MA5 > MA10 > MA20，且收盘价 > MA5）")
    print(f"   • 上两根4小时K棒均处于震荡（收盘价落于前一根区间内）")
    print(f"📊 排序：按双K线期间总成交量（资金流入代理指标）从高到低")
    
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
    
    # ========== 第二步：获取24h涨幅数据（用于附加展示） ==========
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
    print(f"⏳ 正在获取4小时K线数据（需要至少20根K线计算MA20）...")
    result_list = []
    
    for i, symbol in enumerate(swap_symbols):
        try:
            # 获取足够多的4小时K线（需要至少20根计算MA20，取30根确保足够）
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=35)
            if len(ohlcv_4h) < 25:  # 至少需要25根（20根计算MA + 5根用于震荡判断）
                continue
            
            # 提取收盘价序列用于计算均线
            closes = [kline[4] for kline in ohlcv_4h]
            
            # 计算移动平均线
            ma_values = calculate_moving_averages(closes, MA_PERIODS)
            
            # 条件1：均线多头排列
            if not is_bullish_arrangement(ma_values):
                continue
            
            # 条件2：当前收盘价 > MA5（价格在短期均线上方）
            current_close = ohlcv_4h[-1][4]
            if current_close <= ma_values[5]:
                continue
            
            # 索引说明（按时间从旧到新）：
            # ohlcv[-6] = 更早的K线（可能用于计算）
            # ohlcv[-5] = 上上上根（供上上根判断震荡）
            # ohlcv[-4] = 上上根（需要判断它相对于上上上根的震荡）
            # ohlcv[-3] = 上根（需要判断它相对于上上根的震荡）
            # ohlcv[-2] = 当前K线的前一根（不参与判断）
            # ohlcv[-1] = 当前K线（未完全确定，仅用于价格判断）
            
            if len(ohlcv_4h) < 6:
                continue
            
            # 获取K线数据
            # 上上上根（索引-5）
            high_prev3 = ohlcv_4h[-5][2]   # 上上上根最高价
            low_prev3 = ohlcv_4h[-5][3]    # 上上上根最低价
            
            # 上上根（索引-4）
            close_prev2 = ohlcv_4h[-4][4]  # 上上根收盘价
            high_prev2 = ohlcv_4h[-4][2]   # 上上根最高价
            low_prev2 = ohlcv_4h[-4][3]    # 上上根最低价
            volume_prev2 = ohlcv_4h[-4][5] # 上上根成交量
            
            # 上根（索引-3）
            close_prev1 = ohlcv_4h[-3][4]  # 上根收盘价
            high_prev1 = ohlcv_4h[-3][2]   # 上根最高价
            low_prev1 = ohlcv_4h[-3][3]    # 上根最低价
            volume_prev1 = ohlcv_4h[-3][5] # 上根成交量
            
            # 判断上上根是否震荡（相对于上上上根）
            is_consolidation_prev2 = is_consolidation_kline(close_prev2, high_prev3, low_prev3)
            
            # 判断上根是否震荡（相对于上上根）
            is_consolidation_prev1 = is_consolidation_kline(close_prev1, high_prev2, low_prev2)
            
            if not (is_consolidation_prev2 and is_consolidation_prev1):
                continue
            
            # 计算双K线期间的总成交量（作为资金流入量的代理指标）
            total_volume = volume_prev2 + volume_prev1
            
            # 所有条件满足，添加到结果列表
            daily_gain = daily_gain_dict.get(symbol, 0)
            
            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                'total_volume': round(total_volume / 1000000, 2),  # 转换为百万单位
                'daily_gain': round(daily_gain, 2),
                'ma5': round(ma_values[5], 4),
                'ma10': round(ma_values[10], 4),
                'ma20': round(ma_values[20], 4),
                'current_close': round(current_close, 4),
                'close_prev2': round(close_prev2, 4),
                'high_prev3': round(high_prev3, 4),
                'low_prev3': round(low_prev3, 4),
                'close_prev1': round(close_prev1, 4),
                'high_prev2': round(high_prev2, 4),
                'low_prev2': round(low_prev2, 4),
                'volume_prev2': round(volume_prev2 / 1000000, 2),
                'volume_prev1': round(volume_prev1 / 1000000, 2),
            })
            print(f"✓ {symbol} 均线多头+双K线震荡，双K线总成交量{total_volume/1000000:.2f}M，24h涨幅{daily_gain:.2f}%")
            
            if (i + 1) % 50 == 0:
                print(f"   进度: {i+1}/{len(swap_symbols)}")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)
    
    # ========== 第四步：按总成交量排序，取前十 ==========
    result_list.sort(key=lambda x: x['total_volume'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第五步：生成推送消息 ==========
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 均线多头+双K线震荡扫描",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 4小时图均线多头排列（MA5 > MA10 > MA20，价格 > MA5）",
        f"   • 上两根4小时K棒均处于震荡（收盘价落于前一根区间内）",
        f"📊 排序：按双K线期间总成交量（资金流入代理指标）从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   双K线总成交量: {item['total_volume']}M USDT\n"
                f"   24h涨幅: +{item['daily_gain']}%\n"
                f"   均线: MA5={item['ma5']} > MA10={item['ma10']} > MA20={item['ma20']}\n"
                f"   当前价: {item['current_close']} > MA5 ✅\n"
                f"   上上根震荡: 收盘{item['close_prev2']} 落于前根区间[{item['low_prev3']}-{item['high_prev3']}]（成交量{item['volume_prev2']}M）\n"
                f"   上根震荡: 收盘{item['close_prev1']} 落于前根区间[{item['low_prev2']}-{item['high_prev2']}]（成交量{item['volume_prev1']}M）"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：均线多头排列+双K线区间内震荡+放量，蓄势待涨")
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
