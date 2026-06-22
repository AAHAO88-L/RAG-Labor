import gradio as gr
import sys
import os
import json
import uuid
import datetime
import time as time_module
import requests

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")


def get_headers(token):
    return {"Authorization": f"Bearer {token}"}


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


def fetch_conversations(token, search_query=""):
    """从后端获取对话列表，格式化为 Dropdown 的 choices"""
    if not token or not token.strip():
        return []
    try:
        resp = requests.get(f"{API_BASE}/api/conversations", headers=get_headers(token), timeout=5)
        if resp.status_code != 200:
            return []
        convs = resp.json()
    except Exception:
        return []

    if search_query.strip():
        q = search_query.lower()
        convs = [c for c in convs if q in c["title"].lower() or q in c.get("summary", "").lower()]

    if not convs:
        return []

    # 格式化为 Gradio Dropdown choices: [(显示标签, 值), ...]
    choices = []
    current_group = None
    for c in convs:
        key, label = get_time_group(c["mtime"])
        group_header = "📌 置顶" if c.get("pinned") else f"🕐 {label}"
        if group_header != current_group:
            current_group = group_header
            choices.append((group_header, f"__group__{group_header}"))

        title = c["title"][:22] + "…" if len(c["title"]) > 22 else c["title"]
        summary = c.get("summary", "")
        time_str = format_time_ago(c["mtime"])
        prefix = "⭐ " if c.get("pinned") else ""
        display = f"{prefix}{title} | {time_str}"
        choices.append((display, c["id"]))

    return choices


CSS = """
footer { display: none !important; }
#input-box textarea { min-height: 56px !important; border: 1.5px solid #d1d5db !important; border-radius: 12px !important; padding: 12px 16px !important; }
#input-box { margin-top: 8px !important; }
.sidebar-btn { flex: 1; min-width: 0; }
"""

