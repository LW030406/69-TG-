import os
import json
import requests
import time
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import email.utils

# 从环境变量获取 Gmail 配置 (这些变量在 send_email 内部直接使用，无需通过参数传递)
GMAIL_SENDER_EMAIL = os.getenv('GMAIL_SENDER_EMAIL')
GMAIL_SENDER_PASSWORD = os.getenv('GMAIL_SENDER_PASSWORD')
GMAIL_INITIAL_RECEIVER_EMAIL = os.getenv('GMAIL_RECEIVER_EMAIL')

# 辅助函数：清理字符串中的非ASCII空格字符
def clean_string(text):
    if text is None:
        return ""
    # '\xa0' 是不间断空格
    # '\u200b' 是零宽空格
    # '\uFEFF' 是字节顺序标记 (BOM)
    # 这些是常见的，肉眼不可见但可能导致编码问题的字符
    return str(text).replace('\xa0', ' ').replace('\u200b', '').replace('\uFEFF', '')

# 获取html中的用户信息及订阅链接
def fetch_and_extract_info(domain, headers):
    url = f"{domain}/user"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status() # 检查HTTP响应状态码，如果不是2xx，则抛出异常
    except requests.exceptions.RequestException as e:
        print(f"用户信息获取失败，网络或页面打开异常: {e}")
        return "无法获取用户信息或订阅链接。"

    soup = BeautifulSoup(response.text, 'html.parser')

    script_tags = soup.find_all('script')

    chatra_script = None
    for script in script_tags:
        # 使用 in 或者直接检查内容，避免将 None 的 string 属性转换为 str
        if script.string and 'window.ChatraIntegration' in script.string:
            chatra_script = script.string
            break

    if not chatra_script:
        print("未识别到用户信息脚本")
        return "未识别到用户信息或订阅链接。"

    user_info_parts = []
    
    # 提取到期时间和剩余流量
    class_expire = re.search(r"'Class_Expire': '(.*?)'", chatra_script)
    unused_traffic = re.search(r"'Unused_Traffic': '(.*?)'", chatra_script)

    if class_expire and unused_traffic:
        user_info_parts.append(f"到期时间: {clean_string(class_expire.group(1))}")
        user_info_parts.append(f"剩余流量: {clean_string(unused_traffic.group(1))}")
    else:
        user_info_parts.append("用户信息 (到期时间/剩余流量) 未找到。")

    # 提取 Clash 和 V2Ray 订阅链接
    clash_link_found = False
    for script in script_tags:
        if script.string and 'index.oneclickImport' in script.string and 'clash' in script.string:
            link_match = re.search(r"'https://checkhere.top/link/(.*?)\?sub=1'", script.string)
            if link_match:
                user_info_parts.append(f"Clash 订阅链接: https://checkhere.top/link/{clean_string(link_match.group(1))}?clash=1")
                user_info_parts.append(f"v2ray 订阅链接: https://checkhere.top/link/{clean_string(link_match.group(1))}?sub=3")
                clash_link_found = True
                break
    
    if not clash_link_found:
        user_info_parts.append("订阅链接未找到。")


    # 返回拼接后的清理过的用户信息字符串
    return '\n'.join(user_info_parts)


def generate_config():
    # 获取环境变量
    domain = os.getenv('DOMAIN', 'https://69yun69.com')  # 默认值，如果未设置环境变量
    bot_token = os.getenv('BOT_TOKEN', '') # 允许 BOT_TOKEN 为空字符串
    chat_id = os.getenv('CHAT_ID', '')     # 允许 CHAT_ID 为空字符串

    accounts = []
    index = 1

    while True:
        user = os.getenv(f'USER{index}')
        password = os.getenv(f'PASS{index}')
        c_email = os.getenv(f'C_EMAIL{index}')

        if not user or not password:
            break

        accounts.append({
            'user': user,
            'pass': password,
            'c_email': c_email
        })
        index += 1

    config = {
        'domain': domain,
        'BotToken': bot_token,
        'ChatID': chat_id,
        'accounts': accounts
    }
    print("加载配置:", json.dumps(config, indent=2, ensure_ascii=False)) # 打印配置时更友好
    return config


