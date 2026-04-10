import ccxt
import time
from datetime import datetime
import requests
import json

# ================== 配置区域 ==================
# ⚠️ 请替换成你自己的 WxPusher 信息
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"  # 替换成你的 appToken
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"        # 替换成你的 UID

TOP_VOLUME = 100           # 按前天成交量取前N个合约
MIN_GAIN = 10.0            # 前天最小涨幅（百分比）
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
    
    # ========== 初始化 Bitget 接口（修复版）==========
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',  # 永续合约
        },
    })
    
    print("📡 正在加载合约市场数据...")
    try:
        # 加载所有市场数据
        markets = exchange.load_markets()
        print(f"📊 共加载 {len(markets)} 个交易对")
    except Exception as e:
        print(f"❌ 加载市场数据失败: {e}")
        return
    
    # 筛选 USDT 本位永续合约
    # Bitget 合约格式: BTC/USDT:USDT
    swap_symbols = []
    for symbol, market in markets.items():
        if market.get('type') == 'swap' and symbol.endswith('/USDT:USDT'):
            swap_symbols.append(symbol)
    
    # 如果没有找到，尝试备选方案
    if not swap_symbols:
        print("⚠️ 未找到 /USDT:USDT 格式，尝试备选筛选...")
        for symbol, market in markets.items():
            if market.get('type') == 'swap' and 'USDT' in symbol:
                swap_symbols.append(symbol)
    
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")
    
    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        print("📋 前10个市场类型示例:")
        for i, sym in enumerate(list(markets.keys())[:10]):
            print(f"   {sym}: type={markets[sym].get('type')}")
        return
    
    # 可选：限制扫描数量，避免超时（取前 TOP_VOLUME 个）
    scan_symbols = swap_symbols[:TOP_VOLUME]
    print(f"📋 本次将扫描前 {len(scan_symbols)} 个合约")
    
    # ========== 获取成交量数据 ==========
    print("⏳ 正在获取各合约前天成交量...")
    volume_dict = {}
    ohlcv_cache = {}
    
    for i, symbol in enumerate(scan_symbols):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=4)
            if len(ohlcv) >= 3:
                volume_day_before = ohlcv[-3][5]
                volume_dict[symbol] = volume_day_before
                ohlcv_cache[symbol] = ohlcv
            else:
                volume_dict[symbol] = 0
            
            if (i + 1) % 20 == 0:
                print(f"   进度: {i+1}/{len(scan_symbols)}")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 数据失败: {e}")
            volume_dict[symbol] = 0
            time.sleep(0.5)
    
    # 按成交量排序，取前 TOP_VOLUME 个
    sorted_by_volume = sorted(volume_dict.items(), key=lambda x: x[1], reverse=True)
    top_volume_symbols = [sym for sym, vol in sorted_by_volume[:TOP_VOLUME] if vol > 0]
    print(f"✅ 按成交量筛选完成，取前 {len(top_volume_symbols)} 个")
    
    # ========== 分析涨幅和回调 ==========
    result_list = []
    
    for symbol in top_volume_symbols:
        try:
            ohlcv = ohlcv_cache.get(symbol)
            if not ohlcv or len(ohlcv) < 4:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=4)
                if len(ohlcv) < 4:
                    continue
            
            close_yesterday = ohlcv[-2][4]
            close_day_before = ohlcv[-3][4]
            close_two_days_before = ohlcv[-4][4]
            
            gain_day_before = (close_day_before - close_two_days_before) / close_two_days_before * 100
            is_red_yesterday = close_yesterday < close_day_before
            
            if gain_day_before >= MIN_GAIN and is_red_yesterday:
                result_list.append({
                    'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                    'gain': round(gain_day_before, 2),
                    'close_day_before': round(close_day_before, 4),
                    'close_yesterday': round(close_yesterday, 4),
                })
                print(f"✓ {symbol} 前天涨幅 {gain_day_before:.2f}%，昨日收跌")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            continue
    
    # ========== 排序并取前十 ==========
    result_list.sort(key=lambda x: x['gain'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 生成推送消息 ==========
    current_date = datetime.now().strftime('%Y-%m-%d')
    msg_lines = [
        f"📊 Bitget 合约涨幅回调扫描",
        f"🕘 时间：{current_date} 09:00（北京时间）",
        f"📈 条件：前天涨幅 > {MIN_GAIN}% 且 昨日收跌",
        f"📋 按前天涨幅排名 Top {len(top_results)}：",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   前天涨幅: +{item['gain']}%\n"
                f"   前天收盘: {item['close_day_before']}\n"
                f"   昨天收盘: {item['close_yesterday']} 📉"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 今日未找到符合条件的币种")
    
    message = "\n".join(msg_lines)
    
    print("\n" + "="*50)
    print(message)
    print("="*50)
    
    # ========== 推送 ==========
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
