import ccxt
import time
from datetime import datetime
import requests
import json

# ================== 配置区域 ==================
# WxPusher 配置（已自动填充）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

TOP_GAINERS = 50           # 按前天涨幅取前N个合约
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
    print(f"📋 筛选逻辑：遍历所有合约 → 计算前天涨幅 → 取前{TOP_GAINERS}名")
    print(f"📈 条件：前天涨幅前{TOP_GAINERS}名 + 昨天收跌")
    print(f"📊 排序：按前天K棒振幅从高到低")
    
    # 初始化 Bitget 合约接口
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',  # 永续合约
        },
    })
    
    # ========== 第一步：获取所有合约 ==========
    print("📡 正在加载合约市场数据...")
    try:
        markets = exchange.load_markets()
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
    
    # ========== 第二步：遍历计算前天涨幅 ==========
    print(f"⏳ 正在遍历 {len(swap_symbols)} 个合约，计算前天涨幅...")
    gain_dict = {}      # 存储前天涨幅
    amplitude_dict = {} # 存储前天振幅
    close_yesterday_dict = {} # 存储昨天收盘价
    open_yesterday_dict = {}  # 存储昨天开盘价
    ohlcv_cache = {}
    
    for i, symbol in enumerate(swap_symbols):
        try:
            # 获取6根日线数据（需要大前天、前天、昨天的数据）
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=6)
            if len(ohlcv) >= 6:
                # 前天数据（索引-3）
                close_day_before = ohlcv[-3][4]      # 前天收盘价
                close_two_days_before = ohlcv[-4][4] # 大前天收盘价
                high_day_before = ohlcv[-3][2]       # 前天最高价
                low_day_before = ohlcv[-3][3]        # 前天最低价
                
                # 昨天数据（索引-2）
                open_yesterday = ohlcv[-2][1]        # 昨天开盘价
                close_yesterday = ohlcv[-2][4]       # 昨天收盘价
                
                # 计算前天涨幅
                gain = (close_day_before - close_two_days_before) / close_two_days_before * 100
                gain_dict[symbol] = gain
                
                # 计算前天振幅
                amplitude = (high_day_before - low_day_before) / low_day_before * 100
                amplitude_dict[symbol] = amplitude
                
                # 存储昨天数据
                open_yesterday_dict[symbol] = open_yesterday
                close_yesterday_dict[symbol] = close_yesterday
                
                ohlcv_cache[symbol] = ohlcv
            else:
                gain_dict[symbol] = -999
                amplitude_dict[symbol] = 0
            
            if (i + 1) % 50 == 0:
                print(f"   进度: {i+1}/{len(swap_symbols)}")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ {symbol} 获取失败: {e}")
            gain_dict[symbol] = -999
            amplitude_dict[symbol] = 0
            time.sleep(0.5)
    
    # ========== 第三步：按前天涨幅排序，取前 TOP_GAINERS 名 ==========
    sorted_by_gain = sorted(gain_dict.items(), key=lambda x: x[1], reverse=True)
    top_gainer_symbols = [sym for sym, gain in sorted_by_gain[:TOP_GAINERS] if gain > -999]
    
    print(f"✅ 前天涨幅榜筛选完成，取前 {len(top_gainer_symbols)} 名")
    print(f"📊 前天涨幅榜前10名：")
    for i, (sym, gain) in enumerate(sorted_by_gain[:10], 1):
        print(f"   {i}. {sym.replace('/USDT:USDT', '')} 前天涨幅: {gain:.2f}%")
    
    # ========== 第四步：筛选昨天收跌的币种 ==========
    result_list = []
    
    for symbol in top_gainer_symbols:
        open_yest = open_yesterday_dict.get(symbol)
        close_yest = close_yesterday_dict.get(symbol)
        
        if open_yest is None or close_yest is None:
            continue
        
        # 判断昨天是否收跌
        is_red = close_yest < open_yest
        
        if is_red:
            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                'gain': round(gain_dict[symbol], 2),
                'amplitude': round(amplitude_dict[symbol], 2),
                'open_yest': round(open_yest, 4),
                'close_yest': round(close_yest, 4),
            })
            print(f"✓ {symbol} 前天涨幅{gain_dict[symbol]:.2f}%，振幅{amplitude_dict[symbol]:.2f}%，昨日收跌")
    
    # ========== 第五步：按前天振幅排序，取前 PUSH_TOP_N 名 ==========
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第六步：生成推送消息 ==========
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 合约扫描 - 前天涨幅榜前{TOP_GAINERS}名 + 昨日收跌",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 排序：按前天K棒振幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名：")
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   前天涨幅: +{item['gain']}%\n"
                f"   前天振幅: ±{item['amplitude']}%\n"
                f"   昨天: {item['open_yest']} → {item['close_yest']} 📉"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：前天强势上涨，昨日回调，可关注后续走势")
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
