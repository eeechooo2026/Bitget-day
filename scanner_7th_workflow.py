# 仅展示关键修改部分，完整代码请基于之前的第五个工作流修改
# 在 main() 函数中，针对每个 symbol 添加逐步日志

# ... 前面的导入和函数定义保持不变 ...

def main():
    # ... 前面的初始化代码 ...

    for idx, symbol in enumerate(swap_symbols):
        # 只针对 BLURUSDT 打印详细日志（可临时修改）
        is_debug = 'BLURUSDT' in symbol.upper()
        if is_debug:
            print(f"\n🔍 开始详细分析 {symbol}")

        try:
            # 获取K线数据...
            # 在每一步条件判断后打印结果

            # 均线多头排列
            if not is_bullish_arrangement(ma_values):
                if is_debug: print(f"❌ 均线不是多头: MA5={ma_values[5]}, MA10={ma_values[10]}, MA20={ma_values[20]}")
                continue
            if is_debug: print(f"✅ 均线多头: {ma_values[5]:.4f} > {ma_values[10]:.4f} > {ma_values[20]:.4f}")

            # 查找K线
            k_prev1 = find_kline_by_timestamp(ohlcv_4h, prev1_ts_4h)
            k_prev2 = find_kline_by_timestamp(ohlcv_4h, prev2_ts_4h)
            k_prev3 = find_kline_by_timestamp(ohlcv_4h, prev3_ts_4h)
            if is_debug:
                print(f"📅 目标时间戳: 上根={prev1_ts_4h}({ts_to_beijing(prev1_ts_4h)}), 存在={k_prev1 is not None}")
                print(f"   上上根={prev2_ts_4h}({ts_to_beijing(prev2_ts_4h)}), 存在={k_prev2 is not None}")
                print(f"   上上上根={prev3_ts_4h}({ts_to_beijing(prev3_ts_4h)}), 存在={k_prev3 is not None}")
            if not (k_prev1 and k_prev2 and k_prev3):
                if is_debug: print("❌ 缺少K线数据")
                continue

            close1, open1 = k_prev1[4], k_prev1[1]
            close2, high2, low2 = k_prev2[4], k_prev2[2], k_prev2[3]
            high3, low3 = k_prev3[2], k_prev3[3]

            # 条件2: 上根收盘 > MA5
            if close1 <= ma_values[5]:
                if is_debug: print(f"❌ 上根收盘{close1:.4f} <= MA5({ma_values[5]:.4f})")
                continue
            if is_debug: print(f"✅ 上根收盘{close1:.4f} > MA5")

            # 条件3: 上上根震荡
            is_consol2 = is_consolidation_kline(close2, high3, low3)
            if not is_consol2:
                if is_debug: print(f"❌ 上上根震荡失败: 收盘{close2:.4f} 不在 [{low3:.4f}, {high3:.4f}] 区间内")
                continue
            if is_debug: print(f"✅ 上上根震荡: {close2:.4f} ∈ [{low3:.4f}, {high3:.4f}]")

            # 条件4: 上根震荡
            is_consol1 = is_consolidation_kline(close1, high2, low2)
            if not is_consol1:
                if is_debug: print(f"❌ 上根震荡失败: 收盘{close1:.4f} 不在 [{low2:.4f}, {high2:.4f}] 区间内")
                continue
            if is_debug: print(f"✅ 上根震荡: {close1:.4f} ∈ [{low2:.4f}, {high2:.4f}]")

            # 条件5: J值比较
            # ... 计算KDJ并获取J值 ...
            if j_vals[idx1] <= j_vals[idx2]:
                if is_debug: print(f"❌ J值: 上根J={j_vals[idx1]:.2f} <= 上上根J={j_vals[idx2]:.2f}")
                continue
            if is_debug: print(f"✅ J值上升: {j_vals[idx2]:.2f} → {j_vals[idx1]:.2f}")

            # 日线跌幅计算...
            if loss_1d is None:
                if is_debug: print("❌ 日线数据不足或跌幅计算失败")
                continue

            # 全部通过
            if is_debug: print(f"🎉 {symbol} 通过所有条件！")
            result_list.append(...)

        except Exception as e:
            if is_debug: print(f"⚠️ 异常: {e}")
