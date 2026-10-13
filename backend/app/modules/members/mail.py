import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from app.core.config import Settings


def render_mail(settings: Settings, title: str, text: str, link: str, action: str) -> str:
    """Shared HTML for production mail and preview; all dynamic values are escaped."""
    name = escape(settings.smtp_display_name)
    logo = escape(
        settings.smtp_logo_url or f"{settings.app_url}/brand/actvero-icon.png", quote=True
    )
    brand_header = (
        (
            f'<img src="{logo}" alt="{name}" style="display:block;max-width:240px;'
            'max-height:56px;width:auto;height:auto">'
        )
        if settings.smtp_logo_is_wordmark
        else (
            f'<img src="{logo}" width="32" height="32" alt="" '
            f'style="vertical-align:middle;object-fit:contain"> <strong>{name}</strong>'
        )
    )
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;background:#f4f5f7;color:#0f172a;font-family:Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center"
style="padding:32px 16px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"
style="max-width:560px;background:white;border:1px solid #e2e8f0;border-radius:12px">
<tr><td style="padding:32px">{brand_header}
<h1 style="font-size:22px;margin:32px 0 16px">{escape(title)}</h1>
<p style="font-size:14px;line-height:1.8;color:#475569">{escape(text)}</p>
<p style="margin:28px 0"><a href="{escape(link, quote=True)}"
style="display:inline-block;padding:14px 22px;background:#0f172a;color:white;
text-decoration:none;border-radius:8px;font-size:14px">{escape(action)}</a></p>
<p style="font-size:12px;line-height:1.8;color:#64748b">按钮无法打开时，请复制下方链接：<br>
<a href="{escape(link, quote=True)}"
style="color:#475569;word-break:break-all">{escape(link)}</a></p>
<p style="font-size:12px;line-height:1.8;color:#64748b">链接到期或撤销后将失效。
如果你没有请求此操作，请忽略这封邮件。</p></td></tr></table>
<p style="font-size:12px;color:#64748b">此邮件由 {name} 自动发送，请勿直接回复。</p>
</td></tr></table></body></html>'''


def compose_mail(
    settings: Settings, email: str, title: str, text: str, link: str, action: str
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_display_name, settings.smtp_from or ""))
    message["To"] = email
    message["Subject"] = f"{settings.smtp_display_name} · {title}"
    message.set_content(f"{title}\n\n{text}\n\n{action}：{link}\n\n如非本人请求，请忽略。")
    message.add_alternative(render_mail(settings, title, text, link, action), subtype="html")
    return message


async def send_mail(settings: Settings, message: EmailMessage) -> None:
    def deliver() -> None:
        if not settings.smtp_host or not settings.smtp_from:
            raise OSError("Mail service is not configured")
        context = ssl.create_default_context()
        smtp = (
            smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
            if settings.smtp_ssl
            else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        )
        with smtp:
            if settings.smtp_starttls and not settings.smtp_ssl:
                smtp.starttls(context=context)
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)

    await asyncio.to_thread(deliver)


def compose_organization_invitation(settings: Settings, email: str, link: str) -> EmailMessage:
    return compose_mail(
        settings,
        email,
        "组织开通邀请",
        "你受邀创建一个组织。打开邀请后，填写组织名称并注册或登录管理员账号。"
        "完成组织开通后，邀请链接将失效。",
        link,
        "接受邀请并初始化组织",
    )


def compose_member_invitation(
    settings: Settings, email: str, enterprise: str, link: str
) -> EmailMessage:
    return compose_mail(
        settings,
        email,
        "组织成员邀请",
        f"你受邀加入「{enterprise}」。请验证自己的账号后选择是否加入。",
        link,
        "查看邀请",
    )


async def send_invitation(settings: Settings, email: str, enterprise: str, token: str) -> None:
    await send_mail(
        settings,
        compose_member_invitation(settings, email, enterprise, f"{settings.app_url}/join#{token}"),
    )
