import ccxt
import time
from datetime import datetime
import requests
import json

# ================== 配置区域 ==================
# WxPusher 配置（已自动填充）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

TOP_GAINERS = 50           # 按24h涨幅取前N个合约
PUSH_TOP_N = 10            # 推送前N名
TIMEFRAME = '4h'           # K线周期
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
    print(f"🚀 开始4小时K线扫描 - 北京时间 {beijing_time}")
    print(f"📋 筛选范围：24h涨幅榜前{TOP_GAINERS}名")
    print(f"📈 条件：上上根收阳 + 上上根收盘突破前高 + 上根收跌")
    print(f"📊 排序：按上上根K棒振幅从高到低")
    
    # 初始化 Bitget 合约接口
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',  # 永续合约
        },
    })
    
    # ========== 第一步：获取24h涨幅榜前50名 ==========
    print("📡 正在获取所有合约的24h涨幅数据...")
    try:
        tickers = exchange.fetch_tickers()
        print(f"📊 共获取 {len(tickers)} 个交易对数据")
    except Exception as e:
        print(f"❌ 获取市场数据失败: {e}")
        return
    
    # 筛选 USDT 本位永续合约
    usdt_swap_tickers = {}
    for symbol, ticker in tickers.items():
        if '/USDT:USDT' in symbol and ticker.get('percentage') is not None:
            usdt_swap_tickers[symbol] = ticker
    
    # 按24h涨跌幅排序，取前 TOP_GAINERS 名
    sorted_by_gain = sorted(
        usdt_swap_tickers.items(),
        key=lambda x: x[1]['percentage'],
        reverse=True
    )
    top_gainer_symbols = [sym for sym, _ in sorted_by_gain[:TOP_GAINERS]]
    
    print(f"✅ 涨幅榜筛选完成，取前 {len(top_gainer_symbols)} 个")
    
    # 打印涨幅榜前10名（用于调试）
    print(f"📊 24h涨幅榜前10名：")
    for i, (sym, ticker) in enumerate(sorted_by_gain[:10], 1):
        gain = ticker['percentage']
        print(f"   {i}. {sym.replace('/USDT:USDT', '')} 24h涨幅: {gain:.2f}%")
    
    # ========== 第二步：获取K线数据进行分析 ==========
    print(f"⏳ 正在获取涨幅榜前{TOP_GAINERS}名币种的4小时K线数据...")
    ohlcv_cache = {}
    
    for i, symbol in enumerate(top_gainer_symbols):
        try:
            # 需要至少4根4小时K线（上上上根、上上根、上根、当前根）
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=5)
            if len(ohlcv) >= 4:
                ohlcv_cache[symbol] = ohlcv
            else:
                print(f"⚠️ {symbol} K线数据不足，跳过")
            
            if (i + 1) % 10 == 0:
                print(f"   进度: {i+1}/{len(top_gainer_symbols)}")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 获取 {symbol} K线数据失败: {e}")
            time.sleep(0.5)
    
    # ========== 第三步：分析符合条件的币种 ==========
    result_list = []
    
    for symbol in top_gainer_symbols:
        try:
            ohlcv = ohlcv_cache.get(symbol)
            if not ohlcv or len(ohlcv) < 4:
                continue
            
            # 索引说明（按时间从旧到新）：
            # ohlcv[0] = 上上上根K棒（最旧）
            # ohlcv[1] = 上上根K棒
            # ohlcv[2] = 上根K棒
            # ohlcv[3] = 当前K棒（可能未收盘，不参与判断）
            
            # 上上上根数据（索引0）
            high_prev3 = ohlcv[0][2]   # 上上上根最高价
            
            # 上上根数据（索引1）
            open_prev2 = ohlcv[1][1]   # 上上根开盘价
            close_prev2 = ohlcv[1][4]  # 上上根收盘价
            high_prev2 = ohlcv[1][2]   # 上上根最高价
            low_prev2 = ohlcv[1][3]    # 上上根最低价
            
            # 上根数据（索引2）
            open_prev1 = ohlcv[2][1]   # 上根开盘价
            close_prev1 = ohlcv[2][4]  # 上根收盘价
            
            # 条件1：上上根是否收阳
            is_bullish_prev2 = close_prev2 > open_prev2
            
            # 条件2：上上根收盘是否突破上上上根最高价
            is_breakout = close_prev2 > high_prev3
            
            # 条件3：上根是否收跌
            is_red_prev1 = close_prev1 < open_prev1
            
            # 计算上上根振幅
            amplitude_prev2 = (high_prev2 - low_prev2) / low_prev2 * 100
            
            if is_bullish_prev2 and is_breakout and is_red_prev1:
                # 获取该币种的24h涨幅（用于显示）
                ticker = usdt_swap_tickers.get(symbol, {})
                daily_gain = ticker.get('percentage', 0)
                
                result_list.append({
                    'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                    'amplitude': round(amplitude_prev2, 2),
                    'daily_gain': round(daily_gain, 2),
                    'open_prev2': round(open_prev2, 4),
                    'close_prev2': round(close_prev2, 4),
                    'high_prev3': round(high_prev3, 4),
                    'open_prev1': round(open_prev1, 4),
                    'close_prev1': round(close_prev1, 4),
                })
                print(f"✓ {symbol} 上上根收阳+突破前高+{amplitude_prev2:.2f}%振幅，上根收跌")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            continue
    
    # ========== 第四步：按上上根振幅排序，取前十 ==========
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第五步：生成推送消息 ==========
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 4小时K线扫描",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 筛选条件：",
        f"   • 上上根4小时K棒收阳 + 收盘突破前高",
        f"   • 上根4小时K棒收跌",
        f"📋 筛选范围：24h涨幅榜前{TOP_GAINERS}名",
        f"📊 排序：按上上根K棒振幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   24h涨幅: +{item['daily_gain']}%\n"
                f"   上上根振幅: ±{item['amplitude']}%\n"
                f"   上上根: {item['open_prev2']} → {item['close_prev2']} 📈\n"
                f"   突破前高: {item['high_prev3']} → {item['close_prev2']}\n"
                f"   上根: {item['open_prev1']} → {item['close_prev1']} 📉"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：上上根突破前高后上涨，上根回调，关注上根低点支撑")
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
