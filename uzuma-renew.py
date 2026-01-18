#!/usr/bin/env python3
"""
Uzumaru VPS 自动续期脚本 - 青龙版

cron: 0 10 * * *
new Env('uzuma-renew')

环境变量:
    UZUMA_ACCOUNT: 账号密码，格式 email:password，多个用 & 分隔
    TELEGRAM_BOT_TOKEN: Telegram机器人Token (可选)
    TELEGRAM_CHAT_ID: Telegram聊天ID (可选)
"""

import os
import asyncio
import json
import requests
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

# ==================== 配置 ====================
ACCOUNTS_STR = os.environ.get('UZUMA_ACCOUNT', '')
TG_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TG_USER_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

LOGIN_URL = "https://dash.uzuma.ru/"
INSTANCE_URL = "https://dash.uzuma.ru/instance"
SESSION_DIR = Path(__file__).parent / "sessions"

# ==================== 工具函数 ====================
class Logger:
    @staticmethod
    def log(tag, msg, icon="ℹ"):
        icons = {"OK": "✓", "WARN": "⚠", "WAIT": "⏳", "INFO": "ℹ"}
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {icons.get(icon, icon)} {msg}")

def parse_accounts(s):
    accounts = []
    for item in (s or '').split('&'):
        item = item.strip()
        if ':' in item:
            email, password = item.split(':', 1)
            accounts.append({'email': email.strip(), 'password': password.strip()})
    return accounts

async def cdp_click(cdp, x, y):
    """CDP 模拟点击"""
    await cdp.send('Input.dispatchMouseEvent', {
        'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1
    })
    await asyncio.sleep(0.05)
    await cdp.send('Input.dispatchMouseEvent', {
        'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1
    })

async def handle_turnstile(page, cdp, max_wait=30):
    """处理 Turnstile 验证"""
    Logger.log("Turnstile", "等待验证...", "WAIT")
    
    turnstile = await page.evaluate('''() => {
        const el = document.querySelector('.cf-turnstile');
        if (el) { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y}; }
        return null;
    }''')
    
    if not turnstile:
        Logger.log("Turnstile", "未找到元素", "INFO")
        return True
    
    x = int(turnstile['x'] + 30)
    y = int(turnstile['y'] + 32)
    Logger.log("Turnstile", f"点击 ({x}, {y})", "INFO")
    await cdp_click(cdp, x, y)
    
    for i in range(max_wait):
        await asyncio.sleep(1)
        response = await page.evaluate('() => document.querySelector("input[name=cf-turnstile-response]")?.value || ""')
        if len(response) > 10:
            Logger.log("Turnstile", "验证完成", "OK")
            return True
    
    Logger.log("Turnstile", "验证超时", "WARN")
    return False

def send_telegram(msg):
    """发送 Telegram 通知"""
    if TG_BOT_TOKEN and TG_USER_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                data={"chat_id": TG_USER_ID, "text": msg, "parse_mode": "HTML"},
                timeout=10
            )
        except:
            pass

