# Bitget 自动扫描推送

这个项目通过 GitHub Actions 定时扫描 Bitget 交易所的合约市场，并将符合策略的币种自动推送到微信。

## 包含的扫描策略

1.  **日线回调扫描** (每天 09:00)
    *   条件：前天涨幅 > 10% 且 昨天收跌
    *   文件：`scanner_gainer_pullback.py`

2.  **日线蓄势扫描** (每天 09:00)
    *   条件：前天涨幅 > 10% 且 昨天收阳但收盘价低于前天最高价
    *   文件：`scanner_pullback_above_high.py`

## 推送服务

所有扫描结果通过 WxPusher 推送到微信。
