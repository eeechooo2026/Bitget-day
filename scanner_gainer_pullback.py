import ccxt
import time
from datetime import datetime
import requests
import json

# ================== 配置区域 ==================
# WxPusher 配置（已自动填充）
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

TOP_VOLUME = 200           # 成交量粗筛：取前200个
TOP_GAINERS = 50           # 涨幅精筛：取前50个
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
    print(f"🚀 开始扫描（前天振幅>{MIN_AMPLITUDE}% + 前天收盘突破前高 + 昨天收跌）- 北京时间 {beijing_time}")
    
    # 初始化 Bitget 合约接口
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
        },
    })
    
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
    
    if not swap_symbols:
        print("⚠️ 未找到 /USDT:USDT 格式，尝试备选筛选...")
        for symbol, market in markets.items():
            if market.get('type') == 'swap' and 'USDT' in symbol:
                swap_symbols.append(symbol)
    
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位合约")
    
    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return
    
    # ========== 第一步：按成交量粗筛 ==========
    print(f"⏳ 第一步：按日成交量筛选前{TOP_VOLUME}个合约...")
    volume_dict = {}
    ohlcv_cache = {}
    scan_candidates = swap_symbols[:TOP_VOLUME * 2]  # 多取一些备选
    
    for i, symbol in enumerate(scan_candidates):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=6)
            if len(ohlcv) >= 5:
                volume = ohlcv[-3][5]  # 前天成交量
                volume_dict[symbol] = volume
                ohlcv_cache[symbol] = ohlcv
            else:
                volume_dict[symbol] = 0
            
            if (i + 1) % 20 == 0:
                print(f"   进度: {i+1}/{len(scan_candidates)}")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 成交量失败: {e}")
            volume_dict[symbol] = 0
            time.sleep(0.5)
    
    sorted_by_volume = sorted(volume_dict.items(), key=lambda x: x[1], reverse=True)
    top_volume_symbols = [sym for sym, vol in sorted_by_volume[:TOP_VOLUME] if vol > 0]
    print(f"✅ 成交量粗筛完成，取前 {len(top_volume_symbols)} 个")
    
    # ========== 第二步：按前天涨幅精筛 ==========
    print(f"⏳ 第二步：从前{TOP_VOLUME}个中按前天涨幅取前{TOP_GAINERS}名...")
    gain_dict = {}
    
    for symbol in top_volume_symbols:
        try:
            ohlcv = ohlcv_cache.get(symbol)
            if not ohlcv or len(ohlcv) < 5:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=6)
                if len(ohlcv) < 5:
                    gain_dict[symbol] = -999
                    continue
                ohlcv_cache[symbol] = ohlcv
            
            close_day_before = ohlcv[-3][4]      # 前天收盘价
            close_two_days_before = ohlcv[-4][4] # 大前天收盘价
            gain = (close_day_before - close_two_days_before) / close_two_days_before * 100
            gain_dict[symbol] = gain
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 涨幅失败: {e}")
            gain_dict[symbol] = -999
    
    sorted_by_gain = sorted(gain_dict.items(), key=lambda x: x[1], reverse=True)
    top_gainer_symbols = [sym for sym, gain in sorted_by_gain[:TOP_GAINERS] if gain > -999]
    print(f"✅ 涨幅精筛完成，将分析前 {len(top_gainer_symbols)} 个涨幅榜币种")
    
    # ========== 第三步：分析符合条件的币种 ==========
    result_list = []
    
    for symbol in top_gainer_symbols:
        try:
            ohlcv = ohlcv_cache.get(symbol)
            if not ohlcv or len(ohlcv) < 6:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=6)
                if len(ohlcv) < 6:
                    continue
            
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
                result_list.append({
                    'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                    'amplitude': round(amplitude_day_before, 2),
                    'close_day_before': round(close_day_before, 4),
                    'high_two_days_before': round(high_two_days_before, 4),
                    'close_yesterday': round(close_yesterday, 4),
                })
                print(f"✓ {symbol} 前天振幅{amplitude_day_before:.2f}%，突破前高，昨日收跌")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            continue
    
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 生成推送消息 ==========
    current_date = datetime.now().strftime('%Y-%m-%d')
    msg_lines = [
        f"📊 Bitget 合约扫描 - 振幅突破+回调版",
        f"🕘 时间：{current_date} 09:15（北京时间）",
        f"📈 条件：前天振幅>{MIN_AMPLITUDE}% + 前天收盘突破前高 + 昨日收跌",
        f"📋 筛选范围：前天涨幅榜前{TOP_GAINERS}名",
        f"📋 按前天振幅排名 Top {len(top_results)}：",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
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
    
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
