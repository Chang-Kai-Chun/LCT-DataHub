/* ==========================================================================
   lct. 介面原型的互動（純 JS，不接 API）
   - 主題切換：記在 localStorage，沒有記錄時跟隨系統設定
   - 換頁轉場：舊內容上移淡出、側欄橘色指示器滑動；登入時深藍蓋滿畫面
   - 步驟標籤：底線滑動
   - 專案頁：新增專案對話框（先問條件數量，再出現 N 個格子）
   - B 區：曲線選擇（每個條件一區、每個元件一直行、暫時隱藏）
   ========================================================================== */
(function () {
  'use strict';

  const THEME_KEY = 'lct-theme';

  // ---------- 主題 ----------
  /** 取得目前主題（light／dark）。 */
  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'light';
  }

  /** 套用主題並更新切換鈕文字。 */
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelectorAll('[data-theme-toggle]').forEach((btn) => {
      btn.textContent = theme === 'dark' ? '淺色模式' : '深色模式';
      btn.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
    });
  }

  /** 切換主題並記住。 */
  function toggleTheme() {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* 無痕模式等情況不記 */ }
    applyTheme(next);
  }

  // ---------- 換頁轉場 ----------
  const LEAVE_MS = 320;          // 舊內容淡出的時間（與 CSS page-out 相同）
  const LOGIN_WIPE_MS = 450;     // 登入時深藍蓋滿畫面的時間（與 CSS .wipe 相同）
  const FROM_LOGIN_KEY = 'lct-from-login';

  /** 使用者是否設定「減少動態效果」（是的話不做轉場，直接換頁）。 */
  function reducedMotion() {
    return matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /** 側欄的橘色指示器：建立一個，放在目前頁面的項目上。 */
  function setupIndicator() {
    const side = document.querySelector('.sidebar');
    const current = side && side.querySelector('[aria-current="page"] .bar');
    if (!current) return;
    const ind = document.createElement('span');
    ind.className = 'nav-indicator';
    ind.setAttribute('aria-hidden', 'true');
    side.append(ind);
    side.classList.add('has-indicator');
    placeIndicator(current, false);
    window.addEventListener('resize', () => placeIndicator(current, false));
  }

  /** 把指示器移到某個項目的 .bar 位置；animate 為 false 時直接跳過去。 */
  function placeIndicator(bar, animate) {
    const ind = document.querySelector('.nav-indicator');
    if (!ind || !bar) return;
    const s = ind.parentElement.getBoundingClientRect();
    const b = bar.getBoundingClientRect();
    ind.style.transition = animate ? '' : 'none';
    ind.style.transform = 'translate(' + (b.left - s.left) + 'px, ' + (b.top - s.top) + 'px)';
    ind.style.opacity = '1';
  }

  /** 一般換頁：舊內容上移淡出、指示器滑到新項目，再前往新頁面。 */
  function leaveTo(href, link) {
    placeIndicator(link && link.querySelector('.bar'), true);
    document.body.classList.add('is-leaving');
    setTimeout(() => { location.href = href; }, LEAVE_MS);
  }

  /** 登入：深藍區塊由右向左蓋滿畫面，專案頁載入後再淡出（見 projects.html 開頭）。 */
  function loginTo(href) {
    const wipe = document.createElement('div');
    wipe.className = 'wipe';
    document.body.append(wipe);
    requestAnimationFrame(() => requestAnimationFrame(() => wipe.classList.add('on')));
    try { sessionStorage.setItem(FROM_LOGIN_KEY, '1'); } catch (e) { /* 不記也能換頁 */ }
    setTimeout(() => { location.href = href; }, LOGIN_WIPE_MS);
  }

  /** 攔截站內 .html 連結，改成先播轉場再換頁。 */
  function setupPageTransitions() {
    document.addEventListener('click', (e) => {
      const link = e.target.closest('a[href]');
      if (!link || link.target || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      const href = link.getAttribute('href');
      if (!href || !href.endsWith('.html') || reducedMotion()) return;
      e.preventDefault();
      if (link.hasAttribute('data-login')) loginTo(href);
      else leaveTo(href, link);
    });
  }

  // ---------- 步驟標籤 ----------
  /** 把底線移到選中的標籤下方。 */
  function moveUnderline(tabs) {
    const active = tabs.querySelector('[aria-selected="true"]');
    const line = tabs.querySelector('.tab-underline');
    if (!active || !line) return;
    line.style.width = active.offsetWidth + 'px';
    line.style.transform = 'translateX(' + active.offsetLeft + 'px)';
  }

  /** 標籤點選：切換選中狀態與面板（原型只有一個面板有內容，其餘顯示說明）。 */
  function setupTabs(tabs) {
    tabs.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        tabs.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', 'false'));
        tab.setAttribute('aria-selected', 'true');
        moveUnderline(tabs);
        const target = tab.getAttribute('aria-controls');
        document.querySelectorAll('.tab-panel').forEach((p) => { p.hidden = p.id !== target; });
        // 有 data-lock-scroll 的分頁（b-3）：整頁不捲動，只有勾選清單捲動
        const panel = document.getElementById(target);
        document.body.classList.toggle('lock-scroll', !!panel && panel.hasAttribute('data-lock-scroll'));
      });
    });
    moveUnderline(tabs);
    window.addEventListener('resize', () => moveUnderline(tabs));
  }

  // ---------- 專案頁：新增專案對話框 ----------
  const COND_HINTS = ['例如 ref', '例如 1 mol%', '例如 2 mol%'];
  const MAX_CONDITIONS = 12;

  /** 對話框：步驟 1 名稱與條件數量 → 步驟 2 N 個名稱格。 */
  function setupProjectDialog() {
    const overlay = document.getElementById('new-project');
    if (!overlay) return;
    const step1 = overlay.querySelector('[data-step="1"]');
    const step2 = overlay.querySelector('[data-step="2"]');
    const stepText = overlay.querySelector('[data-step-text]');
    const countOut = overlay.querySelector('output');
    const slots = overlay.querySelector('[data-slots]');
    let count = 3;

    /** 顯示指定步驟。 */
    function show(step) {
      step1.hidden = step !== 1;
      step2.hidden = step !== 2;
      stepText.textContent = step === 1 ? '1 / 2　名稱與條件數量' : '2 / 2　條件名稱';
      if (step === 2) renderSlots();
      const first = (step === 1 ? step1 : step2).querySelector('input');
      if (first) first.focus();
    }

    /** 依條件數量產生 N 個名稱格（已填的保留）。 */
    function renderSlots() {
      const old = Array.from(slots.querySelectorAll('input')).map((i) => i.value);
      slots.innerHTML = '';
      for (let i = 0; i < count; i++) {
        const row = document.createElement('div');
        row.className = 'row nowrap';
        const label = document.createElement('label');
        label.className = 'mono small muted';
        label.style.width = '4.5em';
        label.htmlFor = 'cond-' + i;
        label.textContent = '條件 ' + (i + 1);
        const input = document.createElement('input');
        input.className = 'input grow';
        input.id = 'cond-' + i;
        input.placeholder = COND_HINTS[i] || '條件名稱';
        input.value = old[i] || '';
        row.append(label, input);
        slots.append(row);
      }
    }

    /** 開關對話框。 */
    function open() { overlay.hidden = false; show(1); }
    function close() { overlay.hidden = true; }

    document.querySelectorAll('[data-open-dialog]').forEach((b) => b.addEventListener('click', open));
    overlay.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', close));
    overlay.querySelector('[data-dec]').addEventListener('click', () => { count = Math.max(1, count - 1); countOut.value = count; });
    overlay.querySelector('[data-inc]').addEventListener('click', () => { count = Math.min(MAX_CONDITIONS, count + 1); countOut.value = count; });
    overlay.querySelector('[data-next]').addEventListener('click', () => show(2));
    overlay.querySelector('[data-back]').addEventListener('click', () => show(1));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    countOut.value = count;
  }

  // ---------- B 區：曲線選擇 ----------
  /** 一個元件的 5 條曲線名稱。 */
  const five = (d) => [1, 2, 3, 4, 5].map((n) => d + '-' + n);

  // 示意資料：條件名稱 2～4 mol% 為假設；曲線名稱沿用 JD_test_file 的命名方式
  const GROUPS = [
    { title: 'ref', devices: [['G1', ['G1-1', 'G1-2', 'G1-3', 'G1 REF-1_330 K']], ['G2', ['G2-1', 'G2-2', 'G2-3']]] },
    { title: '1 mol%', devices: [['G5', five('G5')], ['G6', five('G6')], ['G7', ['G7-1', 'G7-1_second', 'G7-2', 'G7-3', 'G7-4', 'G7-5']]] },
    { title: '2 mol%', devices: [['G8', five('G8')], ['G9', five('G9')], ['G10', five('G10')]] },
    { title: '3 mol%', devices: [['G11', five('G11')], ['G12', five('G12')], ['G13', five('G13')]] },
    { title: '4 mol%', devices: [['G14', five('G14')], ['G15', five('G15')], ['G16', five('G16')]] }
  ];

  /** B 區曲線選擇：狀態放在 selected、hidden 兩個 Set。 */
  function setupCurvePicker() {
    const root = document.getElementById('blocks');
    if (!root) return;
    const selected = new Set(['G1-2', 'G6-1', 'G8-1', 'G11-3', 'G14-2']);
    const hidden = new Set(['2 mol%']);
    const allNames = GROUPS.flatMap((g) => g.devices.flatMap((d) => d[1]));

    /** 全部已選就全部取消，否則全部勾選。 */
    function toggleMany(names) {
      const all = names.every((n) => selected.has(n));
      names.forEach((n) => (all ? selected.delete(n) : selected.add(n)));
      render();
    }

    /** 更新上方計數。 */
    function renderCount() {
      let hiddenSel = 0;
      GROUPS.forEach((g) => {
        if (!hidden.has(g.title)) return;
        g.devices.forEach((d) => d[1].forEach((n) => { if (selected.has(n)) hiddenSel += 1; }));
      });
      document.getElementById('sel-count').textContent = selected.size;
      const flag = document.getElementById('hidden-flag');
      flag.hidden = hiddenSel === 0;
      flag.textContent = '其中 ' + hiddenSel + ' 個 pixel 暫時隱藏';
    }

    /** 重畫全部區塊（原型資料量小，直接重建）。 */
    function render() {
      root.innerHTML = '';
      GROUPS.forEach((g) => {
        const names = g.devices.flatMap((d) => d[1]);
        const isHidden = hidden.has(g.title);
        const block = document.createElement('div');
        block.className = 'block' + (isHidden ? ' is-hidden' : '');

        // 區塊標題列：名稱、整組勾選、暫時隱藏（固定寬度，不會移動）
        const head = document.createElement('div');
        head.className = 'block-head';
        head.innerHTML =
          '<h3></h3>' +
          '<button type="button" class="btn ghost sm" data-all>整組勾選／取消</button>' +
          '<button type="button" class="btn sm hide-btn" data-hide></button>';
        head.querySelector('h3').textContent = g.title;
        head.querySelector('[data-all]').addEventListener('click', () => toggleMany(names));
        const hideBtn = head.querySelector('[data-hide]');
        hideBtn.textContent = isHidden ? '取消隱藏' : '暫時隱藏';   // 兩個字數相同，按鈕寬度不變
        hideBtn.classList.toggle('warn', isHidden);
        hideBtn.setAttribute('aria-pressed', isHidden ? 'true' : 'false');
        hideBtn.addEventListener('click', () => {
          isHidden ? hidden.delete(g.title) : hidden.add(g.title);
          render();
        });
        // 數量放在標題下一行
        const sum = document.createElement('span');
        sum.className = 'block-sum';
        sum.textContent = g.devices.length + ' 個樣品 · ' + names.length + ' 個 pixel' + (isHidden ? ' · 已隱藏，不畫進圖' : '');
        block.append(head, sum);

        // 樣品直行
        const cols = document.createElement('div');
        cols.className = 'columns';
        g.devices.forEach(([device, curves]) => {
          const col = document.createElement('div');
          col.className = 'device';
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'device-btn';
          btn.textContent = device;
          btn.title = '整行勾選／取消';
          btn.addEventListener('click', () => toggleMany(curves));
          col.append(btn);
          curves.forEach((name) => {
            const label = document.createElement('label');
            label.className = 'check';
            const box = document.createElement('input');
            box.type = 'checkbox';
            box.checked = selected.has(name);
            box.addEventListener('change', () => {
              box.checked ? selected.add(name) : selected.delete(name);
              renderCount();
            });
            const text = document.createElement('span');
            text.textContent = name;
            label.append(box, text);
            col.append(label);
          });
          cols.append(col);
        });
        block.append(cols);
        root.append(block);
      });
      renderCount();
    }

    // 頁首：n 個樣品（G1、G2…）、m 個 pixel（G1-1、G1-2…）
    document.getElementById('sample-count').textContent = GROUPS.reduce((sum, g) => sum + g.devices.length, 0);
    document.getElementById('pixel-count').textContent = allNames.length;

    document.getElementById('select-all').addEventListener('click', () => { allNames.forEach((n) => selected.add(n)); render(); });
    document.getElementById('select-none').addEventListener('click', () => { selected.clear(); render(); });
    const collapse = document.getElementById('collapse');
    collapse.addEventListener('click', () => {
      const open = collapse.getAttribute('aria-expanded') === 'true';
      collapse.setAttribute('aria-expanded', open ? 'false' : 'true');
      collapse.textContent = open ? '展開 ▼' : '收合 ▲';
      root.hidden = open;
    });
    render();
  }

  // ---------- 啟動 ----------
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(currentTheme());
    document.querySelectorAll('[data-theme-toggle]').forEach((b) => b.addEventListener('click', toggleTheme));
    setupIndicator();
    setupPageTransitions();
    document.querySelectorAll('.tabs').forEach(setupTabs);
    setupProjectDialog();
    setupCurvePicker();
  });
})();
