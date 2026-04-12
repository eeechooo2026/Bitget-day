import ccxt
import time
from datetime import datetime
import requests
import json

# ================== 配置区域 ==================
# WxPusher 配置（已自动填充）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

TOP_VOLUME = 100           # 按日成交量取前N个合约
MIN_AMPLITUDE = 5.0        # 上上根4小时K棒最小振幅（百分比）
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
    print(f"🚀 开始4小时K线扫描（上上根振幅>{MIN_AMPLITUDE}% + 上一根收跌）- 北京时间 {beijing_time}")
    
    # 初始化 Bitget 合约接口
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    })
    
    # 1. 获取所有合约交易对
    print("📡 正在加载合约市场数据...")
    try:
        markets = exchange.load_markets()
    except Exception as e:
        print(f"❌ 加载市场数据失败: {e}")
        return
    
    # 筛选 USDT 本位永续合约
    swap_symbols = [
        symbol for symbol, market in markets.items()
        if market.get('type') == 'swap' and symbol.endswith('/USDT:USDT')
    ]
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")
    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    # 2. 按日成交量排序，取前 TOP_VOLUME 个
    print(f"⏳ 正在获取日成交量以筛选前{TOP_VOLUME}个合约...")
    volume_dict = {}
    scan_candidates = swap_symbols[:TOP_VOLUME*2]  # 多取一些备选
    for i, symbol in enumerate(scan_candidates):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=1)
            if len(ohlcv) > 0:
                volume_dict[symbol] = ohlcv[0][5]
            else:
                volume_dict[symbol] = 0
            if (i + 1) % 20 == 0:
                print(f"   进度: {i+1}/{len(scan_candidates)}")
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 成交量失败: {e}")
            volume_dict[symbol] = 0
    
    sorted_by_volume = sorted(volume_dict.items(), key=lambda x: x[1], reverse=True)
    top_volume_symbols = [sym for sym, vol in sorted_by_volume[:TOP_VOLUME] if vol > 0]
    print(f"✅ 按成交量筛选完成，将分析前 {len(top_volume_symbols)} 个")

    # 3. 分析每个币种的4小时K线形态
    result_list = []
    print(f"⏳ 正在分析4小时K线形态...")
    for symbol in top_volume_symbols:
        try:
            # 获取最近3根已收盘的4小时K线
            # 索引0: 上上根（最旧）, 索引1: 上一根, 索引2: 最新（还未收盘，但这里取的是已收盘的）
            # 实际上 limit=3 取到的是最近3根已收盘的K线
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=3)
            if len(ohlcv) < 3:
                continue
            
            # 上上根（索引0）- 计算振幅
            high_prev2 = ohlcv[0][2]   # 上上根最高价
            low_prev2 = ohlcv[0][3]    # 上上根最低价
            amplitude_prev2 = (high_prev2 - low_prev2) / low_prev2 * 100
            
            # 上一根（索引1）- 判断是否收跌
            open_prev1 = ohlcv[1][1]   # 上一根开盘价
            close_prev1 = ohlcv[1][4]  # 上一根收盘价
            is_red_prev1 = close_prev1 < open_prev1
            
            if amplitude_prev2 >= MIN_AMPLITUDE and is_red_prev1:
                result_list.append({
                    'symbol': symbol.replace('/USDT:USDT', ''),
                    'amplitude': round(amplitude_prev2, 2),
                    'high_prev2': round(high_prev2, 4),
                    'low_prev2': round(low_prev2, 4),
                    'close_prev1': round(close_prev1, 4),
                })
                print(f"✓ {symbol} 上上根振幅 {amplitude_prev2:.2f}%，上一根收跌")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            continue

    # 4. 按振幅排序，取前PUSH_TOP_N名
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]

    # 5. 生成推送消息
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 4小时K线扫描",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 条件：上上根4小时K棒振幅 > {MIN_AMPLITUDE}% 且 上一根4小时K棒收跌",
        f"📋 按上上根振幅排名 Top {len(top_results)}：",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   上上根振幅: ±{item['amplitude']}%\n"
                f"   上上根: {item['low_prev2']} → {item['high_prev2']}\n"
                f"   上一根收盘: {item['close_prev1']} 📉"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：上上根大振幅后，上一根回调，可能提供短线机会")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 今日未找到符合条件的币种")
    
    message = "\n".join(msg_lines)
    print("\n" + "="*50)
    print(message)
    print("="*50)
    
    # 6. 推送消息
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
