function selectConv(id) {
    document.querySelectorAll('.conv-item').forEach(function(el) { el.classList.remove('selected'); });
    var item = document.querySelector('.conv-item[data-id="' + id + '"]');
    if (item) item.classList.add('selected');
    window._selConvId = id;
    document.getElementById('h-conv-btn')?.click();
}

function doLogout() {
    document.getElementById('h-logout')?.click();
}

function toggleUserMenu() {
    var dd = document.getElementById('user-dropdown');
    var area = document.querySelector('.user-area');
    dd.classList.toggle('open');
    if (area) area.classList.toggle('menu-open');
}

document.addEventListener('click', function(e) {
    var dd = document.getElementById('user-dropdown');
    var trigger = document.querySelector('.user-trigger');
    if (dd && trigger && !dd.contains(e.target) && !trigger.contains(e.target)) {
        dd.classList.remove('open');
    }
});

function pinConv(e, convId) {
    e.stopPropagation();
    window._pinConvId = convId;
    document.getElementById('h-pin-btn')?.click();
}

function deleteConv(e, convId) {
    e.stopPropagation();
    window._delConvId = convId;
    document.getElementById('del-overlay').classList.add('show');
}

function hideDelConfirm() {
    document.getElementById('del-overlay').classList.remove('show');
    window._delConvId = '';
}

function confirmDelConv() {
    if (!window._delConvId) return;
    document.getElementById('del-overlay').classList.remove('show');
    document.getElementById('h-del-btn').click();
}

// 点击遮罩背景关闭删除弹窗
document.addEventListener('click', function(e) {
    if (e.target.id === 'del-overlay') hideDelConfirm();
});

function showPwdForm() {
    document.getElementById('pwd-overlay').classList.add('show');
    document.getElementById('pwd-err-msg').style.display = 'none';
    document.getElementById('pwd-suc-msg').style.display = 'none';
    document.getElementById('pwd-old').value = '';
    document.getElementById('pwd-new').value = '';
    document.getElementById('pwd-confirm').value = '';
}
function hidePwdForm() {
    document.getElementById('pwd-overlay').classList.remove('show');
}

function submitPwd() {
    var oldPwd = document.getElementById('pwd-old').value.trim();
    var newPwd = document.getElementById('pwd-new').value.trim();
    var confirmPwd = document.getElementById('pwd-confirm').value.trim();
    var errEl = document.getElementById('pwd-err-msg');
    var sucEl = document.getElementById('pwd-suc-msg');
    errEl.style.display = 'none';
    sucEl.style.display = 'none';
    if (!oldPwd || !newPwd) { errEl.textContent = '请填写所有字段'; errEl.style.display = 'block'; return; }
    if (newPwd !== confirmPwd) { errEl.textContent = '两次密码不一致'; errEl.style.display = 'block'; return; }
    if (newPwd.length < 4) { errEl.textContent = '新密码至少4位'; errEl.style.display = 'block'; return; }
    try {
        window._pwdData = JSON.stringify({old: oldPwd, new: newPwd});
        document.getElementById('h-pwd-btn')?.click();
        hidePwdForm();
    } catch(e) {
        errEl.textContent = '操作失败，请重试'; errEl.style.display = 'block';
    }
}

function triggerUpload() {
    var el = document.querySelector('#h-upload input[type=file]');
    if (el) el.click();
}

function showDocList() {
    var el = document.getElementById('doc-list-html');
    if (!el) return;
    var inner = document.getElementById('doc-list-inner');
    if (inner && inner.style.display !== 'none') {
        inner.style.display = 'none';
    }
}

function showContractList() {
    var el = document.getElementById('contract-list-html');
    if (!el) return;
    var inner = document.getElementById('contract-list-inner');
    if (inner && inner.style.display !== 'none') {
        inner.style.display = 'none';
    }
}

function deleteDoc(path) {
    if (!confirm('确定从知识库中删除该文件吗？')) return;
    var el = document.getElementById('h-doc-del');
    if (!el) return;
    // 通过 Gradio hidden trigger 传递删除路径
    window._delDocPath = path;
    // 设置 value 并触发 submit
    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeInputValueSetter.call(el, path);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    // Gradio file/textbox submit 触发变化
    setTimeout(function() {
        // 刷新文档列表
        var btn = document.querySelector('.sidebar-upload-btn[onclick*="showDocList"]');
        if (btn) btn.click();
    }, 1000);
}

// ── 合同审查 ──

function selectContract(id) {
    document.querySelectorAll('.contract-item').forEach(function(el) { el.classList.remove('selected'); });
    var item = document.querySelector('.contract-item[data-id="' + id + '"]');
    if (item) item.classList.add('selected');
    window._selContractId = id;
    document.getElementById('h-contract-btn')?.click();
}

function triggerContractUpload() {
    var el = document.querySelector('#h-contract-upload input[type=file]');
    if (el) el.click();
}

function endReview() {
    window._endReview = '1';
    document.getElementById('h-contract-btn')?.click();
}

// ── 来源面板折叠 ──

document.addEventListener('click', function(e) {
    var header = e.target.closest('.source-header');
    if (header) {
        var body = header.nextElementSibling;
        var toggle = header.querySelector('.source-toggle');
        if (body) body.classList.toggle('open');
        if (toggle) toggle.classList.toggle('open');
    }
});

// ── 点赞/踩 ──

document.addEventListener('click', function(e) {
    var btn = e.target.closest('.fb-btn');
    if (!btn) return;
    var container = btn.closest('.feedback-btns');
    if (!container) return;
    var rating = parseInt(btn.dataset.rating, 10);
    var convId = container.dataset.conv;

    // 禁用所有按钮
    container.querySelectorAll('.fb-btn').forEach(function(b) { b.disabled = true; });
    btn.classList.add('active');

    // 获取最后一条消息的 query_text 和 answer_text
    // 因为 feedback-btns 是助手消息的一部分，需要从 Gradio 组件中获取当前会话信息
    window._feedbackData = JSON.stringify({
        conversation_id: convId,
        message_index: 0,
        rating: rating,
        query_text: '',
        answer_text: '',
        sources_json: '',
        comment: ''
    });
    document.getElementById('h-feedback-btn')?.click();
});
