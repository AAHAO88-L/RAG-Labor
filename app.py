"""Gradio 前端 — RAG-Labor 劳动法智能助手"""

import gradio as gr
import os
import json
import uuid
import logging
import requests
import base64

from ui_helpers import (
    build_conv_list_html, build_user_area_html, PWD_MODAL_HTML,
)

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
logger = logging.getLogger(__name__)

def _load_static(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

CSS = _load_static(os.path.join(os.path.dirname(__file__), "static", "style.css"))
HEAD_JS = f"<script>{_load_static(os.path.join(os.path.dirname(__file__), 'static', 'app.js'))}</script>"


def get_headers(token):
    return {"Authorization": f"Bearer {token}"}


EMPTY_STATE = {
    "token": None, "user_id": None, "username": None,
    "current_conv_id": None, "current_title": "新对话",
    "conv_map": {}, "selected_conv_id": None,
}


def fetch_conversations(token):
    if not token or not token.strip():
        return []
    try:
        resp = requests.get(f"{API_BASE}/api/conversations", headers=get_headers(token), timeout=5)
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        logger.warning("获取对话列表失败", exc_info=True)
        return []


def fetch_user_info(token):
    if not token:
        return {}
    try:
        resp = requests.get(f"{API_BASE}/api/me", headers=get_headers(token), timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        logger.warning("获取用户信息失败", exc_info=True)
    return {}


def refresh_sidebar(token, selected_id=None, search_query=""):
    convs = fetch_conversations(token)
    conv_html = build_conv_list_html(convs, selected_id, search_query)
    user_info = fetch_user_info(token)
    user_html = build_user_area_html(
        user_info.get("username", ""), user_info.get("avatar", "")
    )
    return conv_html, user_html


# ── Python callbacks ──

def _auth_request(endpoint, username, password):
    """Login/Register 共用逻辑"""
    if not username or not password:
        return "请填写用户名和密码", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), EMPTY_STATE
    try:
        resp = requests.post(f"{API_BASE}/api/{endpoint}", json={"username": username, "password": password}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            token = data["token"]
            new_state = {**EMPTY_STATE, "token": token, "user_id": data["user_id"], "username": data["username"]}
            conv_html, user_html = refresh_sidebar(token)
            return "", gr.update(visible=False), gr.update(visible=True), conv_html, user_html, gr.update(value=PWD_MODAL_HTML), gr.update(), new_state
        else:
            msg = resp.json().get("detail", f"{endpoint}失败")
            return "❌ " + msg, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), EMPTY_STATE
    except Exception as e:
        return "❌ 连接后端失败：" + str(e), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), EMPTY_STATE


def fn_login(username, password):
    return _auth_request("login", username, password)


def fn_register(username, password):
    return _auth_request("register", username, password)


def fn_logout():
    new_state = {**EMPTY_STATE}
    empty_conv = '<div class="conv-list-wrap"><div class="conv-list"><div class="conv-empty">暂无对话</div></div></div>'
    empty_user = '<div class="user-area-wrap"><div class="user-area-placeholder"></div></div>'
    return (gr.update(visible=True), gr.update(visible=False), [],
            empty_conv, empty_user, gr.update(value=""), gr.update(), new_state)


