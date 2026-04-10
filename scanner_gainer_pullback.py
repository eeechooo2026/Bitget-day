import ccxt
import time
from datetime import datetime
import os
import requests

# ================== 配置区域 ==================
TOP_VOLUME = 100           # 按前天成交量取前N个合约
MIN_GAIN = 10.0            # 前天最小涨幅（百分比）
PUSH_TOP_N = 10            # 推送前N名
# =============================================

PUSH_WEBHOOK = os.environ.get('WEBHOOK_URL')

def send_push(message):
    """使用 WxPusher 推送消息到微信"""
    if not PUSH_WEBHOOK:
        print("⚠️ 未配置 WxPusher 凭证，仅打印日志。")
        return

    # 注意：此时 PUSH_WEBHOOK 环境变量里存放的是 appToken
    app_token = PUSH_WEBHOOK
    uid = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"  # 这里替换成你的 UID

    url = "https://wxpusher.zjiecode.com/api/send/message"

    params = {
        "appToken": app_token,
        "uid": uid,
        "content": message
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        result = response.json()
        
        if result.get("code") == 1000:
            print("✅ WxPusher 推送成功")
        else:
            print(f"❌ WxPusher 推送失败: {result}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")
        
def main():
    beijing_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🚀 开始扫描 - 北京时间 {beijing_time}")
    
    # 初始化 Bitget 合约接口
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',   # 永续合约
        }
    })
    
    # 1. 获取所有合约交易对
    print("📡 获取合约市场数据...")
    try:
        markets = exchange.load_markets()
        # 筛选 USDT 本位合约交易对
        swap_symbols = [
            symbol for symbol, market in markets.items()
            if market['type'] == 'swap' and symbol.endswith('/USDT')
        ]
        print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")
    except Exception as e:
        print(f"❌ 获取市场列表失败: {e}")
        return
    
    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对，请检查API配置")
        return
    
    # 2. 获取每个合约的前天成交量（用于排序筛选Top N）
    # 注意：需要先获取OHLCV才能得到成交量，这一步会比较耗时
    print(f"⏳ 正在获取各合约前天成交量（共{len(swap_symbols)}个）...")
    
    volume_dict = {}  # symbol -> 前天成交量
    ohlcv_cache = {}  # symbol -> ohlcv数据缓存（后面还会用到）
    
    for i, symbol in enumerate(swap_symbols):
        try:
            # 获取最近4根日线 (索引: -1今天, -2昨天, -3前天, -4大前天)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=4)
            if len(ohlcv) >= 3:
                # 前天成交量 = ohlcv[-3][5] (索引5是volume)
                volume_day_before = ohlcv[-3][5]
                volume_dict[symbol] = volume_day_before
                ohlcv_cache[symbol] = ohlcv
            else:
                volume_dict[symbol] = 0
            
            # 进度打印
            if (i + 1) % 50 == 0:
                print(f"   进度: {i+1}/{len(swap_symbols)}")
            
            time.sleep(0.2)  # 避免触发API限频
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 数据失败: {e}")
            volume_dict[symbol] = 0
            time.sleep(0.5)
    
    # 3. 按前天成交量排序，取前 TOP_VOLUME 个
    sorted_by_volume = sorted(volume_dict.items(), key=lambda x: x[1], reverse=True)
    top_volume_symbols = [sym for sym, vol in sorted_by_volume[:TOP_VOLUME] if vol > 0]
    print(f"✅ 按前天成交量筛选完成，取前 {len(top_volume_symbols)} 个")
    
    # 4. 计算这些币种的涨幅和回调
    result_list = []
    
    for symbol in top_volume_symbols:
        try:
            ohlcv = ohlcv_cache.get(symbol)
            if not ohlcv or len(ohlcv) < 4:
                # 如果没有缓存，重新获取
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=4)
                if len(ohlcv) < 4:
                    continue
            
            # 日线数据索引
            # [-1] = 今天（未完整）
            # [-2] = 昨天收盘
            # [-3] = 前天收盘
            # [-4] = 大前天收盘
            close_yesterday = ohlcv[-2][4]      # 昨天收盘价
            close_day_before = ohlcv[-3][4]     # 前天收盘价
            close_two_days_before = ohlcv[-4][4] # 大前天收盘价
            
            # 前天涨幅（相对于大前天）
            gain_day_before = (close_day_before - close_two_days_before) / close_two_days_before * 100
            
            # 判断昨天是否收跌
            is_red_yesterday = close_yesterday < close_day_before
            
            if gain_day_before >= MIN_GAIN and is_red_yesterday:
                result_list.append({
                    'symbol': symbol.replace('/USDT', ''),  # 去掉/USDT，显示更简洁
                    'gain': round(gain_day_before, 2),
                    'close_day_before': round(close_day_before, 4),
                    'close_yesterday': round(close_yesterday, 4),
                    'volume': volume_dict.get(symbol, 0)
                })
                print(f"✓ {symbol} 前天涨幅 {gain_day_before:.2f}%，昨日收跌")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            continue
    
    # 5. 按前天涨幅从高到低排序，取前 PUSH_TOP_N 个
    result_list.sort(key=lambda x: x['gain'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # 6. 生成推送消息
    current_date = datetime.now().strftime('%Y-%m-%d')
    msg_lines = [
        f"📊 **Bitget 合约涨幅回调扫描**",
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
        
        # 添加统计信息
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 今日未找到符合条件的币种")
    
    message = "\n".join(msg_lines)
    
    print("\n" + "="*50)
    print(message)
    print("="*50)
    
    # 7. 推送
    send_push(message)

if __name__ == "__main__":
    main()
