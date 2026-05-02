/* Mini Agent · Web Frontend */
(() => {
  'use strict';

  // ---------- DOM ----------
  const $ = (id) => document.getElementById(id);
  const apiBaseInput = $('apiBase');
  const statusDot    = $('statusDot');
  const codeArea     = $('codeArea');
  const promptInput  = $('promptInput');
  const sendBtn      = $('sendBtn');
  const sendBtnText  = $('sendBtnText');
  const runCodeBtn   = $('runCodeBtn');
  const clearCodeBtn = $('clearCodeBtn');
  const clearChatBtn = $('clearChatBtn');
  const clearTermBtn = $('clearTermBtn');
  const chatList     = $('chatList');
  const terminal     = $('terminal');
  const metaInfo     = $('metaInfo');

  // ---------- Helpers ----------
  const apiBase = () => apiBaseInput.value.trim().replace(/\/$/, '');
  const escapeHtml = (s) =>
    String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

  const scrollToBottom = (el) => { el.scrollTop = el.scrollHeight; };

  // ---------- Chat ----------
  function appendChat(role, htmlContent, opts = {}) {
    const wrap = document.createElement('div');
    wrap.className = `chat-msg ${role}`;
    const iconMap = { user: 'user', assistant: 'sparkles' };
    wrap.innerHTML = `
      <div class="avatar"><i class="lucide lucide-${iconMap[role] || 'circle'}"></i></div>
      <div class="bubble ${opts.error ? 'error' : ''}">${htmlContent}</div>
    `;
    chatList.appendChild(wrap);
    scrollToBottom(chatList);
    return wrap;
  }

  // ---------- Terminal ----------
  function clearTerminal() { terminal.innerHTML = ''; metaInfo.textContent = ''; }

  function writeTerm(html) {
    terminal.insertAdjacentHTML('beforeend', html);
    scrollToBottom(terminal);
  }

  function renderResult(result, opts = {}) {
    const { stdout, stderr, exit_code, duration_ms, timeout, success, truncated } = result || {};
    const cmdLabel = opts.label || 'run';
    writeTerm(`<span class="term-cmd">$ ${escapeHtml(cmdLabel)}</span>\n`);

    if (stdout && stdout.length) {
      writeTerm(`<span class="term-out">${escapeHtml(stdout)}</span>${stdout.endsWith('\n') ? '' : '\n'}`);
    }
    if (stderr && stderr.length) {
      writeTerm(`<span class="term-err">${escapeHtml(stderr)}</span>${stderr.endsWith('\n') ? '' : '\n'}`);
    }
    if (timeout) {
      writeTerm(`<span class="term-warn">[!] 执行超时</span>\n`);
    }
    if (truncated) {
      writeTerm(`<span class="term-warn">[!] 输出已截断</span>\n`);
    }
    const meta = `[exit=${exit_code ?? 'N/A'}] [duration=${duration_ms ?? '?'}ms] [success=${!!success}]`;
    writeTerm(`<span class="term-meta">${escapeHtml(meta)}</span>\n\n`);
    metaInfo.textContent = meta;
  }

  // ---------- API ----------
  async function postJSON(path, body) {
    const res = await fetch(apiBase() + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
    if (!res.ok) {
      const err = new Error(data?.detail || `HTTP ${res.status}`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  async function checkHealth() {
    try {
      const res = await fetch(apiBase() + '/api/health');
      statusDot.classList.toggle('ok', res.ok);
      statusDot.classList.toggle('err', !res.ok);
      statusDot.title = res.ok ? '后端在线' : `后端异常 (${res.status})`;
    } catch {
      statusDot.classList.remove('ok');
      statusDot.classList.add('err');
      statusDot.title = '无法连接后端';
    }
  }

  // ---------- Actions ----------
  function setSending(on) {
    sendBtn.disabled = on;
    runCodeBtn.disabled = on;
    if (on) {
      sendBtnText.innerHTML = 'AI 思考并执行中<span class="loading-dots"></span>';
    } else {
      sendBtnText.textContent = '一键发送并执行';
    }
  }

  function setRunning(on) {
    runCodeBtn.disabled = on;
    sendBtn.disabled = on;
    runCodeBtn.innerHTML = on
      ? '<i class="lucide lucide-loader"></i> 运行中...'
      : '<i class="lucide lucide-play"></i> 仅运行代码';
  }

  async function handleSend() {
    const prompt = promptInput.value.trim();
    if (!prompt) {
      promptInput.focus();
      return;
    }
    appendChat('user', escapeHtml(prompt));
    promptInput.value = '';
    const thinking = appendChat('assistant', '正在调用 DeepSeek 生成代码并在沙盒中执行<span class="loading-dots"></span>');
    setSending(true);

    try {
      const data = await postJSON('/api/chat_and_run', {
        prompt,
        timeout_ms: 10000,
      });
      // 1) 填充代码
      codeArea.value = data.code || '';
      // 2) 渲染终端
      renderResult(data.result, { label: `python main.py  # session=${data.session_id}` });
      // 3) 更新对话
      const ok = data.result?.success;
      thinking.querySelector('.bubble').innerHTML =
        `已生成 <strong>${(data.code || '').split('\n').length}</strong> 行 Python 代码并执行完毕（` +
        `<span style="color:${ok ? 'var(--success)' : 'var(--danger)'}">` +
        `${ok ? '成功' : '失败'}</span>，用时 ${data.result?.duration_ms ?? '?'} ms）。` +
        `<br/><small style="color:var(--text-dim)">模型: ${escapeHtml(data.model || '')}</small>`;
    } catch (err) {
      thinking.querySelector('.bubble').classList.add('error');
      thinking.querySelector('.bubble').innerHTML =
        `❌ 请求失败: ${escapeHtml(err.message)}`;
      writeTerm(`<span class="term-err">[ERROR] ${escapeHtml(err.message)}</span>\n\n`);
    } finally {
      setSending(false);
    }
  }

  async function handleRunCodeOnly() {
    const code = codeArea.value;
    if (!code.trim()) {
      appendChat('assistant', '⚠️ 左侧编辑器为空，无代码可运行。', { error: true });
      return;
    }
    setRunning(true);
    writeTerm(`<span class="term-hint">$ 提交左侧代码到 /api/run_code ...</span>\n`);
    try {
      const data = await postJSON('/api/run_code', {
        code,
        filename: 'main.py',
        command: 'python',
        timeout_ms: 10000,
      });
      renderResult(data.result, { label: `python main.py  # session=${data.session_id}` });
    } catch (err) {
      writeTerm(`<span class="term-err">[ERROR] ${escapeHtml(err.message)}</span>\n\n`);
    } finally {
      setRunning(false);
    }
  }

  // ---------- Events ----------
  sendBtn.addEventListener('click', handleSend);
  runCodeBtn.addEventListener('click', handleRunCodeOnly);
  clearCodeBtn.addEventListener('click', () => { codeArea.value = ''; });
  clearChatBtn.addEventListener('click', () => { chatList.innerHTML = ''; });
  clearTermBtn.addEventListener('click', clearTerminal);
  apiBaseInput.addEventListener('change', checkHealth);

  promptInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  });

  // Tab 在 textarea 内插入空格
  codeArea.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = codeArea.selectionStart;
      const end = codeArea.selectionEnd;
      codeArea.value = codeArea.value.slice(0, start) + '    ' + codeArea.value.slice(end);
      codeArea.selectionStart = codeArea.selectionEnd = start + 4;
    }
  });

  // 初始化
  checkHealth();
  setInterval(checkHealth, 10000);
})();