def fn_conv_selected(conv_id, state_data):
    if not conv_id or not state_data.get("token"):
        return [], state_data, gr.update(), gr.update()
    try:
        resp = requests.get(f"{API_BASE}/api/conversations/{conv_id}",
                            headers=get_headers(state_data["token"]), timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            state_data["current_conv_id"] = conv_id
            state_data["current_title"] = data.get("title", "对话")
            state_data["selected_conv_id"] = conv_id
            conv_html, user_html = refresh_sidebar(state_data["token"], selected_id=conv_id)
            chat_history = data.get("messages", [])
            if not chat_history or not isinstance(chat_history, list):
                chat_history = []
            return chat_history, state_data, conv_html, user_html
    except Exception:
        logger.warning("加载对话失败", exc_info=True)
    return [], state_data, gr.update(), gr.update()


def fn_new_chat(state_data):
    state_data["current_conv_id"] = uuid.uuid4().hex[:12]
    state_data["current_title"] = "新对话"
    conv_html, user_html = refresh_sidebar(state_data.get("token"))
    return [], state_data, conv_html, user_html, gr.update(value="")


def fn_search(query, state_data):
    conv_html, user_html = refresh_sidebar(state_data.get("token"), search_query=query)
    return conv_html, user_html


def fn_change_password(pwd_json, state_data):
    if not pwd_json or not state_data.get("token"):
        return gr.update()
    try:
        data = json.loads(pwd_json)
        resp = requests.post(
            f"{API_BASE}/api/change-password",
            json={"old_password": data["old"], "new_password": data["new"]},
            headers=get_headers(state_data["token"]), timeout=10
        )
        if resp.status_code == 200:
            return gr.update(value=PWD_MODAL_HTML + '<div style="position:fixed;bottom:20px;right:20px;background:#16a34a;color:#fff;padding:10px 20px;border-radius:8px;z-index:10000;font-size:14px;box-shadow:0 2px 12px rgba(0,0,0,0.15);">✅ 密码修改成功</div>')
        else:
            detail = resp.json().get("detail", "修改失败")
            return gr.update(value=PWD_MODAL_HTML + '<div style="position:fixed;bottom:20px;right:20px;background:#dc2626;color:#fff;padding:10px 20px;border-radius:8px;z-index:10000;font-size:14px;box-shadow:0 2px 12px rgba(0,0,0,0.15);">❌ ' + detail + '</div>')
    except Exception as e:
        return gr.update(value=PWD_MODAL_HTML + '<div style="position:fixed;bottom:20px;right:20px;background:#dc2626;color:#fff;padding:10px 20px;border-radius:8px;z-index:10000;font-size:14px;box-shadow:0 2px 12px rgba(0,0,0,0.15);">❌ 请求失败：' + str(e) + '</div>')


def fn_avatar_upload(image_path, state_data):
    if not image_path or not state_data.get("token"):
        return gr.update(), state_data
    try:
        with open(image_path, "rb") as f:
            img_bytes = f.read()
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{b64}"
        resp = requests.post(
            f"{API_BASE}/api/change-avatar",
            json={"avatar_base64": data_url},
            headers=get_headers(state_data["token"]), timeout=10
        )
        if resp.status_code == 200:
            user_html = build_user_area_html(state_data.get("username", ""), data_url)
            return gr.update(value=user_html), state_data
    except Exception:
        logger.warning("上传头像失败", exc_info=True)
    return gr.update(), state_data


def fn_pin_conv(conv_id, state_data):
    if not conv_id or not state_data.get("token"):
        return gr.update(), gr.update()
    try:
        requests.patch(f"{API_BASE}/api/conversations/{conv_id}/pin",
                       headers=get_headers(state_data["token"]), timeout=5)
    except Exception:
        logger.warning("置顶对话失败", exc_info=True)
    conv_html, user_html = refresh_sidebar(state_data["token"], selected_id=state_data.get("selected_conv_id"))
    return conv_html, user_html


def fn_delete_conv(conv_id, state_data):
    if not conv_id or not state_data.get("token"):
        return gr.update(), gr.update(), state_data
    try:
        requests.delete(f"{API_BASE}/api/conversations/{conv_id}",
                        headers=get_headers(state_data["token"]), timeout=5)
    except Exception:
        logger.warning("删除对话失败", exc_info=True)
    if state_data.get("current_conv_id") == conv_id:
        state_data["current_conv_id"] = None
        state_data["current_title"] = "新对话"
    conv_html, user_html = refresh_sidebar(state_data["token"], selected_id=None)
    return conv_html, user_html, state_data


def respond_stream(message, chat_history, state_data):
    if hasattr(state_data, 'value'):
        state_data = state_data.value
    if not message.strip():
        yield chat_history, state_data, gr.update(), gr.update(), ""
        return
    if not state_data.get("token"):
        yield chat_history, state_data, gr.update(), gr.update(), ""
        return

    token = state_data["token"]
    conv_id = state_data.get("current_conv_id") or uuid.uuid4().hex[:12]
    state_data["current_conv_id"] = conv_id

    chat_history.append({"role": "user", "content": message})
    chat_history.append({"role": "assistant", "content": "⏳ 检索中……"})
    yield chat_history, state_data, gr.update(), gr.update(), ""

    full_answer = ""
    low_confidence = False
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
                    yield chat_history, state_data, gr.update(), gr.update(), ""
                    return
                token_text = payload.get("token", "")
                if token_text:
                    full_answer += token_text
                    chat_history[-1] = {"role": "assistant", "content": full_answer + "▍"}
                    yield chat_history, state_data, gr.update(), gr.update(), ""
                if payload.get("done"):
                    if payload.get("low_confidence"):
                        low_confidence = True
                    break
    except Exception as e:
        chat_history[-1] = {"role": "assistant", "content": "❌ 请求失败：" + str(e)}
        yield chat_history, state_data, gr.update(), gr.update(), ""
        return

    if low_confidence:
        full_answer = "⚠️ *注意：以下回答的匹配度较低，部分内容可能来自模型自身知识，仅供参考。*\n\n" + full_answer
    chat_history[-1] = {"role": "assistant", "content": full_answer}
    conv_html, user_html = refresh_sidebar(token, selected_id=conv_id)
    yield chat_history, state_data, conv_html, user_html, ""


# ── UI ──

with gr.Blocks(title="劳动法智能助手", fill_height=True) as demo:

    state = gr.State({**EMPTY_STATE})

    with gr.Column(visible=True, elem_id="login-panel") as login_panel:
        gr.HTML('<div style="text-align:center;padding:40px 0 20px;"><h1 style="font-size:28px;font-weight:600;">劳动法智能助手</h1><p style="color:#888;">登录或注册以继续</p></div>')
        with gr.Row(equal_height=True):
            with gr.Column(scale=1): pass
            with gr.Column(scale=2, min_width=320):
                username_input = gr.Textbox(label="用户名", placeholder="请输入用户名")
                password_input = gr.Textbox(label="密码", placeholder="请输入密码", type="password")
                with gr.Row():
                    login_btn = gr.Button("登录", variant="primary", scale=1)
                    register_btn = gr.Button("注册", variant="secondary", scale=1)
                login_msg = gr.HTML('')
            with gr.Column(scale=1): pass

    with gr.Column(visible=False, elem_id="main-panel") as main_panel:
        with gr.Row(elem_id="main-layout"):
            with gr.Column(elem_id="sidebar", scale=0):
                gr.HTML('<div class="sidebar-spacer"></div>')
                gr.HTML('<div class="sidebar-new-btn-wrap">')
                new_chat_btn = gr.Button("+ 新建对话", variant="secondary", size="sm", elem_classes="sidebar-new-btn")
                gr.HTML('</div>')
                search_input = gr.Textbox(placeholder="搜索历史对话...", show_label=False, container=False, max_lines=1, elem_classes="sidebar-search")
                conv_list = gr.HTML(
                    '<div class="conv-list-wrap"><div class="conv-list"><div class="conv-empty">暂无对话</div></div></div>',
                    elem_id="conv-list-box")
                user_area = gr.HTML('<div class="user-area-wrap"><div class="user-area-placeholder"></div></div>')

            with gr.Column(elem_id="main-content", scale=1):
                pwd_modal = gr.HTML("")
                chatbot = gr.Chatbot(height="100%", layout="bubble",
                                     placeholder="开始向劳动法智能助手提问...", scale=1, elem_id="main-chat")
                msg = gr.Textbox(
                    placeholder="请输入您的劳动法问题...",
                    show_label=False, container=True, scale=0, elem_id="input-box",
                )

        conv_trigger = gr.Textbox(visible=True, elem_id="h-conv", elem_classes="hidden-trigger")
        conv_trigger_btn = gr.Button("_sel", visible=True, elem_id="h-conv-btn", elem_classes="hidden-trigger")
        pin_trigger = gr.Textbox(visible=True, elem_id="h-pin", elem_classes="hidden-trigger")
        pin_trigger_btn = gr.Button("_pin", visible=True, elem_id="h-pin-btn", elem_classes="hidden-trigger")
        del_trigger = gr.Textbox(visible=True, elem_id="h-del", elem_classes="hidden-trigger")
        del_trigger_btn = gr.Button("_del", visible=True, elem_id="h-del-btn", elem_classes="hidden-trigger")
        pwd_trigger = gr.Textbox(visible=True, elem_id="h-pwd", elem_classes="hidden-trigger")
        pwd_trigger_btn = gr.Button("_pwd", visible=True, elem_id="h-pwd-btn", elem_classes="hidden-trigger")
        avatar_upload = gr.Image(type="filepath", visible=True, elem_id="h-avatar", elem_classes="hidden-trigger")
        _h_logout = gr.Button("_logout", visible=True, elem_id="h-logout", elem_classes="hidden-trigger")

    login_btn.click(fn_login, [username_input, password_input],
                    [login_msg, login_panel, main_panel, conv_list, user_area, pwd_modal, chatbot, state])
    register_btn.click(fn_register, [username_input, password_input],
                       [login_msg, login_panel, main_panel, conv_list, user_area, pwd_modal, chatbot, state])
    _h_logout.click(fn_logout, None,
                    [login_panel, main_panel, chatbot, conv_list, user_area, pwd_modal, msg, state])
    conv_trigger_btn.click(fn_conv_selected, [conv_trigger, state],
                           [chatbot, state, conv_list, user_area],
                           js="(c, s) => { var v = window._selConvId || ''; window._selConvId = ''; return [v, s]; }")
    pin_trigger_btn.click(fn_pin_conv, [pin_trigger, state],
                          [conv_list, user_area],
                          js="(c, s) => { var v = window._pinConvId || ''; window._pinConvId = ''; return [v, s]; }")
    del_trigger_btn.click(fn_delete_conv, [del_trigger, state],
                          [conv_list, user_area, state],
                          js="(c, s) => { var v = window._delConvId || ''; window._delConvId = ''; return [v, s]; }")
    new_chat_btn.click(fn_new_chat, [state],
                       [chatbot, state, conv_list, user_area, search_input])
    search_input.change(fn_search, [search_input, state], [conv_list, user_area])
    pwd_trigger_btn.click(fn_change_password, [pwd_trigger, state], [pwd_modal],
                          js="(p, s) => { var v = window._pwdData || ''; window._pwdData = ''; return [v, s]; }")
    avatar_upload.upload(fn_avatar_upload, [avatar_upload, state], [user_area, state])
    msg.submit(respond_stream, [msg, chatbot, state],
               [chatbot, state, conv_list, user_area, msg])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo.launch(
        head=HEAD_JS,
        theme=gr.themes.Soft(primary_hue="blue", neutral_hue="gray", font=gr.themes.GoogleFont("Inter")),
        css=CSS,
        server_port=7860,
    )
