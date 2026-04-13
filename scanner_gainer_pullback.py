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
    print(f"📋 筛选逻辑：所有 USDT 本位永续合约")
    print(f"📈 条件1：前天收阳 + 前天收盘突破前高")
    print(f"📈 条件2：前天放量（>1.5倍5日均量）+ 昨天缩量（<0.8倍5日均量）")
    print(f"📈 条件3：回调不破20日均线（趋势确认）")
    print(f"📈 条件4：昨天收跌")
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
    
    # 打印前20个合约（用于调试）
    print(f"📊 合约示例（前20个）：")
    for i, sym in enumerate(swap_symbols[:20], 1):
        print(f"   {i}. {sym.replace('/USDT:USDT', '')}")
    
    # ========== 第二步：获取K线数据进行分析 ==========
    print(f"⏳ 正在遍历 {len(swap_symbols)} 个合约，获取K线数据...")
    
    result_list = []
    
    for i, symbol in enumerate(swap_symbols):
        try:
            # 获取足够多的K线数据（需要至少21根日线计算20日均线）
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=30)
            if len(ohlcv) < 21:  # 至少需要21根K线才能计算20日均线
                continue
            
            # 大前天数据（索引-4）
            high_two_days_before = ohlcv[-4][2]   # 大前天最高价
            
            # 前天数据（索引-3）
            open_day_before = ohlcv[-3][1]   # 前天开盘价
            close_day_before = ohlcv[-3][4]  # 前天收盘价
            high_day_before = ohlcv[-3][2]   # 前天最高价
            low_day_before = ohlcv[-3][3]    # 前天最低价
            volume_day_before = ohlcv[-3][5] # 前天成交量
            
            # 昨天数据（索引-2）
            open_yesterday = ohlcv[-2][1]    # 昨天开盘价
            close_yesterday = ohlcv[-2][4]   # 昨天收盘价
            low_yesterday = ohlcv[-2][3]     # 昨天最低价
            volume_yesterday = ohlcv[-2][5]  # 昨天成交量
            
            # 计算20日均线（取最近20根K线的收盘价平均值，不包括今天）
            ma20_values = [ohlcv[-i][4] for i in range(1, 21)]  # 最近20根K线收盘价
            ma20 = sum(ma20_values) / 20
            
            # 计算5日均量（取最近5根K线的成交量平均值，不包括今天）
            avg_volume_5 = sum([ohlcv[-i][5] for i in range(1, 6)]) / 5
            
            # 条件1：前天是否收阳
            is_bullish_day_before = close_day_before > open_day_before
            
            # 条件2：前天收盘是否突破大前天最高价
            is_breakout = close_day_before > high_two_days_before
            
            # 条件3：前天是否放量（>1.5倍5日均量）
            is_volume_surge = volume_day_before > avg_volume_5 * 1.5
            
            # 条件4：昨天是否缩量（<0.8倍5日均量）
            is_volume_shrink = volume_yesterday < avg_volume_5 * 0.8
            
            # 条件5：回调不破20日均线（昨天最低价 ≥ 20日均线 * 0.98，留2%误差）
            is_support = low_yesterday >= ma20 * 0.98
            
            # 条件6：昨天是否收跌
            is_red_yesterday = close_yesterday < open_yesterday
            
            # 计算前天振幅
            amplitude_day_before = (high_day_before - low_day_before) / low_day_before * 100
            
            # 判断是否符合所有条件
            if is_bullish_day_before and is_breakout and is_volume_surge and is_volume_shrink and is_support and is_red_yesterday:
                result_list.append({
                    'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                    'amplitude': round(amplitude_day_before, 2),
                    'ma20': round(ma20, 4),
                    'low_yesterday': round(low_yesterday, 4),
                    'volume_ratio_up': round(volume_day_before / avg_volume_5, 2),
                    'volume_ratio_down': round(volume_yesterday / avg_volume_5, 2),
                    'open_day_before': round(open_day_before, 4),
                    'close_day_before': round(close_day_before, 4),
                    'high_two_days_before': round(high_two_days_before, 4),
                    'open_yesterday': round(open_yesterday, 4),
                    'close_yesterday': round(close_yesterday, 4),
                })
                print(f"✓ {symbol} 前天突破前高+放量+{amplitude_day_before:.2f}%振幅，昨日缩量回调至MA20上方收跌")
            
            if (i + 1) % 20 == 0:
                print(f"   进度: {i+1}/{len(swap_symbols)}")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.5)
    
    # ========== 第三步：按前天振幅排序，取前十 ==========
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第四步：生成推送消息 ==========
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 合约扫描 - 所有USDT本位永续合约",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 筛选条件：",
        f"   • 前天收阳 + 收盘突破前高",
        f"   • 前天放量（>1.5倍均量）+ 昨天缩量（<0.8倍均量）",
        f"   • 回调不破20日均线 + 昨天收跌",
        f"📊 排序：按前天K棒振幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   前天振幅: ±{item['amplitude']}%\n"
                f"   前天: {item['open_day_before']} → {item['close_day_before']} 📈 (放量{item['volume_ratio_up']}倍)\n"
                f"   突破前高: {item['high_two_days_before']} → {item['close_day_before']}\n"
                f"   昨天: {item['open_yesterday']} → {item['close_yesterday']} 📉 (缩量{item['volume_ratio_down']}倍)\n"
                f"   支撑位: MA20={item['ma20']} > 昨日低点={item['low_yesterday']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：突破前高+放量上涨+缩量回调至均线支撑，具备二次启动潜力")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 今日未找到符合条件的币种")
    
    message = "\n".join(msg_lines)
    
    print("\n" + "="*50)
    print(message)
    print("="*50)
    
    # ========== 第五步：推送消息 ==========
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
