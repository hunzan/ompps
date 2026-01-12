(function(){
  const initial = (window.OMpps && window.OMpps.initial) ? window.OMpps.initial : { category: "定向" };
  const groupInit = (window.OMpps && window.OMpps.groupInit) ? window.OMpps.groupInit : [];

  // ✅ 新增：類別來源（先 hidden，再舊的 select）
  const catHiddenEl = document.getElementById("catHidden");
  const categoryEl = document.getElementById("category"); // 舊版才有
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

  // ✅ 取得目前類別：優先 hidden，否則 select，最後 fallback
  function getCat(){
    const v = (catHiddenEl && catHiddenEl.value) ? catHiddenEl.value.trim()
            : (categoryEl && categoryEl.value) ? categoryEl.value.trim()
            : (initial && initial.category) ? String(initial.category).trim()
            : "定向";
    return (v === "生活" || v === "定向") ? v : "定向";
  }

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
    const selectEl = groupEl.querySelector(".longTermSelect");
    const cat = getCat();
    const initLong = groupEl.getAttribute("data-init-long") || "";
    fillSelect(selectEl, cat, initLong);

    const removeGroupBtn = groupEl.querySelector("[data-remove-group]");
    removeGroupBtn?.addEventListener("click", () => {
      const groups = groupsEl.querySelectorAll(".group");
      if (groups.length <= 1) return;
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
    if (!groupsEl) return;
    const cat = getCat();
    groupsEl.querySelectorAll(".group").forEach(groupEl => {
      const selectEl = groupEl.querySelector(".longTermSelect");
      const current = selectEl.value;
      fillSelect(selectEl, cat, current);
    });
  }

  // 初始化：套用 DB 帶來的每組長期目標值
  if (groupsEl){
    groupInit.forEach(x => {
      const el = groupsEl.querySelector(`.group[data-idx="${x.idx}"]`);
      if (el) el.setAttribute("data-init-long", x.longTerm || "");
    });
    groupsEl.querySelectorAll(".group").forEach(bindGroup);
  }

  // ✅ 如果你還保留舊版 select#category，仍可支援 change
  categoryEl?.addEventListener("change", () => {
    // 同步 hidden（如果兩者同時存在）
    if (catHiddenEl) catHiddenEl.value = categoryEl.value;
    refreshAllSelects();
  });

  // ✅ 關鍵：按上方「定向/生活」按鈕時，如果你不想換頁，也可即時切換選單
  // 目前你的按鈕是 href 直接換頁，所以「換頁後」會自然套用新 catHidden
  // 但如果你之後想做成不換頁，可打開這段 preventDefault 即時切換：
  document.querySelectorAll("[data-switch-cat]").forEach(a => {
    a.addEventListener("click", (e) => {
      // 如果你希望「仍然換頁」，把下面兩行註解掉即可
      // e.preventDefault();
      // history.replaceState(null, "", a.getAttribute("href"));

      const toCat = (a.getAttribute("data-cat") || "").trim();
      if (toCat === "定向" || toCat === "生活") {
        if (catHiddenEl) catHiddenEl.value = toCat;
        if (categoryEl) categoryEl.value = toCat;
        refreshAllSelects();
      }
    });
  });

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
        <button class="btn btn-small btn-short" type="button" data-add-short>＋新增短期目標</button>
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
// ---- After download modal (Step 3) ----
(function(){
  const downloadBtn = document.getElementById("downloadBtn");
  if (!downloadBtn) return; // 不是每頁都有下載按鈕

  const code = (downloadBtn.getAttribute("data-code") || "").trim();
  const dlUrl = downloadBtn.getAttribute("data-download-url") || "";
  const homeUrl = downloadBtn.getAttribute("data-home-url") || "/";

  const backdrop = document.getElementById("afterDownloadBackdrop");
  const modal = document.getElementById("afterDownloadModal");
  const keepBtn = document.getElementById("keepAfterDownloadBtn");
  const delBtn = document.getElementById("deleteAfterDownloadBtn");

  function openModal(){
    if (backdrop) backdrop.style.display = "block";
    if (modal) modal.style.display = "grid";
    delBtn?.focus();
  }

  function closeModal(){
    if (backdrop) backdrop.style.display = "none";
    if (modal) modal.style.display = "none";
    downloadBtn.focus();
  }

    downloadBtn.addEventListener("click", async () => {
      if (!dlUrl) return;

      // 按鈕鎖定，避免連點重複下載
      const oldText = downloadBtn.textContent;
      downloadBtn.disabled = true;
      downloadBtn.textContent = "下載中…";

      try{
        const res = await fetch(dlUrl, { method: "GET" });
        if (!res.ok) throw new Error("download failed");

        // 嘗試從 Content-Disposition 抓檔名（抓不到就用預設）
        let filename = "";
        const cd = res.headers.get("Content-Disposition") || "";
        const m = cd.match(/filename\*?=(?:UTF-8''|")?([^\";]+)/i);
        if (m && m[1]) filename = decodeURIComponent(m[1].replace(/"/g, "").trim());
        if (!filename) filename = `OMpps_${code || "draft"}.txt`;

        const blob = await res.blob();

        // 觸發下載
        const a = document.createElement("a");
        const blobUrl = URL.createObjectURL(blob);
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);

        // ✅ 下載成功後才詢問是否刪除
        openModal();

      }catch(e){
        alert("下載失敗，請稍後再試。");
      }finally{
        downloadBtn.disabled = false;
        downloadBtn.textContent = oldText;
      }
    });

  keepBtn?.addEventListener("click", closeModal);
  backdrop?.addEventListener("click", closeModal);

  delBtn?.addEventListener("click", async () => {
    if (!code){
      alert("找不到代碼，無法刪除。");
      return;
    }
    try{
      const res = await fetch("/api/delete-workspace", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ code })
      });
      if (res.ok){
        alert("已刪除草稿 ✅");
        window.location.href = homeUrl;
      } else {
        alert("刪除失敗，請稍後再試。");
      }
    }catch{
      alert("網路/伺服器異常，請稍後再試。");
    }
  });
})();