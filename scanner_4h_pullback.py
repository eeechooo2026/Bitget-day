import ccxt
import time
from datetime import datetime
import requests
import json

# ================== 配置区域 ==================
# WxPusher 配置（已自动填充）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10            # 推送前N名
TIMEFRAME_4H = '4h'        # 4小时K线周期
TIMEFRAME_1D = '1d'        # 日线K线周期
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

def main():
    beijing_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🚀 开始双周期突破回调扫描 - 北京时间 {beijing_time}")
    print(f"📈 策略逻辑：")
    print(f"   • 昨天日线收阳 + 收盘价 > 前天最高价（日线突破前高）")
    print(f"   • 上上根4小时K棒收阳 + 收盘价 > 上上上根最高价（4小时突破前高）")
    print(f"   • 上根4小时K棒收跌（回调确认）")
    print(f"📊 排序：按上上根K棒振幅从高到低")
    
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
    
    # ========== 第二步：获取日线数据判断突破前高 ==========
    print(f"⏳ 正在获取日线数据，判断昨天日线是否突破前天最高价...")
    daily_breakout_symbols = []
    ohlcv_4h_cache = {}
    
    for i, symbol in enumerate(swap_symbols):
        try:
            # 获取最近4根日线（大前天、前天、昨天、今天）
            ohlcv_daily = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1D, limit=4)
            if len(ohlcv_daily) < 4:
                continue
            
            # 前天数据（索引1）
            high_day_before = ohlcv_daily[1][2]   # 前天最高价
            close_day_before = ohlcv_daily[1][4]  # 前天收盘价
            
            # 昨天数据（索引2）
            open_yesterday = ohlcv_daily[2][1]    # 昨天开盘价
            close_yesterday = ohlcv_daily[2][4]   # 昨天收盘价
            
            # 条件1：昨天是否收阳
            is_bullish = close_yesterday > open_yesterday
            
            # 条件2：昨天收盘是否突破前天最高价
            is_breakout = close_yesterday > high_day_before
            
            if is_bullish and is_breakout:
                daily_breakout_symbols.append(symbol)
                print(f"✓ {symbol} 昨天日线收阳+突破前天最高{high_day_before:.4f}")
            
            if (i + 1) % 50 == 0:
                print(f"   进度: {i+1}/{len(swap_symbols)}")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 日线数据失败: {e}")
            time.sleep(0.5)
    
    print(f"✅ 日线筛选完成：共 {len(daily_breakout_symbols)} 个币种满足日线突破前高")
    
    if len(daily_breakout_symbols) == 0:
        print("❌ 未找到满足日线突破前高的币种")
        return
    
    # ========== 第三步：获取4小时K线数据 ==========
    print(f"⏳ 正在获取4小时K线数据...")
    
    for i, symbol in enumerate(daily_breakout_symbols):
        try:
            # 获取足够多的4小时K线（至少需要5根）
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=10)
            if len(ohlcv_4h) >= 5:
                ohlcv_4h_cache[symbol] = ohlcv_4h
            else:
                print(f"⚠️ {symbol} 4小时K线数据不足，跳过")
            
            if (i + 1) % 20 == 0:
                print(f"   进度: {i+1}/{len(daily_breakout_symbols)}")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 4小时K线数据失败: {e}")
            time.sleep(0.5)
    
    # ========== 第四步：分析4小时级别突破和回调 ==========
    result_list = []
    
    for symbol in daily_breakout_symbols:
        try:
            ohlcv = ohlcv_4h_cache.get(symbol)
            if not ohlcv or len(ohlcv) < 5:
                continue
            
            # 索引说明（按时间从旧到新）：
            # ohlcv[-5] = 更早的K线（用于判断上上根的突破）
            # ohlcv[-4] = 上上上根（提供突破参考高点）
            # ohlcv[-3] = 上上根（核心判断：是否收阳+突破前高+振幅）
            # ohlcv[-2] = 上根（判断是否收跌）
            # ohlcv[-1] = 当前K线（未完全确定，不参与判断）
            
            # 上上上根数据（索引-4）
            high_prev3 = ohlcv[-4][2]   # 上上上根最高价（突破参考点）
            
            # 上上根数据（索引-3）
            open_prev2 = ohlcv[-3][1]   # 上上根开盘价
            close_prev2 = ohlcv[-3][4]  # 上上根收盘价
            high_prev2 = ohlcv[-3][2]   # 上上根最高价
            low_prev2 = ohlcv[-3][3]    # 上上根最低价
            
            # 上根数据（索引-2）
            open_prev1 = ohlcv[-2][1]   # 上根开盘价
            close_prev1 = ohlcv[-2][4]  # 上根收盘价
            
            # 条件1：上上根是否收阳
            is_bullish_4h = close_prev2 > open_prev2
            
            # 条件2：上上根收盘是否突破上上上根最高价
            is_breakout_4h = close_prev2 > high_prev3
            
            # 条件3：上根是否收跌
            is_red = close_prev1 < open_prev1
            
            # 计算上上根振幅
            amplitude = (high_prev2 - low_prev2) / low_prev2 * 100
            
            if is_bullish_4h and is_breakout_4h and is_red:
                result_list.append({
                    'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                    'amplitude': round(amplitude, 2),
                    'close_prev2': round(close_prev2, 4),
                    'high_prev3': round(high_prev3, 4),
                    'open_prev1': round(open_prev1, 4),
                    'close_prev1': round(close_prev1, 4),
                })
                print(f"✓ {symbol} 上上根收阳+突破前高+{amplitude:.2f}%振幅，上根收跌")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 4小时K线时出错: {e}")
            continue
    
    # ========== 第五步：按上上根振幅排序，取前十 ==========
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第六步：生成推送消息 ==========
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 双周期突破回调扫描",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 昨天日线收阳 + 收盘价 > 前天最高价（日线突破）",
        f"   • 上上根4小时K棒收阳 + 收盘价 > 上上上根最高价（4小时突破）",
        f"   • 上根4小时K棒收跌（回调确认）",
        f"📊 排序：按上上根K棒振幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   上上根振幅: ±{item['amplitude']}%\n"
                f"   上上根突破前高: {item['high_prev3']} → {item['close_prev2']} 📈\n"
                f"   上根收跌: {item['open_prev1']} → {item['close_prev1']} 📉"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：日线+4小时双周期突破前高，上根回调提供入场机会")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 今日未找到符合条件的币种")
    
    message = "\n".join(msg_lines)
    
    print("\n" + "="*50)
    print(message)
    print("="*50)
    
    # ========== 第七步：推送消息 ==========
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