# 发送消息到 Telegram Bot 的函数，支持按钮
def send_message(msg="", BotToken="", ChatID=""):
    now = datetime.utcnow()
    beijing_time = now + timedelta(hours=8)
    formatted_time = beijing_time.strftime("%Y-%m-%d %H:%M:%S")

    if BotToken and ChatID: # 仅当 BotToken 和 ChatID 不为空时才发送
        message_text = f"执行时间: {formatted_time}\n{msg}"

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "一休交流群",
                        "url": "https://t.me/yxjsjl"
                    }
                ]
            ]
        }

        url = f"https://api.telegram.org/bot{BotToken}/sendMessage"
        payload = {
            "chat_id": ChatID,
            "text": message_text,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard)
        }

        try:
            response = requests.post(url, data=payload)
            response.raise_for_status() # 检查网络响应
            print(f"Telegram 消息发送成功: {response.status_code}")
            return response
        except requests.exceptions.RequestException as e:
            print(f"发送电报消息时发生错误: {e}")
            return None
    else:
        print("Telegram Bot Token 或 Chat ID 未配置，跳过发送消息。")
        return None


# 登录并签到的主要函数
def checkin(account, domain, BotToken, ChatID, InitialReceiverEmail): # 移除 account_index 参数
    user = account['user']
    pass_ = account['pass']
    c_email = account['c_email']

    # 初始的签到结果消息，包含账号信息（已清理）
    checkin_overall_message = f"地址: {clean_string(domain)}\n账号: {clean_string(user)}\n密码: <tg-spoiler>{clean_string(pass_)}</tg-spoiler>\n\n"
    checkin_message_for_email = "" # 仅用于邮件（不含密码）

    try:
        if not domain or not user or not pass_:
            raise ValueError('必需的配置参数缺失 (域名/用户名/密码)。')

        login_url = f"{domain}/auth/login"
        login_data = {
            'email': user,
            'passwd': pass_,
            'remember_me': 'on',
            'code': "",
        }
        login_headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Origin': domain,
            'Referer': f"{domain}/auth/login",
        }

        login_response = requests.post(login_url, json=login_data, headers=login_headers)
        print(f'{user}账号登录状态: {login_response.status_code}')
        login_response.raise_for_status() # 再次检查HTTP状态码

        login_json = login_response.json()
        if login_json.get("ret") != 1:
            raise ValueError(f"登录失败: {login_json.get('msg', '未知错误')}")

        cookies = login_response.cookies
        if not cookies:
            raise ValueError('登录成功但未收到Cookie。')

        time.sleep(1) # 等待确保登录状态生效

        checkin_url = f"{domain}/user/checkin"
        checkin_headers = {
            'Cookie': '; '.join([f"{key}={value}" for key, value in cookies.items()]),
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': domain,
            'Referer': f"{domain}/user/panel",
            'X-Requested-With': 'XMLHttpRequest'
        }

        checkin_response = requests.post(checkin_url, headers=checkin_headers)
        print(f'{user}账号签到状态: {checkin_response.status_code}')
        checkin_response.raise_for_status()

        checkin_result_json = checkin_response.json()
        
        # 获取用户签到信息和订阅链接
        # 这里的 fetch_and_extract_info 会返回一个清理过的字符串
        user_and_subscribe_info = fetch_and_extract_info(domain, checkin_headers)


        # 根据返回的结果更新签到信息
        current_checkin_msg = ""
        if checkin_result_json.get('ret') == 1 or checkin_result_json.get('ret') == 0:
            current_checkin_msg = f"🎉 签到结果 🎉\n {clean_string(checkin_result_json.get('msg', '签到成功' if checkin_result_json['ret'] == 1 else '签到失败'))}"
        else:
            current_checkin_msg = f"🎉 签到结果 🎉\n {clean_string(checkin_result_json.get('msg', '签到结果未知'))}"
        
        # 构建给 Telegram 和 Email 的完整消息
        telegram_message_content = f"{checkin_overall_message}{user_and_subscribe_info}\n\n{current_checkin_msg}"
        email_message_content = f"地址: {clean_string(domain)}\n账号: {clean_string(user)}\n\n{user_and_subscribe_info}\n\n{current_checkin_msg}" # 邮件中不含密码

        # 发送签到结果到 Telegram
        send_message(telegram_message_content, BotToken, ChatID)

        # 确定邮件接收者
        receiver_email = c_email if c_email else InitialReceiverEmail
        
        return email_message_content, receiver_email # 返回用于邮件的清理后的内容和接收邮箱

    except Exception as error:
        # 捕获异常，打印错误并发送错误信息到 Telegram
        error_message = f"{clean_string(user)}账号签到异常: {clean_string(str(error))}"
        print(error_message)
        send_message(error_message, BotToken, ChatID)
        return None, None # 返回 None 表示不发送邮件

