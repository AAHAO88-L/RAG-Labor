"""UI 辅助函数 — 侧边栏渲染、时间格式化"""

import datetime
import time as time_module


def get_time_group(ts):
    now = datetime.datetime.now()
    today_start = datetime.datetime(now.year, now.month, now.day)
    yesterday_start = today_start - datetime.timedelta(days=1)
    week_ago_start = today_start - datetime.timedelta(days=7)
    conv_date = datetime.datetime.fromtimestamp(ts)
    if conv_date >= today_start:
        return 0, "今天"
    elif conv_date >= yesterday_start:
        return 1, "昨天"
    elif conv_date >= week_ago_start:
        return 2, "7天内"
    else:
        return 3, "更早"


def format_time_ago(ts):
    now_ts = time_module.time()
    diff = now_ts - ts
    if diff < 60:
        return "刚刚"
    elif diff < 3600:
        return f"{int(diff // 60)}分钟前"
    elif diff < 86400:
        return f"{int(diff // 3600)}小时前"
    elif diff < 172800:
        return "昨天"
    else:
        return time_module.strftime("%m-%d", time_module.localtime(ts))


def build_conv_list_html(convs, selected_id=None, search_query=""):
    if search_query:
        q = search_query.lower()
        convs = [c for c in convs if q in c["title"].lower() or q in c.get("summary", "").lower()]

    if not convs:
        return '<div class="conv-list-wrap"><div class="conv-list"><div class="conv-empty">暂无对话</div></div></div>'

    sorted_convs = sorted(convs, key=lambda c: (not c.get("pinned"), -c["mtime"]))

    parts = ['<div class="conv-list-wrap"><div class="conv-list">']
    for c in sorted_convs:
        is_pinned = c.get("pinned")
        display_title = "📌 " + c["title"] if is_pinned else c["title"]
        if len(display_title) > 24:
            display_title = display_title[:24] + "…"
        time_str = format_time_ago(c["mtime"])
        sel = " selected" if c["id"] == selected_id else ""
        display_title_esc = display_title.replace("'", "&#39;").replace('"', "&quot;")
        conv_id = c["id"]
        parts.append(
            f'<div class="conv-item{sel}" data-id="{conv_id}" onclick="selectConv(\'{conv_id}\')">'
            f'<span class="conv-item-title">{display_title_esc}</span>'
            f'<span class="conv-item-time">{time_str}</span>'
            f'<span class="conv-item-actions">'
            f'<button class="conv-action-btn" title="{"取消置顶" if is_pinned else "置顶"}" onclick="pinConv(event, \'{conv_id}\')">📌</button>'
            f'<button class="conv-action-btn" title="删除" onclick="deleteConv(event, \'{conv_id}\')">🗑</button>'
            f'</span>'
            f'</div>'
        )
    parts.append("</div></div>")
    return "\n".join(parts)


def build_user_area_html(username, avatar_b64=""):
    if avatar_b64:
        avatar_src = avatar_b64
    else:
        initial = username[0].upper() if username else "U"
        avatar_src = (
            f"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32'"
            f" viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='16' fill='%234569d6'/%3E"
            f"%3Ctext x='16' y='21' text-anchor='middle' fill='white' font-size='16'"
            f" font-weight='600'%3E{initial}%3C/text%3E%3C/svg%3E"
        )

    return f"""<div class="user-area-wrap">
<div class="user-area">
    <div class="user-trigger" onclick="toggleUserMenu()">
        <img class="user-avatar" src="{avatar_src}" alt="avatar" />
        <span class="user-name">{username}</span>
        <span class="user-arrow">▾</span>
    </div>
    <div class="user-dropdown" id="user-dropdown">
        <div class="user-dropdown-item" onclick="document.querySelector('#h-avatar input[type=file]').click(); toggleUserMenu()">更改头像</div>
        <div class="user-dropdown-item" onclick="showPwdForm(); toggleUserMenu()">更改密码</div>
        <div class="user-dropdown-item user-dropdown-exit" onclick="doLogout()">退出登录</div>
    </div>
</div>
</div>"""


PWD_MODAL_HTML = """
<div id="pwd-overlay" class="pwd-overlay">
  <div class="pwd-modal">
    <h3>🔑 更改密码</h3>
    <input type="password" id="pwd-old" placeholder="原密码" autocomplete="off" />
    <input type="password" id="pwd-new" placeholder="新密码（至少4位）" autocomplete="off" />
    <input type="password" id="pwd-confirm" placeholder="确认新密码" autocomplete="off" />
    <div id="pwd-err-msg" class="pwd-error"></div>
    <div id="pwd-suc-msg" class="pwd-success"></div>
    <div class="pwd-actions">
      <button class="pwd-confirm" onclick="submitPwd()">确认更改</button>
      <button class="pwd-cancel" onclick="hidePwdForm()">取消</button>
    </div>
  </div>
</div>
"""
