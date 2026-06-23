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
    if (!confirm('确定要删除这条对话吗？')) return;
    window._delConvId = convId;
    document.getElementById('h-del-btn')?.click();
}

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