def send_email(subject, content, receiver_email):
    if not GMAIL_SENDER_EMAIL or not GMAIL_SENDER_PASSWORD or not receiver_email:
        print("Gmail 发送者邮箱、密码或接收者邮箱未配置，跳过邮件发送。")
        return

    try:
        # 清理邮件正文中的特殊字符
        cleaned_content = clean_string(content)

        msg = MIMEText(cleaned_content, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8') # 让 Header 自己处理编码
        msg['From'] = email.utils.formataddr((str(Header(GMAIL_SENDER_EMAIL.split("@")[0], 'utf-8')), GMAIL_SENDER_EMAIL))
        msg['To'] = email.utils.formataddr((str(Header(receiver_email.split("@")[0], 'utf-8')), receiver_email)) # 将email.utils.formataddr应用于接收者

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.set_debuglevel(1) # 启用调试输出
            server.ehlo()
            server.login(GMAIL_SENDER_EMAIL, GMAIL_SENDER_PASSWORD)
            server.send_message(msg) # 使用 send_message 发送 MIME 对象
        
        print("邮件发送成功")
    except smtplib.SMTPAuthenticationError as e:
        print(f"Error: SMTP认证失败，请检查Gmail邮箱和密码或应用专用密码设置: {e}")
    except smtplib.SMTPException as e:
        print(f"Error: SMTP服务器错误: {e}")
    except Exception as e:
        print(f"Error: 发送邮件时发生意外错误: {e}")


if __name__ == "__main__":
    # 读取配置
    config = generate_config()

    domain = config['domain']
    BotToken = config['BotToken']
    ChatID = config['ChatID']

    # 循环执行每个账号的签到任务
    for i, account in enumerate(config.get("accounts", [])):
        print(f"\n----------------------------------开始处理账号 {i+1}----------------------------------")
        
        # 调用 checkin 函数，获取邮件内容和接收者邮箱
        # GMAIL_INITIAL_RECEIVER_EMAIL 作为 checkin 函数的参数传入
        checkin_content_for_email, receiver_email_for_mail = checkin(account, domain, BotToken, ChatID, GMAIL_INITIAL_RECEIVER_EMAIL)

        if checkin_content_for_email and receiver_email_for_mail:
            # 发送邮件通知
            try:
                # 邮件主题可以包含账号编号或用户名，增加辨识度
                email_subject = f'69云签到结果 - 账号 {i+1} ({clean_string(account["user"])})'
                send_email(email_subject, checkin_content_for_email, receiver_email_for_mail)
            except Exception as e:
                print(f"发送邮件失败: {e}")
        else:
            print(f"账号 {clean_string(account['user'])} 签到失败或无邮件内容，不发送邮件。")
        print(f"----------------------------------账号 {i+1} 处理结束----------------------------------\n")

