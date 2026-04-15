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
TIMEFRAME_1D = '1d'        # 日线K线周期
TIMEFRAME_4H = '4h'        # 4小时K线周期
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

def get_beijing_time_from_utc_kline(ohlcv_time):
    """
    将UTC时间的K线时间戳转换为北京时间，返回时间段描述
    """
    dt = datetime.fromtimestamp(ohlcv_time / 1000, tz=timezone.utc)
    beijing_dt = dt + timedelta(hours=8)
    return beijing_dt

def get_4h_period_label(beijing_hour):
    """
    根据北京时间的小时数，返回4小时K线的时间段标签
    4小时K线时段：00:00-03:00, 04:00-07:00, 08:00-11:00, 12:00-15:00, 16:00-19:00, 20:00-23:00
    """
    if 0 <= beijing_hour <= 3:
        return "00:00-03:00"
    elif 4 <= beijing_hour <= 7:
        return "04:00-07:00"
    elif 8 <= beijing_hour <= 11:
        return "08:00-11:00"
    elif 12 <= beijing_hour <= 15:
        return "12:00-15:00"
    elif 16 <= beijing_hour <= 19:
        return "16:00-19:00"
    else:
        return "20:00-23:00"

def main():
    beijing_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🚀 开始日线扫描 - 北京时间 {beijing_time}")
    print(f"📈 策略逻辑：")
    print(f"   • 昨天日线收阳 + 收盘价 > 前天最高价（日线突破前高）")
    print(f"   • 04:00-07:00四小时K棒震荡：收盘价 < 00:00-03:00四小时K棒最高价")
    print(f"📊 排序：按昨日日线振幅从高到低")
    
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
    print(f"⏳ 正在获取日线数据...")
    daily_data_cache = {}
    
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
            high_yesterday = ohlcv_daily[2][2]    # 昨天最高价
            low_yesterday = ohlcv_daily[2][3]     # 昨天最低价
            
            # 条件1：昨天是否收阳
            is_bullish = close_yesterday > open_yesterday
            
            # 条件2：昨天收盘是否突破前天最高价
            is_breakout = close_yesterday > high_day_before
            
            if is_bullish and is_breakout:
                # 计算昨日日线振幅
                amplitude = (high_yesterday - low_yesterday) / low_yesterday * 100
                
                daily_data_cache[symbol] = {
                    'high_day_before': high_day_before,
                    'open_yesterday': open_yesterday,
                    'close_yesterday': close_yesterday,
                    'high_yesterday': high_yesterday,
                    'low_yesterday': low_yesterday,
                    'amplitude': amplitude,
                }
                print(f"✓ {symbol} 昨天日线收阳+突破前天最高{high_day_before:.4f}，振幅{amplitude:.2f}%")
            
            if (i + 1) % 50 == 0:
                print(f"   进度: {i+1}/{len(swap_symbols)}")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 日线数据失败: {e}")
            time.sleep(0.5)
    
    print(f"✅ 日线筛选完成：共 {len(daily_data_cache)} 个币种满足日线突破前高")
    
    if len(daily_data_cache) == 0:
        print("❌ 未找到满足日线突破前高的币种")
        return
    
    # ========== 第三步：获取4小时K线数据，判断04:00-07:00时段是否震荡 ==========
    print(f"⏳ 正在获取4小时K线数据，判断04:00-07:00时段震荡...")
    result_list = []
    
    for symbol, daily_data in daily_data_cache.items():
        try:
            # 获取足够多的4小时K线（至少需要覆盖最近几天的数据）
            ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_4H, limit=30)
            if len(ohlcv_4h) < 12:
                print(f"⚠️ {symbol} 4小时K线数据不足，跳过")
                continue
            
            # 遍历4小时K线，找到昨天对应的00:00-03:00和04:00-07:00时段
            # 注意：我们需要的是昨天的这两个时段
            target_00_03_high = None
            target_04_07_close = None
            
            for kline in ohlcv_4h:
                # 获取K线时间（UTC），转换为北京时间
                kline_time = kline[0]  # 毫秒时间戳
                beijing_dt = get_beijing_time_from_utc_kline(kline_time)
                beijing_hour = beijing_dt.hour
                kline_date = beijing_dt.date()
                
                # 获取昨天的日期
                yesterday_date = (datetime.now() - timedelta(days=1)).date()
                
                # 只处理昨天的K线
                if kline_date != yesterday_date:
                    continue
                
                period = get_4h_period_label(beijing_hour)
                
                if period == "00:00-03:00":
                    target_00_03_high = kline[2]  # 最高价
                elif period == "04:00-07:00":
                    target_04_07_close = kline[4]  # 收盘价
            
            # 判断震荡条件：04:00-07:00收盘价 < 00:00-03:00最高价
            if target_00_03_high is not None and target_04_07_close is not None:
                is_consolidation = target_04_07_close < target_00_03_high
                
                if is_consolidation:
                    result_list.append({
                        'symbol': symbol.replace('/USDT:USDT', '').replace('/USDT', ''),
                        'amplitude': round(daily_data['amplitude'], 2),
                        'close_yesterday': round(daily_data['close_yesterday'], 4),
                        'high_day_before': round(daily_data['high_day_before'], 4),
                        'high_00_03': round(target_00_03_high, 4),
                        'close_04_07': round(target_04_07_close, 4),
                    })
                    print(f"✓ {symbol} 04:00-07:00收盘{target_04_07_close:.4f} < 00:00-03:00最高{target_00_03_high:.4f}，符合震荡条件")
            else:
                print(f"⚠️ {symbol} 缺少昨日特定时段数据")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 4小时K线时出错: {e}")
            continue
    
    # ========== 第四步：按昨日日线振幅排序，取前十 ==========
    result_list.sort(key=lambda x: x['amplitude'], reverse=True)
    top_results = result_list[:PUSH_TOP_N]
    
    # ========== 第五步：生成推送消息 ==========
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 日线突破+4小时震荡扫描",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 昨天日线收阳 + 收盘价 > 前天最高价（日线突破）",
        f"   • 04:00-07:00四小时K棒震荡：收盘价 < 00:00-03:00四小时K棒最高价",
        f"📊 排序：按昨日日线振幅从高到低",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if top_results:
        msg_lines.append(f"📋 推送前十名（共{len(result_list)}个符合条件的币种）：")
        for idx, item in enumerate(top_results, 1):
            msg_lines.append(
                f"{idx}. {item['symbol']}\n"
                f"   昨日振幅: ±{item['amplitude']}%\n"
                f"   昨日收盘: {item['close_yesterday']}\n"
                f"   突破前高: {item['high_day_before']} → {item['close_yesterday']} 📈\n"
                f"   04-07震荡: 最高{item['high_00_03']} > 收盘{item['close_04_07']}"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个符合条件的币种")
        msg_lines.append("💡 解读：日线突破前高，次日凌晨震荡整理，关注后续方向选择")
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