with gr.Blocks(title="劳动法智能助手", fill_height=True) as demo:

    state = gr.State({"token": None, "user_id": None, "username": None,
                       "current_conv_id": None, "current_title": "新对话",
                       "conv_map": {}})

    # ── 登录/注册界面 ──
    with gr.Column(visible=True, elem_id="login-panel") as login_panel:
        gr.HTML('<div style="text-align:center;padding:40px 0 20px;"><h1 style="font-size:28px;font-weight:600;">劳动法智能助手</h1><p style="color:#888;">登录或注册以继续</p></div>')
        with gr.Row(equal_height=True):
            with gr.Column(scale=1):
                pass
            with gr.Column(scale=2, min_width=320):
                username_input = gr.Textbox(label="用户名", placeholder="请输入用户名")
                password_input = gr.Textbox(label="密码", placeholder="请输入密码", type="password")
                with gr.Row():
                    login_btn = gr.Button("登录", variant="primary", scale=1)
                    register_btn = gr.Button("注册", variant="secondary", scale=1)
                login_msg = gr.HTML('')
            with gr.Column(scale=1):
                pass

    # ── 主界面（登录后可见） ──
    with gr.Column(visible=False, elem_id="main-panel") as main_panel:
        with gr.Sidebar(position="left", width=280, open=True, label="历史记录"):
            gr.HTML('<div style="font-weight:600;font-size:15px;margin-bottom:8px;">💬 对话</div>')
            new_chat_btn = gr.Button("✏️  新建对话", variant="secondary", size="sm")
            search_input = gr.Textbox(placeholder="搜索历史对话...", show_label=False, container=False, max_lines=1)
            conv_dropdown = gr.Dropdown(choices=[], label="", interactive=True, container=False, scale=1)
            with gr.Row():
                pin_btn = gr.Button("⭐ 置顶", size="sm", elem_classes="sidebar-btn")
                delete_btn = gr.Button("🗑 删除", size="sm", elem_classes="sidebar-btn")
            logout_btn = gr.Button("🚪 退出登录", variant="secondary", size="sm")

        chatbot = gr.Chatbot(height="100%", layout="bubble",
                            placeholder="开始向劳动法智能助手提问...", scale=1, elem_id="main-chat")
        msg = gr.Textbox(
            placeholder="请输入您的劳动法问题...",
            show_label=False, container=True, scale=0, elem_id="input-box",
        )

    # ── 辅助：更新下拉列表 ──
    def refresh_dropdown(token="", query=""):
        if not token:
            return gr.update(choices=[], value=None)
        choices = fetch_conversations(token, query)
        return gr.update(choices=choices, value=None)

    # ── 登录/注册 ──
    def fn_login(username, password):
        if not username or not password:
            return "请填写用户名和密码", gr.update(), gr.update(), state
        try:
            resp = requests.post(f"{API_BASE}/api/login", json={"username": username, "password": password}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                new_state = {"token": data["token"], "user_id": data["user_id"], "username": data["username"],
                             "current_conv_id": None, "current_title": "新对话", "conv_map": {}}
                dd = refresh_dropdown(data["token"])
                return "", gr.update(visible=False), gr.update(visible=True), dd, new_state
            else:
                return f"❌ {resp.json().get('detail', '登录失败')}", gr.update(), gr.update(), state
        except Exception as e:
            return f"❌ 连接后端失败：{e}", gr.update(), gr.update(), state

    login_btn.click(fn_login, [username_input, password_input], [login_msg, login_panel, main_panel, conv_dropdown, state])

    def fn_register(username, password):
        if not username or not password:
            return "请填写用户名和密码", gr.update(), gr.update(), state
        try:
            resp = requests.post(f"{API_BASE}/api/register", json={"username": username, "password": password}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                new_state = {"token": data["token"], "user_id": data["user_id"], "username": data["username"],
                             "current_conv_id": None, "current_title": "新对话", "conv_map": {}}
                dd = refresh_dropdown(data["token"])
                return "", gr.update(visible=False), gr.update(visible=True), dd, new_state
            else:
                return f"❌ {resp.json().get('detail', '注册失败')}", gr.update(), gr.update(), state
        except Exception as e:
            return f"❌ 连接后端失败：{e}", gr.update(), gr.update(), state

    register_btn.click(fn_register, [username_input, password_input], [login_msg, login_panel, main_panel, conv_dropdown, state])

    # ── 退出登录 ──
    def fn_logout():
        new_state = {"token": None, "user_id": None, "username": None,
                     "current_conv_id": None, "current_title": "新对话", "conv_map": {}}
        return gr.update(visible=True), gr.update(visible=False), [], gr.update(choices=[], value=None), new_state

    logout_btn.click(fn_logout, None, [login_panel, main_panel, chatbot, conv_dropdown, state])

    # ── 搜索 ──
    def fn_search(query, state_data):
        return refresh_dropdown(state_data.get("token"), query)

    search_input.change(fn_search, [search_input, state], [conv_dropdown])

    # ── 新建对话 ──
    def fn_new_chat(state_data):
        state_data["current_conv_id"] = uuid.uuid4().hex[:12]
        state_data["current_title"] = "新对话"
        return [], state_data, gr.update(value=None)

    new_chat_btn.click(fn_new_chat, [state], [chatbot, state, conv_dropdown])

    # ── 加载选中对话 ──
    def fn_load_selected(conv_id, state_data):
        if not conv_id or conv_id.startswith("__group__") or not state_data.get("token"):
            return [], state_data, gr.update()
        try:
            resp = requests.get(f"{API_BASE}/api/conversations/{conv_id}",
                                headers=get_headers(state_data["token"]), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                state_data["current_conv_id"] = conv_id
                state_data["current_title"] = data.get("title", "对话")
                return data.get("messages", []), state_data, gr.update()
        except Exception:
            pass
        return [], state_data, gr.update()

    conv_dropdown.change(fn_load_selected, [conv_dropdown, state], [chatbot, state, conv_dropdown])

    # ── 删除选中对话 ──
    def fn_delete_selected(conv_id, state_data):
        if not conv_id or conv_id.startswith("__group__") or not state_data.get("token"):
            return gr.update(), state_data, gr.update()
        try:
            requests.delete(f"{API_BASE}/api/conversations/{conv_id}",
                            headers=get_headers(state_data["token"]), timeout=5)
        except Exception:
            pass
        chat_history = []
        state_data["current_conv_id"] = None
        state_data["current_title"] = "新对话"
        dd = refresh_dropdown(state_data["token"])
        return chat_history, state_data, dd

    delete_btn.click(fn_delete_selected, [conv_dropdown, state], [chatbot, state, conv_dropdown])

    # ── 置顶选中对话 ──
    def fn_pin_selected(conv_id, state_data):
        if not conv_id or conv_id.startswith("__group__") or not state_data.get("token"):
            return gr.update()
        try:
            requests.patch(f"{API_BASE}/api/conversations/{conv_id}/pin",
                           headers=get_headers(state_data["token"]), timeout=5)
        except Exception:
            pass
        return refresh_dropdown(state_data["token"])

    pin_btn.click(fn_pin_selected, [conv_dropdown, state], [conv_dropdown])

    # ── 流式问答 ──
    def respond_stream(message, chat_history, state_data):
        # Gradio 6 generator 中 State 可能是代理对象，转成 dict
        if hasattr(state_data, 'value'):
            state_data = state_data.value
        if not message.strip():
            yield chat_history, state_data, gr.update(), ""
            return
        if not state_data.get("token"):
            yield chat_history, state_data, gr.update(), ""
            return

        token = state_data["token"]
        conv_id = state_data.get("current_conv_id") or uuid.uuid4().hex[:12]
        state_data["current_conv_id"] = conv_id

        chat_history.append({"role": "user", "content": message})
        chat_history.append({"role": "assistant", "content": "▍"})
        yield chat_history, state_data, gr.update(), ""

        full_answer = ""
        try:
            history_for_api = chat_history[:-1]
            resp = requests.post(
                f"{API_BASE}/api/query",
                json={"conv_id": conv_id, "message": message, "history": history_for_api},
                headers=get_headers(token),
                stream=True, timeout=120,
            )
            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    payload = json.loads(decoded[6:])
                    if payload.get("error"):
                        chat_history[-1] = {"role": "assistant", "content": payload["error"]}
                        yield chat_history, state_data, gr.update(), ""
                        return
                    token_text = payload.get("token", "")
                    if token_text:
                        full_answer += token_text
                        chat_history[-1] = {"role": "assistant", "content": full_answer + "▍"}
                        yield chat_history, state_data, gr.update(), ""
                    if payload.get("done"):
                        break
        except Exception as e:
            chat_history[-1] = {"role": "assistant", "content": f"❌ 请求失败：{e}"}
            yield chat_history, state_data, gr.update(), ""
            return

        chat_history[-1] = {"role": "assistant", "content": full_answer}
        dd = refresh_dropdown(token)
        yield chat_history, state_data, dd, ""

    msg.submit(
        respond_stream,
        [msg, chatbot, state],
        [chatbot, state, conv_dropdown, msg],
    )


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(primary_hue="blue", neutral_hue="gray", font=gr.themes.GoogleFont("Inter")),
        css=CSS,
        server_port=7860,
    )