# ==================== 主逻辑 ====================
async def renew_account(playwright, email, password):
    """续期单个账号的所有实例"""
    Logger.log("账号", f"处理: {email}", "WAIT")
    
    browser = None
    result = {"email": email, "success": False, "msg": "", "instances": []}
    
    try:
        browser = await playwright.chromium.launch(
            headless=False,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', 
                  '--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            viewport={'width': 1400, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        cdp = await context.new_cdp_session(page)
        
        # 加载会话
        SESSION_DIR.mkdir(exist_ok=True)
        session_file = SESSION_DIR / f"{email.replace('@', '_at_')}.json"
        if session_file.exists():
            try:
                with open(session_file) as f:
                    await context.add_cookies(json.load(f))
                Logger.log("会话", "已加载", "OK")
            except:
                pass
        
        # 访问登录页
        await page.goto(LOGIN_URL, timeout=60000)
        await asyncio.sleep(3)
        
        # 检查是否需要登录
        if "dashboard" not in page.url:
            Logger.log("登录", "填写表单...", "INFO")
            await page.fill('#username', email)
            await page.fill('#password', password)
            await asyncio.sleep(1)
            
            # Turnstile
            turnstile_ok = await handle_turnstile(page, cdp)
            if not turnstile_ok:
                result["msg"] = "Turnstile 验证失败"
                return result
            
            # 点击登录
            await page.click('button[type="submit"]')
            await asyncio.sleep(5)
            
            if "dashboard" not in page.url:
                result["msg"] = "登录失败"
                return result
            
            # 保存会话
            cookies = await context.cookies()
            with open(session_file, 'w') as f:
                json.dump(cookies, f)
            Logger.log("登录", "成功", "OK")
        
        # 访问实例列表
        await page.goto(INSTANCE_URL, timeout=60000)
        await asyncio.sleep(3)
        
        # 获取所有实例行
        instances = await page.evaluate('''() => {
            const rows = document.querySelectorAll('tr');
            const result = [];
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length > 4) {
                    result.push({
                        region: cells[0]?.innerText?.trim() || '',
                        size: cells[2]?.innerText?.trim() || '',
                        expiry: cells[4]?.innerText?.trim() || '',
                        status: cells[6]?.innerText?.trim() || ''
                    });
                }
            }
            return result;
        }''')
        
        if not instances:
            result["msg"] = "未找到实例"
            return result
        
        Logger.log("实例", f"找到 {len(instances)} 个实例", "OK")
        
        # 处理每个实例
        renewed_count = 0
        for i, inst in enumerate(instances):
            Logger.log("实例", f"[{i+1}/{len(instances)}] {inst['region']} - {inst['size']} - 到期: {inst['expiry']} - 状态: {inst['status']}", "INFO")
            
            # 点击实例行进入详情
            await page.click(f'tr:has-text("{inst["size"]}")')
            await asyncio.sleep(3)
            
            # 检查是否有 Renew 按钮
            renew_btn = await page.query_selector('button:has-text("Renew")')
            if renew_btn:
                # 检查按钮是否可用
                is_disabled = await renew_btn.evaluate('el => el.disabled || el.classList.contains("opacity-50")')
                if not is_disabled:
                    Logger.log("续期", "点击 Renew...", "WAIT")
                    await renew_btn.click()
                    await asyncio.sleep(2)
                    
                    # 点击确认
                    confirm_btn = await page.query_selector('button:has-text("Confirm")')
                    if confirm_btn:
                        await confirm_btn.click()
                        await asyncio.sleep(3)
                        Logger.log("续期", f"{inst['region']} 续期成功", "OK")
                        renewed_count += 1
                        result["instances"].append(f"✅ {inst['region']}")
                    else:
                        Logger.log("续期", "未找到确认按钮", "WARN")
                        result["instances"].append(f"⚠️ {inst['region']}: 无确认按钮")
                else:
                    Logger.log("续期", f"{inst['region']} 续期按钮不可用（可能未到期）", "INFO")
                    result["instances"].append(f"⏭️ {inst['region']}: 跳过")
            else:
                Logger.log("续期", f"{inst['region']} 无续期按钮", "INFO")
                result["instances"].append(f"⏭️ {inst['region']}: 无按钮")
            
            # 返回实例列表
            await page.goto(INSTANCE_URL, timeout=60000)
            await asyncio.sleep(2)
        
        result["success"] = True
        result["msg"] = f"处理完成，续期 {renewed_count}/{len(instances)} 个"
        
    except Exception as e:
        result["msg"] = f"错误: {str(e)[:100]}"
        Logger.log("错误", result["msg"], "WARN")
    finally:
        if browser:
            await browser.close()
    
    return result

async def main():
    print("=" * 50)
    print("Uzumaru VPS 续期脚本")
    print("=" * 50)
    
    accounts = parse_accounts(ACCOUNTS_STR)
    if not accounts:
        print("错误: 未配置 UZUMA_ACCOUNT 环境变量")
        print("格式: email:password 或 email1:pass1&email2:pass2")
        return
    
    Logger.log("配置", f"共 {len(accounts)} 个账号", "INFO")
    
    results = []
    async with async_playwright() as playwright:
        for acc in accounts:
            result = await renew_account(playwright, acc['email'], acc['password'])
            results.append(result)
            await asyncio.sleep(3)
    
    # 汇总
    success = sum(1 for r in results if r['success'])
    fail = len(results) - success
    
    print("=" * 50)
    Logger.log("汇总", f"成功: {success}, 失败: {fail}", "INFO")
    
    # 发送通知
    msg_lines = ["🖥 Uzumaru VPS 续期", ""]
    for r in results:
        icon = "✅" if r['success'] else "❌"
        msg_lines.append(f"{icon} {r['email']}: {r['msg']}")
        for inst in r.get('instances', []):
            msg_lines.append(f"  {inst}")
    
    msg = "\n".join(msg_lines)
    print(msg)
    send_telegram(msg)

if __name__ == "__main__":
    asyncio.run(main())
