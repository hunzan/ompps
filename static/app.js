(function(){
  const initial = (window.OMpps && window.OMpps.initial) ? window.OMpps.initial : { category: "定向" };
  const groupInit = (window.OMpps && window.OMpps.groupInit) ? window.OMpps.groupInit : [];

  const categoryEl = document.getElementById("category");
  const groupsEl = document.getElementById("groups");
  const addGroupBtn = document.getElementById("addLongTermGroup");

  const LT = {
    "定向": [
      "感官知覺/動作能力",
      "基本空間與方位概念",
      "人導法",
      "徒手法",
      "手杖技巧",
      "道路穿越",
      "搭乘大眾運輸工具"
    ],
    "生活": [
      "感官知覺/動作能力",
      "基本空間與方位概念",
      "人導法",
      "徒手法",
      "個人衛生處理",
      "餐飲料理能力",
      "家庭事務處理"
    ]
  };

  // ---- Theme (Light/Dark) ----
  function applyTheme(theme){
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("ompps_theme", theme);

    const lightBtn = document.getElementById("themeLight");
    const darkBtn = document.getElementById("themeDark");
    if (lightBtn && darkBtn){
      lightBtn.setAttribute("aria-pressed", theme === "light" ? "true" : "false");
      darkBtn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    }
  }

  // 初次：優先用使用者上次選的；沒有就跟系統偏好
  const saved = localStorage.getItem("ompps_theme");
  if (saved === "light" || saved === "dark"){
    applyTheme(saved);
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches){
    applyTheme("dark");
  } else {
    applyTheme("light");
  }

  // 綁定首頁按鈕（其他頁沒有也沒關係）
  document.getElementById("themeLight")?.addEventListener("click", () => applyTheme("light"));
  document.getElementById("themeDark")?.addEventListener("click", () => applyTheme("dark"));

  function fillSelect(selectEl, category, selectedValue){
    selectEl.innerHTML = "";
    const opts = LT[category] || LT["定向"];
    opts.forEach(v => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      if (selectedValue && selectedValue === v) opt.selected = true;
      selectEl.appendChild(opt);
    });
  }

  function currentMaxIdx(){
    if (!groupsEl) return -1;
    const els = groupsEl.querySelectorAll(".group[data-idx]");
    let max = -1;
    els.forEach(e => {
      const n = parseInt(e.getAttribute("data-idx"), 10);
      if (!Number.isNaN(n)) max = Math.max(max, n);
    });
    return max;
  }

  function bindGroup(groupEl){
    // 長期目標選單
    const selectEl = groupEl.querySelector(".longTermSelect");
    const cat = categoryEl ? categoryEl.value : "定向";
    const initLong = groupEl.getAttribute("data-init-long") || "";
    fillSelect(selectEl, cat, initLong);

    // 刪除群組
    const removeGroupBtn = groupEl.querySelector("[data-remove-group]");
    removeGroupBtn?.addEventListener("click", () => {
      const groups = groupsEl.querySelectorAll(".group");
      if (groups.length <= 1) {
        // 至少保留一組
        return;
      }
      groupEl.remove();
    });

    // 新增短期目標
    const addShortBtn = groupEl.querySelector("[data-add-short]");
    const shortList = groupEl.querySelector(".shortList");

    function bindRemoveShort(btn){
      btn.addEventListener("click", () => {
        const row = btn.closest(".repeat-row");
        if (!row) return;
        const rows = shortList.querySelectorAll(".repeat-row");
        if (rows.length <= 1) {
          const input = row.querySelector("input");
          if (input) input.value = "";
          return;
        }
        row.remove();
      });
    }

    shortList.querySelectorAll("[data-remove-short]").forEach(bindRemoveShort);

    addShortBtn?.addEventListener("click", () => {
      const idx = groupEl.getAttribute("data-idx");
      const row = document.createElement("div");
      row.className = "repeat-row";
      row.innerHTML = `
        <input class="input" name="short_term_${idx}[]" value="" placeholder="短期目標內容" />
        <button class="btn btn-danger btn-small" type="button" data-remove-short>刪除</button>
      `;
      shortList.appendChild(row);
      const rm = row.querySelector("[data-remove-short]");
      if (rm) bindRemoveShort(rm);
      row.querySelector("input")?.focus();
    });
  }

  function refreshAllSelects(){
    if (!groupsEl || !categoryEl) return;
    const cat = categoryEl.value;
    groupsEl.querySelectorAll(".group").forEach(groupEl => {
      const selectEl = groupEl.querySelector(".longTermSelect");
      const current = selectEl.value;
      fillSelect(selectEl, cat, current);
    });
  }

  // 初始化：套用 DB 帶來的每組長期目標值
  if (groupsEl){
    // 把 init 值灌到 DOM，讓 bindGroup 讀到
    groupInit.forEach(x => {
      const el = groupsEl.querySelector(`.group[data-idx="${x.idx}"]`);
      if (el) el.setAttribute("data-init-long", x.longTerm || "");
    });

    groupsEl.querySelectorAll(".group").forEach(bindGroup);
  }

  // 類別切換 -> 更新所有群組的選單（保留原本選值）
  if (categoryEl){
    if (!categoryEl.value) categoryEl.value = initial.category || "定向";
    categoryEl.addEventListener("change", refreshAllSelects);
  }

  // 新增長期目標群組
  addGroupBtn?.addEventListener("click", () => {
    if (!groupsEl) return;
    const idx = currentMaxIdx() + 1;
    const group = document.createElement("div");
    group.className = "group";
    group.setAttribute("data-idx", String(idx));
    group.setAttribute("data-init-long", "感官知覺/動作能力");
    group.innerHTML = `
      <div class="row-between">
        <div style="flex:1;">
          <label class="label">長期目標</label>
          <select class="select longTermSelect" name="long_term_goal_${idx}"></select>
        </div>
        <button class="btn btn-danger btn-small" type="button" data-remove-group>刪除</button>
      </div>

      <div class="row-between" style="margin-top:10px;">
        <div class="label">短期目標（本長期目標的子目標）</div>
        <button class="btn btn-small" type="button" data-add-short>＋新增短期目標</button>
      </div>

      <div class="shortList">
        <div class="repeat-row">
          <input class="input" name="short_term_${idx}[]" value="" placeholder="短期目標內容" />
          <button class="btn btn-danger btn-small" type="button" data-remove-short>刪除</button>
        </div>
      </div>

      <div class="hint" style="margin-top:6px;">群組會在匯出時變成「長期目標1/2/…」</div>
      <hr class="hr"/>
    `;
    groupsEl.appendChild(group);
    bindGroup(group);
    group.querySelector("select")?.focus();
  });
  // ---- Force Code Modal ----
  const copyBtn = document.getElementById("copyCodeBtn");
  const ackBtn = document.getElementById("ackCodeBtn");
  const codeEl = document.getElementById("codeValue");

    copyBtn?.addEventListener("click", () => {
      const code = codeEl?.textContent?.trim() || "";
      if (!code) return;

      // 建立暫存 input 元素
      const input = document.createElement("input");
      input.value = code;
      document.body.appendChild(input);
      input.select();
      input.setSelectionRange(0, 99999); // for mobile

      const ok = document.execCommand("copy");
      document.body.removeChild(input);

      if (ok) {
        copyBtn.textContent = "已複製 ✅";
        setTimeout(() => (copyBtn.textContent = "複製代碼"), 1200);
      } else {
        alert("請長按代碼進行複製");
      }
    });

  ackBtn?.addEventListener("click", async () => {
    try {
      const res = await fetch("/ack-code", { method: "POST" });
      if (res.ok) {
        // 解除 modal：重新載入同頁
        window.location.reload();
      } else {
        alert("確認失敗，請再試一次。");
      }
    } catch {
      alert("網路/伺服器異常，請再試一次。");
    }
  });
})();

