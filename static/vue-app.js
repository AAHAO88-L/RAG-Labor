// 劳动法智能助手 — Vue 3 应用
const { createApp, ref, computed, nextTick } = Vue;

createApp({
  setup() {
    // ─── 认证 ───
    const token = ref(localStorage.getItem('token') || '');
    const username = ref(localStorage.getItem('username') || '');
    const avatarBase64 = ref(localStorage.getItem('avatar') || '');
    const loginUsername = ref('');
    const loginPassword = ref('');
    const loginMsg = ref('');

    const isLoggedIn = computed(() => !!token.value);
    const avatarSrc = computed(() => {
      if (avatarBase64.value) return avatarBase64.value;
      if (!username.value) return '';
      const initial = username.value[0].toUpperCase();
      return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='16' fill='%234569d6'/%3E%3Ctext x='16' y='21' text-anchor='middle' fill='white' font-size='16' font-weight='600'%3E${initial}%3C/text%3E%3C/svg%3E`;
    });

    function getHeaders() {
      return { 'Authorization': `Bearer ${token.value}`, 'Content-Type': 'application/json' };
    }

    async function doAuth(endpoint) {
      loginMsg.value = '';
      if (!loginUsername.value || !loginPassword.value) {
        loginMsg.value = '请填写用户名和密码';
        return;
      }
      try {
        const resp = await fetch(`/api/${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: loginUsername.value, password: loginPassword.value }),
        });
        if (resp.ok) {
          const data = await resp.json();
          token.value = data.token;
          username.value = data.username;
          localStorage.setItem('token', data.token);
          localStorage.setItem('username', data.username);
          loginUsername.value = '';
          loginPassword.value = '';
          loginMsg.value = '';
          loadConversations();
          loadUserInfo();
        } else {
          const err = await resp.json();
          loginMsg.value = '❌ ' + (err.detail || endpoint + '失败');
        }
      } catch (e) {
        loginMsg.value = '❌ 连接后端失败：' + e.message;
      }
    }

    function login() { return doAuth('login'); }
    function register() { return doAuth('register'); }

    function logout() {
      token.value = ''; username.value = ''; avatarBase64.value = '';
      localStorage.removeItem('token'); localStorage.removeItem('username'); localStorage.removeItem('avatar');
      conversations.value = []; messages.value = [];
      selectedConvId.value = null; currentConvId.value = null;
      sources.value = []; reviewContractId.value = null; reviewContractName.value = '';
      searchQuery.value = '';
    }

    async function loadUserInfo() {
      if (!token.value) return;
      try {
        const resp = await fetch(`/api/me`, { headers: getHeaders() });
        if (resp.ok) {
          const data = await resp.json();
          if (data.avatar) { avatarBase64.value = data.avatar; localStorage.setItem('avatar', data.avatar); }
        }
      } catch (_) {}
    }

    // ─── 密码修改 ───
    const showPwdModal = ref(false);
    const pwdOld = ref('');
    const pwdNew = ref('');
    const pwdConfirm = ref('');
    const pwdError = ref('');
    const pwdSuccess = ref('');

    function submitPwd() {
      pwdError.value = ''; pwdSuccess.value = '';
      if (!pwdOld.value || !pwdNew.value) { pwdError.value = '请填写所有字段'; return; }
      if (pwdNew.value !== pwdConfirm.value) { pwdError.value = '两次密码不一致'; return; }
      if (pwdNew.value.length < 4) { pwdError.value = '新密码至少4位'; return; }
      fetch(`/api/change-password`, {
        method: 'POST', headers: getHeaders(),
        body: JSON.stringify({ old_password: pwdOld.value, new_password: pwdNew.value }),
      }).then(r => {
        if (r.ok) {
          pwdSuccess.value = '✅ 密码修改成功';
          pwdOld.value = ''; pwdNew.value = ''; pwdConfirm.value = '';
          setTimeout(() => { showPwdModal.value = false; pwdSuccess.value = ''; }, 1500);
        } else {
          r.json().then(d => { pwdError.value = '❌ ' + (d.detail || '修改失败'); });
        }
      }).catch(e => { pwdError.value = '❌ 请求失败：' + e.message; });
    }

    // ─── 用户菜单 ───
    const userMenuOpen = ref(false);

    // ─── 对话管理 ───
    const conversations = ref([]);
    const selectedConvId = ref(null);
    const currentConvId = ref(null);
    const searchQuery = ref('');
    let searchTimer = null;

    const filteredConversations = computed(() => {
      let list = conversations.value;
      if (searchQuery.value) {
        const q = searchQuery.value.toLowerCase();
        list = list.filter(c => c.title.toLowerCase().includes(q) || (c.summary || '').toLowerCase().includes(q));
      }
      return [...list].sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        return b.mtime - a.mtime;
      });
    });

    async function loadConversations() {
      if (!token.value) return;
      try {
        const resp = await fetch(`/api/conversations`, { headers: getHeaders() });
        if (resp.ok) conversations.value = await resp.json();
      } catch (_) {}
    }

    function searchConversations() {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(loadConversations, 300);
    }

    async function selectConversation(convId) {
      if (!token.value) return;
      try {
        const resp = await fetch(`/api/conversations/${convId}`, { headers: getHeaders() });
        if (resp.ok) {
          const data = await resp.json();
          currentConvId.value = convId;
          selectedConvId.value = convId;
          messages.value = data.messages || [];
          sources.value = [];
          // 只更新选中状态，不重新排序列表避免闪烁
          nextTick(scrollToBottom);
        }
      } catch (_) {}
    }

    function newChat() {
      currentConvId.value = null; selectedConvId.value = null;
      messages.value = []; sources.value = []; searchQuery.value = '';
      loadConversations();
    }

    async function pinConversation(convId) {
      if (!token.value) return;
      try { await fetch(`/api/conversations/${convId}/pin`, { method: 'PATCH', headers: getHeaders() }); loadConversations(); } catch (_) {}
    }

    const showDelModal = ref(false);
    const delTarget = ref(null);

    async function confirmDelete() {
      const id = delTarget.value;
      if (!id || !token.value) return;
      try { await fetch(`/api/conversations/${id}`, { method: 'DELETE', headers: getHeaders() }); } catch (_) {}
      if (currentConvId.value === id) { currentConvId.value = null; selectedConvId.value = null; messages.value = []; }
      delTarget.value = null; showDelModal.value = false;
      loadConversations();
    }

    // ─── 聊天 ───
    const messages = ref([]);
    const inputMessage = ref('');
    const isStreaming = ref(false);
    const sources = ref([]);
    const chatContainer = ref(null);

    function scrollToBottom() {
      const el = chatContainer.value;
      if (el) el.scrollTop = el.scrollHeight;
    }

    function truncate(text, n) {
      return text && text.length > n ? text.slice(0, n) + '…' : text;
    }

    function timeAgo(ts) {
      const diff = Date.now() / 1000 - ts;
      if (diff < 60) return '刚刚';
      if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
      if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
      if (diff < 172800) return '昨天';
      const d = new Date(ts * 1000);
      return String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    function renderContent(text) {
      if (!text) return '';
      // 分离反馈按钮 HTML（在末尾，以 <div class="feedback-btns" 开头）
      const fbMatch = text.match(/\n\n(<div class="feedback-btns" data-conv="[^"]+">[\s\S]*)$/);
      let main = text;
      let fbHtml = '';
      if (fbMatch) {
        main = text.slice(0, fbMatch.index);
        fbHtml = fbMatch[1];
      }
      // 文本转义 + 格式处理
      let html = main.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      return html + fbHtml;
    }

    async function sendMessage() {
      const msg = inputMessage.value.trim();
      if (!msg || isStreaming.value || !token.value) return;
      inputMessage.value = '';

      if (!currentConvId.value) {
        currentConvId.value = Math.random().toString(16).slice(2, 14);
      }

      // 健康检查
      try {
        const hr = await fetch(`/api/health`, { headers: getHeaders() });
        if (hr.ok) {
          const hd = await hr.json();
          if (!hd.model_ready) {
            messages.value.push({ role: 'user', content: msg }, { role: 'assistant', content: '⏳ 模型正在后台加载（约需15秒），请稍候重试……' });
            nextTick(scrollToBottom);
            return;
          }
        }
      } catch (_) {}

      messages.value.push({ role: 'user', content: msg });
      sources.value = [];
      isStreaming.value = true;
      nextTick(scrollToBottom);

      try {
        const resp = await fetch(`/api/query`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token.value}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conv_id: currentConvId.value,
            message: msg,
            history: messages.value.slice(0, -1),
            ...(reviewContractId.value ? { contract_id: reviewContractId.value } : {}),
          }),
        });
        if (!resp.ok) {
          messages.value.push({ role: 'assistant', content: '❌ 请求失败' });
          isStreaming.value = false;
          nextTick(scrollToBottom);
          return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullAnswer = '';
        let lowConfidence = false;
        let sourcesData = [];
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.sources) {
                sourcesData = payload.sources;
                sources.value = sourcesData.map(s => ({ ...s, _open: false }));
                continue;
              }
              if (payload.error) {
                const last = messages.value[messages.value.length - 1];
                if (last && last.role === 'assistant') last.content = payload.error;
                else messages.value.push({ role: 'assistant', content: payload.error });
                isStreaming.value = false;
                nextTick(scrollToBottom);
                return;
              }
              if (payload.token) {
                fullAnswer += payload.token;
                const last = messages.value[messages.value.length - 1];
                if (last && last.role === 'assistant') last.content = fullAnswer;
                else messages.value.push({ role: 'assistant', content: fullAnswer });
                nextTick(scrollToBottom);
              }
              if (payload.done) {
                lowConfidence = !!payload.low_confidence;
                if (payload.sources) sourcesData = payload.sources;
              }
            } catch (_) {}
          }
        }

        // 处理残余 buffer
        if (buffer.startsWith('data: ')) {
          try {
            const p = JSON.parse(buffer.slice(6));
            if (p.token) fullAnswer += p.token;
            if (p.low_confidence) lowConfidence = true;
            if (p.sources) sourcesData = p.sources;
          } catch (_) {}
        }

        if (lowConfidence) {
          fullAnswer = '⚠️ *注意：以下回答的匹配度较低，部分内容可能来自模型自身知识，仅供参考。*\n\n' + fullAnswer;
        }
        fullAnswer += '\n\n' + buildFeedbackHtml(currentConvId.value);

        const last = messages.value[messages.value.length - 1];
        if (last && last.role === 'assistant') last.content = fullAnswer;
        else messages.value.push({ role: 'assistant', content: fullAnswer });

        sources.value = sourcesData.map(s => ({ ...s, _open: false }));
        // 发送后只刷新列表，不重置选中
        const wasSelected = selectedConvId.value;
        loadConversations().then(() => {
          // 保持当前选中的对话高亮
        });
      } catch (e) {
        messages.value.push({ role: 'assistant', content: '❌ 请求失败：' + e.message });
      }
      isStreaming.value = false;
      nextTick(scrollToBottom);
    }

    function buildFeedbackHtml(convId) {
      return `<div class="feedback-btns" data-conv="${convId}">
        <button class="fb-btn fb-up" data-rating="1" title="有帮助">👍</button>
        <button class="fb-btn fb-down" data-rating="-1" title="没有帮助">👎</button>
      </div>`;
    }

    // ─── 反馈（全局事件委托）───
    document.addEventListener('click', function(e) {
      const btn = e.target.closest('.fb-btn');
      if (!btn) return;
      const container = btn.closest('.feedback-btns');
      if (!container) return;
      const rating = parseInt(btn.dataset.rating, 10);
      const convId = container.dataset.conv;
      container.querySelectorAll('.fb-btn').forEach(b => b.disabled = true);
      btn.classList.add('active');
      fetch(`/api/feedback`, {
        method: 'POST', headers: { 'Authorization': `Bearer ${token.value}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: convId, message_index: 0, rating, query_text: '', answer_text: '', sources_json: '', comment: '' }),
      }).catch(() => {});
    });

    // ─── 点击外部关闭用户菜单 ───
    document.addEventListener('click', function(e) {
      const dd = document.getElementById('user-dropdown');
      const trigger = document.querySelector('.user-trigger');
      if (dd && trigger && !dd.contains(e.target) && !trigger.contains(e.target)) {
        userMenuOpen.value = false;
      }
    });

    // ─── 文档管理 ───
    const uploadStatus = ref('');
    const documents = ref([]);
    const docListVisible = ref(false);

    function triggerFileUpload() {
      const el = document.getElementById('h-file-upload');
      if (el) el.click();
    }

    async function uploadDoc(e) {
      const file = e.target.files[0];
      if (!file || !token.value) return;
      // 前端文件大小校验（后端上限 100MB）
      if (file.size > 100 * 1024 * 1024) {
        uploadStatus.value = '❌ 文件过大，上限为 100MB';
        e.target.value = '';
        setTimeout(() => { uploadStatus.value = ''; }, 3000);
        return;
      }
      uploadStatus.value = '上传中...';
      const fd = new FormData(); fd.append('file', file);
      try {
        const resp = await fetch(`/api/upload-doc`, {
          method: 'POST', headers: { 'Authorization': `Bearer ${token.value}` }, body: fd,
        });
        if (resp.ok) {
          const data = await resp.json();
          uploadStatus.value = `✅ ${data.filename} 已导入（${data.chunks} 个片段）`;
          loadDocuments();
        } else {
          const err = await resp.json();
          uploadStatus.value = '❌ ' + (err.detail || '上传失败');
        }
      } catch (e) { uploadStatus.value = '❌ 上传失败：' + e.message; }
      e.target.value = '';
      setTimeout(() => { uploadStatus.value = ''; }, 3000);
    }

    async function loadDocuments() {
      if (!token.value) return;
      try {
        const resp = await fetch(`/api/documents`, { headers: getHeaders() });
        if (resp.ok) { const d = await resp.json(); documents.value = d.documents || []; }
      } catch (_) {}
    }

    function toggleDocList() {
      docListVisible.value = !docListVisible.value;
      if (docListVisible.value) loadDocuments();
    }

    async function deleteDoc(path) {
      if (!confirm('确定从知识库中删除该文件吗？')) return;
      try {
        const resp = await fetch(`/api/documents?path=${encodeURIComponent(path)}`, { method: 'DELETE', headers: getHeaders() });
        if (resp.ok) { loadDocuments(); } else { const err = await resp.json(); alert('❌ ' + (err.detail || '删除失败')); }
      } catch (e) { alert('❌ 删除失败：' + e.message); }
    }

    // ─── 合同管理 ───
    const contractStatus = ref('');
    const contracts = ref([]);
    const contractListVisible = ref(false);
    const reviewContractId = ref(null);
    const reviewContractName = ref('');

    function triggerContractUpload() {
      const el = document.getElementById('h-contract-upload');
      if (el) el.click();
    }

    async function uploadContract(e) {
      const file = e.target.files[0];
      if (!file || !token.value) return;
      if (file.size > 100 * 1024 * 1024) {
        contractStatus.value = '❌ 文件过大，上限为 100MB';
        e.target.value = '';
        setTimeout(() => { contractStatus.value = ''; }, 3000);
        return;
      }
      contractStatus.value = '上传中...';
      const fd = new FormData(); fd.append('file', file);
      try {
        const resp = await fetch(`/api/contracts/upload`, {
          method: 'POST', headers: { 'Authorization': `Bearer ${token.value}` }, body: fd,
        });
        if (resp.ok) {
          const data = await resp.json();
          contractStatus.value = `✅ ${data.filename} 已上传`;
          loadContracts();
        } else {
          const err = await resp.json();
          contractStatus.value = '❌ ' + (err.detail || '上传失败');
        }
      } catch (e) { contractStatus.value = '❌ 上传失败：' + e.message; }
      e.target.value = '';
      setTimeout(() => { contractStatus.value = ''; }, 3000);
    }

    async function loadContracts() {
      if (!token.value) return;
      try {
        const resp = await fetch(`/api/contracts`, { headers: getHeaders() });
        if (resp.ok) { const d = await resp.json(); contracts.value = d.contracts || []; }
      } catch (_) {}
    }

    function toggleContractList() {
      contractListVisible.value = !contractListVisible.value;
      if (contractListVisible.value) loadContracts();
    }

    async function selectContract(contractId) {
      reviewContractId.value = contractId;
      try {
        const resp = await fetch(`/api/contracts/${contractId}`, { headers: getHeaders() });
        if (resp.ok) { const d = await resp.json(); reviewContractName.value = d.filename; }
      } catch (_) {}
      newChat();
      loadContracts();
    }

    function endReview() {
      reviewContractId.value = null; reviewContractName.value = '';
      newChat();
    }

    // ─── 头像上传 ───
    function triggerAvatarUpload() {
      const el = document.getElementById('h-avatar-upload');
      if (el) el.click();
      userMenuOpen.value = false;
    }

    async function uploadAvatar(e) {
      const file = e.target.files[0];
      if (!file || !token.value) return;
      const reader = new FileReader();
      reader.onload = async function(ev) {
        const dataUrl = ev.target.result;
        try {
          const resp = await fetch(`/api/change-avatar`, {
            method: 'POST', headers: getHeaders(),
            body: JSON.stringify({ avatar_base64: dataUrl }),
          });
          if (resp.ok) { avatarBase64.value = dataUrl; localStorage.setItem('avatar', dataUrl); }
        } catch (_) {}
      };
      reader.readAsDataURL(file);
      e.target.value = '';
    }

    // ─── 初始化 ───
    if (token.value) { loadConversations(); loadUserInfo(); }

    return {
      isLoggedIn, loginUsername, loginPassword, loginMsg,
      login, register, logout,
      username, avatarSrc, userMenuOpen,
      showPwdModal, pwdOld, pwdNew, pwdConfirm, pwdError, pwdSuccess, submitPwd,
      conversations, filteredConversations, selectedConvId, currentConvId,
      searchQuery, searchConversations, selectConversation, newChat,
      pinConversation, confirmDelete, showDelModal, delTarget,
      messages, inputMessage, isStreaming, sources, chatContainer,
      sendMessage, truncate, timeAgo, renderContent,
      uploadStatus, documents, docListVisible, triggerFileUpload, uploadDoc, toggleDocList, deleteDoc,
      contractStatus, contracts, contractListVisible,
      reviewContractId, reviewContractName,
      triggerContractUpload, uploadContract, toggleContractList,
      selectContract, endReview,
      triggerAvatarUpload, uploadAvatar,
    };
  },
}).mount('#app');
