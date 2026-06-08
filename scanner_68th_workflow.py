import ccxt
import time
from datetime import datetime, timedelta, timezone
import requests
import json

# ================== 配置区域 ==================
WX_PUSHER_APP_TOKEN = "AT_6EcetNOaafHBZXtsqLSob1KGlfHQTMss"
WX_PUSHER_UID = "UID_Lrlwr0VJuCwmT3sCGP2yJbLOCQhU"

PUSH_TOP_N = 10
TIMEFRAME_1W = '1w'  # 周线
# =============================================

def send_push_wxpusher(message):
    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": WX_PUSHER_APP_TOKEN,
        "content": message,
        "summary": message[:50],
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
        else:
            print(f"❌ 推送失败: {result}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")

def get_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_weekly_target_dates(beijing_now, offset_weeks=0):
    """
    返回目标周线对应的日期字符串（UTC 时间的周一日期）
    用于匹配 fetch_ohlcv 返回的 K 线
    """
    # 计算北京时间所在周的周一日期
    days_since_monday = beijing_now.weekday()
    monday_beijing = beijing_now - timedelta(days=days_since_monday)
    target_monday = monday_beijing + timedelta(weeks=offset_weeks)
    # 转换为 UTC 日期（减去8小时，如果跨日则日期会变）
    utc_date = (target_monday - timedelta(hours=8)).date()
    return utc_date.strftime('%Y-%m-%d')

def find_kline_by_date(ohlcv, target_date_str):
    """在K线列表中查找指定日期（UTC日期）的K线"""
    for k in ohlcv:
        # 将时间戳转换为 UTC 日期字符串
        k_date = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date().strftime('%Y-%m-%d')
        if k_date == target_date_str:
            return k
    return None

def ts_to_beijing(ts):
    return datetime.fromtimestamp(ts/1000) + timedelta(hours=8)

def main():
    utc_now = get_utc_now()
    beijing_now = utc_now + timedelta(hours=8)
    print(f"🚀 开始第68个工作流扫描（周线级别：上根+上上根涨幅和排序 - 修复版）")
    print(f"   当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 策略逻辑：")
    print(f"   • 扫描所有USDT本位永续合约")
    print(f"   • 排序指标 = 上根周线涨幅 + 上上根周线涨幅（从高到低）")
    print(f"📊 推送：前十名（微信推送）")

    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    print("📡 正在加载合约市场数据...")
    markets = exchange.load_markets()
    print(f"📊 共加载 {len(markets)} 个交易对")

    # 筛选 USDT 本位永续合约，并提取杠杆信息
    swap_symbols = []
    leverage_info = {}
    for symbol, market in markets.items():
        if market.get('type') == 'swap' and symbol.endswith('/USDT:USDT'):
            max_leverage = 0
            if 'limits' in market and 'leverage' in market['limits'] and 'max' in market['limits']['leverage']:
                max_leverage = float(market['limits']['leverage']['max'])
            elif 'info' in market and 'maxLeverage' in market['info']:
                max_leverage = float(market['info']['maxLeverage'])
            elif 'leverage' in market:
                max_leverage = float(market['leverage']) if isinstance(market['leverage'], (int, float)) else 0
            if max_leverage > 0:
                swap_symbols.append(symbol)
                leverage_info[symbol] = max_leverage
    print(f"📊 共找到 {len(swap_symbols)} 个 USDT 本位永续合约（且有有效杠杆信息）")

    if len(swap_symbols) == 0:
        print("❌ 未找到合约交易对")
        return

    # 计算目标周线的日期字符串
    target_date_prev1 = get_weekly_target_dates(beijing_now, -1)   # 上根周线
    target_date_prev2 = get_weekly_target_dates(beijing_now, -2)   # 上上根周线
    print(f"📅 目标周线日期（UTC）:")
    print(f"   上根周线: {target_date_prev1}")
    print(f"   上上根周线: {target_date_prev2}")

    print("⏳ 正在获取周线K线数据...")
    result_list = []

    for idx, symbol in enumerate(swap_symbols):
        try:
            # 获取最近10根周线K线
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME_1W, limit=10)
            if len(ohlcv) < 3:
                continue

            # 用日期查找K线（不再用时间戳精确匹配）
            k1 = find_kline_by_date(ohlcv, target_date_prev1)   # 上根周线
            k2 = find_kline_by_date(ohlcv, target_date_prev2)   # 上上根周线
            if k1 is None or k2 is None:
                # 调试输出（可选，首次运行时可取消注释查看）
                # print(f"   {symbol}: 未找到目标周线 (上根={target_date_prev1}, 上上根={target_date_prev2})")
                continue

            open1 = k1[1]
            close1 = k1[4]
            open2 = k2[1]
            close2 = k2[4]

            if open1 == 0 or open2 == 0:
                continue

            # 计算涨幅
            gain1 = (close1 - open1) / open1 * 100
            gain2 = (close2 - open2) / open2 * 100
            total_gain = gain1 + gain2

            leverage = leverage_info[symbol]

            result_list.append({
                'symbol': symbol.replace('/USDT:USDT', ''),
                'gain1': round(gain1, 2),
                'gain2': round(gain2, 2),
                'total_gain': round(total_gain, 2),
                'leverage': round(leverage),
            })

            if (idx+1) % 50 == 0:
                print(f"进度: {idx+1}/{len(swap_symbols)}")
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ 分析 {symbol} 时出错: {e}")
            time.sleep(0.3)

    # 按总涨幅从高到低排序
    result_list.sort(key=lambda x: x['total_gain'], reverse=True)
    top = result_list[:PUSH_TOP_N]

    current_time = beijing_now.strftime('%Y-%m-%d %H:%M')
    msg_lines = [
        f"📊 Bitget 周线级别涨幅和排行（第68个工作流 - 修复版）",
        f"🕘 时间：{current_time}（北京时间）",
        f"📈 策略逻辑：",
        f"   • 扫描所有USDT本位永续合约",
        f"   • 排序 = 上根周线涨幅 + 上上根周线涨幅",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    if top:
        msg_lines.append(f"📋 涨幅和前十名（共{len(result_list)}个合约）：")
        for i, item in enumerate(top, 1):
            msg_lines.append(
                f"{i}. {item['symbol']}\n"
                f"   上上根周线涨幅: +{item['gain2']}%\n"
                f"   上根周线涨幅: +{item['gain1']}%\n"
                f"   总涨幅: +{item['total_gain']}%\n"
                f"   杠杆: {item['leverage']}x"
            )
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📊 共筛选出 {len(result_list)} 个合约")
        msg_lines.append("💡 解读：连续两周累计涨幅排名")
        msg_lines.append("⚠️ 此信息仅供参考，不构成投资建议")
    else:
        msg_lines.append("😔 未找到符合条件的币种")

    message = "\n".join(msg_lines)
    print("\n" + "="*50)
    print(message)
    print("="*50)
    send_push_wxpusher(message)

if __name__ == "__main__":
    main()
