# Uzumaru VPS 自动续期脚本

自动续期 Uzumaru (dash.uzuma.ru) 免费 VPS。

## 功能

- 支持多账号批量处理
- 自动发现账号下所有实例
- 自动处理 Cloudflare Turnstile 验证
- 会话持久化
- Telegram 通知支持

## 青龙面板使用

### 1. 添加订阅

在青龙面板的「订阅管理」中添加：

- **名称**: uzuma-renew
- **链接**: `https://github.com/donma033x/uzuma-renew.git`
- **分支**: main
- **定时规则**: `0 10 * * *`

### 2. 配置环境变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `ACCOUNTS_UZUMA` | 账号配置 | `邮箱:密码&邮箱2:密码2` |
| `TELEGRAM_BOT_TOKEN` | TG机器人Token | (可选) |
| `TELEGRAM_CHAT_ID` | TG聊天ID | (可选) |

### 3. 安装依赖

在青龙「依赖管理」→「Python3」中安装：playwright, requests

## 手动运行

```bash
export ACCOUNTS_UZUMA="your@email.com:password"
xvfb-run python3 uzuma-renew.py
```

## 许可

MIT License
