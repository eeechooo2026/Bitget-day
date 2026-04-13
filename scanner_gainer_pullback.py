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
MIN_AMPLITUDE = 10.0       # 前天最小振幅（百分比）
PUSH_TOP_N = 10            # 推送前N名
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
    print(f"🚀 开始扫描 - 北京时间 {beijing_time}")
    print(f"📋 筛选范围：24h涨幅榜前{TOP_GAINERS}名")
    print(f"📈 条件：前天振幅>{MIN_AMPLITUDE}% + 前天收盘突破前高 + 昨日收跌")
    
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
    
    # 打印涨幅榜前10名
    print(f"📊 24h涨幅榜前10名：")
    for i, (sym, ticker) in enumerate(sorted_by_gain[:10], 1):
        gain = ticker['percentage']
        print(f"   {i}. {sym.replace('/USDT:USDT', '')} 24h涨幅: {gain:.2f}%")
    
    # ========== 第二步：获取K线数据进行分析 ==========
    print(f"⏳ 正在获取涨幅榜前{TOP_GAINERS}名币种的K线数据...")
    ohlcv_cache = {}
    
    for i, symbol in enumerate(top_gainer_symbols):
        try:
            # 获取6根日线数据（用于分析前天、大前天、昨天）
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=6)
            if len(ohlcv) >= 6:
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
            if not ohlcv or len(ohlcv) < 6:
                continue
            
            # 索引说明：
            # [-1] = 今天（未完整）
            # [-2] = 昨天
            # [-3] = 前天
            # [-4] = 大前天
            
            # 大前天数据（索引-4）
            high_two_days_before = ohlcv[-4][2]   # 大前天最高价
            
            # 前天数据（索引-3）
            high_day_before = ohlcv[-3][2]   # 前天最高价
            low_day_before = ohlcv[-3][3]    # 前天最低价
            close_day_before = ohlcv[-3][4]  # 前天收盘价
            
            # 昨天数据（索引-2）
            open_yesterday = ohlcv[-2][1]    # 昨天开盘价
            close_yesterday = ohlcv[-2][4]   # 昨天收盘价
            
            # 计算前天振幅
            amplitude_day_before = (high_day_before - low_day_before) / low_day_before * 100
            
            # 条件1：前天振幅 > MIN_AMPLITUDE
            condition_amplitude = amplitude_day_before >= MIN_AMPLITUDE
            
            # 条件2：前天收盘 > 大前天最高（突破前高）
            condition_breakout = close_day_before > high_two_days_before
            
            # 条件3：昨天收跌
            condition_red = close_yesterday < open_yesterday
            
            if condition_amplitude and condition_breakout and condition_red:
                # 获取该币种的24h涨幅（用于显示）
                ticker = usdt_swap_tickers.get(symbol, {})
                daily_gain = ticker.get('percentage', 0)
                
                result_list.append({
                    'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                    'amplitude': round(amplitude_day_before, 2),
                    'daily_gain': round(daily_gain, 2),
                    'close_day_before': round(close_day_before, 4),
                    'high_two_days_before': round(high_two_days_before, 4),
                    'close_yesterday': round(close_yesterday, 4),
                })
                print(f"✓ {symbol} 前天振幅{amplitude_day_before:.2f}%，突破前高，昨日收跌")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            continue
    
    # 按前天振幅排序，取前 PUSH_TOP_N 名
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 生成推送消息 ==========
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 合约扫描 - 振幅突破+回调版",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 条件：前天振幅 > {MIN_AMPLITUDE}% + 前天收盘突破前高 + 昨日收跌",
        f"📋 筛选范围：24h涨幅榜前{TOP_GAINERS}名",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 按前天振幅排名 Top {len(top_results)}：")
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   24h涨幅: +{item['daily_gain']}%\n"
                f"   前天振幅: ±{item['amplitude']}%\n"
                f"   前天收盘: {item['close_day_before']}\n"
                f"   突破前高: {item['high_two_days_before']} → 被突破\n"
                f"   昨天收盘: {item['close_yesterday']} 📉"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：前天大振幅突破前高，昨日回调，可能提供二次入场机会")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 今日未找到符合条件的币种")
    
    message = "\n".join(msg_lines)
    
    print("\n" + "="*50)
    print(message)
    print("="*50)
    
    # ========== 第四步：推送消息 ==========
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
