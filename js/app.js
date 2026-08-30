(function () {
  "use strict";
  var PT = window.PolicyTracker;

  var allProducts = [];      // policy JSON 对象，顺序与 data/products.json 索引一致
  var monitorStatus = null;  // data/update_status.json（可能不存在）
  var state = { q: "", region: "all", training: "all", risk: "all" };

  /* 厂商归一化与排序键：与 scripts/gen_readme_table.py 的 VENDOR_RULES/VENDOR_SORT 保持同步 */
  var VENDOR_RULES = [
    ["火山引擎", "字节跳动"], ["字节跳动", "字节跳动"], ["腾讯", "腾讯"],
    ["阿里云", "阿里巴巴"], ["阿里巴巴", "阿里巴巴"], ["百度", "百度"],
    ["深度求索", "DeepSeek（深度求索）"], ["OpenAI", "OpenAI"], ["Anthropic", "Anthropic"],
    ["Google", "Google"], ["智谱AI", "智谱AI"], ["月之暗面", "月之暗面（Moonshot AI）"],
    ["科大讯飞", "科大讯飞"], ["快手", "快手"], ["MiniMax", "MiniMax"],
    ["阶跃星辰", "阶跃星辰"], ["昆仑万维", "昆仑万维"], ["商汤", "商汤科技"],
    ["360", "360"], ["华为", "华为"], ["百川", "百川智能"], ["零一万物", "零一万物"]
  ];
  var VENDOR_SORT = {
    "阿里巴巴": "alibaba", "百川智能": "baichuan", "百度": "baidu", "华为": "huawei",
    "阶跃星辰": "jieyue", "科大讯飞": "kedaxunfei", "快手": "kuaishou",
    "昆仑万维": "kunlun", "零一万物": "lingyi", "MiniMax": "minimax",
    "商汤科技": "shangtang", "DeepSeek（深度求索）": "shendu", "腾讯": "tengxun",
    "月之暗面（Moonshot AI）": "yue", "智谱AI": "zhipu",
    "Anthropic": "anthropic", "Google": "google", "OpenAI": "openai", "360": "360"
  };
  function vendorOf(company) {
    for (var i = 0; i < VENDOR_RULES.length; i++) {
      if (company.indexOf(VENDOR_RULES[i][0]) === 0) return VENDOR_RULES[i][1];
    }
    return company;
  }

  function fetchJson(url) {
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  function fetchAllProducts() {
    return fetchJson("data/products.json").then(function (index) {
      var ids = index.products || [];
      return Promise.all(ids.map(function (id) {
        return fetchJson("data/policies/" + id + ".json");
      })).then(function (policies) {
        return { meta: index.meta, policies: policies };
      });
    });
  }

  function fetchMonitorStatus() {
    return fetchJson("data/update_status.json")
      .then(function (s) { monitorStatus = s; })
      .catch(function () { monitorStatus = null; });
  }

  function changedProductIds() {
    if (!monitorStatus || !monitorStatus.products) return [];
    return Object.keys(monitorStatus.products).filter(function (id) {
      return monitorStatus.products[id].status === "changed";
    });
  }

  /* ---------- 筛选 ---------- */

  function matchesFilters(p) {
    if (state.q) {
      var hay = (p.name + " " + p.company + " " + vendorOf(p.company)).toLowerCase();
      if (hay.indexOf(state.q.toLowerCase()) === -1) return false;
    }
    if (state.region === "cn" && p.region !== "中国") return false;
    if (state.region === "overseas" && p.region === "中国") return false;

    var toc = (p.versions && p.versions.toc) || null;
    var tob = (p.versions && p.versions.tob) || null;

    if (state.training !== "all") {
      if (!toc && !tob) return false; // 占位条目无训练语义
      var anyTrue = (toc && toc.used_for_training === true) || (tob && tob.used_for_training === true);
      if (state.training === "yes" && !anyTrue) return false;
      if (state.training === "no" && anyTrue) return false;
    }
    if (state.risk !== "all") {
      var r1 = toc && toc.risk_level, r2 = tob && tob.risk_level;
      if (state.risk !== r1 && state.risk !== r2) return false;
    }
    return true;
  }

  /* ---------- 渲染 ---------- */

  function trainCell(v) {
    if (v === true) return '<span class="badge badge-bad" title="该版本会将用户数据用于模型训练/优化">使用用户数据</span>';
    if (v === false) return '<span class="badge badge-good" title="该版本不会将用户数据用于模型训练">不使用用户数据</span>';
    return '<span class="cell-na">—</span>';
  }

  function riskMini(v) {
    if (!v || !v.risk_level) return '<span class="cell-na">—</span>';
    var labels = { green: "🟢 低", yellow: "🟡 中", red: "🔴 高" };
    return '<span class="risk-mini ' + PT.escapeHtml(v.risk_level) + '">' +
      (labels[v.risk_level] || "—") + "</span>";
  }

  function versionPanel(title, v, emptyReason) {
    if (!v) {
      return '<div class="detail-panel muted"><div class="dp-title">' +
        PT.escapeHtml(title) + '</div><div class="dp-line">—（' +
        PT.escapeHtml(emptyReason) + '）</div></div>';
    }
    var train = v.used_for_training === true
      ? '<span class="badge badge-bad">使用用户数据</span><span class="dp-note">（默认）</span>'
      : v.used_for_training === false
        ? '<span class="badge badge-good">不使用用户数据</span><span class="dp-note">（或加入式未启用）</span>'
        : '<span class="cell-na">—</span>';
    var deid = v.deidentified === true ? '<span class="badge badge-good">是</span>'
      : v.deidentified === false ? '<span class="badge badge-bad">否</span>'
      : '<span class="cell-na">—</span>';
    return (
      '<div class="detail-panel">' +
      '<div class="dp-title">' + PT.escapeHtml(title) + '</div>' +
      '<div class="dp-line"><span class="dp-k">训练</span>' + train + "</div>" +
      '<div class="dp-line"><span class="dp-k">退出机制</span>' + PT.escapeHtml(v.opt_out || "—") + "</div>" +
      '<div class="dp-line"><span class="dp-k">去标识化</span>' + deid + "</div>" +
      '<div class="dp-line"><span class="dp-k">数据留存</span>' + PT.escapeHtml(v.data_retention || "—") + "</div>" +
      '<div class="dp-line"><span class="dp-k">风险</span>' + PT.riskBadge(v.risk_level) + "</div>" +
      "</div>"
    );
  }

  /* 版本缺失时的说明：优先展示数据中的 toc_note/tob_note（如"已搜索，信息未公开"原因），
     其次是通用占位文案 */
  function emptyReason(note, fallback) {
    return note || fallback;
  }

  function detailRowHtml(p) {
    var toc = (p.versions && p.versions.toc) || null;
    var tob = (p.versions && p.versions.tob) || null;
    var isPlaceholder = !toc && !tob;
    var panels =
      versionPanel("个人版", toc, emptyReason(p.toc_note,
        isPlaceholder ? "占位条目：条款待收集" : "无个人版（纯开发者产品等）")) +
      versionPanel("企业版", tob, emptyReason(p.tob_note,
        isPlaceholder ? "占位条目：条款待收集" : "无企业版（详见条目 tob_note）"));
    return (
      '<div class="row-pin"><div class="detail-indent">' +
      '<div class="dp-link"><a href="detail.html?id=' + PT.escapeHtml(p.id) +
      '">查看完整详情页 →</a></div>' +
      '<div class="detail-panels">' + panels + "</div>" +
      "</div></div>"
    );
  }

  function render() {
    var tbody = document.getElementById("tableBody");
    var changed = {};
    changedProductIds().forEach(function (id) { changed[id] = true; });

    var filtered = allProducts.filter(matchesFilters);
    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="no-data">没有符合条件的产品</td></tr>';
      return;
    }

    // 按厂商分组，厂商按拼音排序，组内按 id
    var groups = {};
    var order = {};
    filtered.forEach(function (p) {
      var v = vendorOf(p.company);
      (groups[v] = groups[v] || []).push(p);
      order[v] = VENDOR_SORT[v] || v;
    });
    var vendors = Object.keys(groups).sort(function (a, b) {
      return order[a] < order[b] ? -1 : order[a] > order[b] ? 1 : 0;
    });

    var html = "";
    vendors.forEach(function (v) {
      var list = groups[v];
      html += '<tr class="group-row" data-open="true" data-vendor="' + PT.escapeHtml(v) + '">' +
        '<td colspan="5"><div class="row-pin"><span class="tri">▾</span> ' + PT.escapeHtml(v) +
        '<span class="group-count">' + list.length + ' 款产品</span></div></td></tr>';
      list.forEach(function (p, idx) {
        var toc = (p.versions && p.versions.toc) || null;
        var tob = (p.versions && p.versions.tob) || null;
        var flag = changed[p.id]
          ? '<span class="monitor-flag" title="政策监控检测到该产品政策可能已更新，待核实">⚠️</span>'
          : "";
        var lastCls = idx === list.length - 1 ? " last-in-group" : "";
        html += '<tr class="product-row' + lastCls + '" data-id="' + PT.escapeHtml(p.id) +
          '" tabindex="0" role="button" aria-expanded="false">' +
          '<td class="cell-name"><strong>' + PT.escapeHtml(p.name) + "</strong>" + flag + "</td>" +
          "<td>" + trainCell(toc && toc.used_for_training) + "</td>" +
          "<td>" + trainCell(tob && tob.used_for_training) + "</td>" +
          "<td>" + riskMini(toc) + "</td>" +
          "<td>" + riskMini(tob) + "</td></tr>" +
          '<tr class="detail-row" hidden><td colspan="5">' + detailRowHtml(p) + "</td></tr>";
      });
    });
    tbody.innerHTML = html;
  }

  /* ---------- 交互（事件委托） ---------- */

  function toggleDetail(row) {
    var det = row.nextElementSibling;
    if (!det || !det.classList.contains("detail-row")) return;
    var open = det.hidden;
    det.hidden = !open;
    row.setAttribute("aria-expanded", open ? "true" : "false");
    row.classList.toggle("open", open);
  }

  function toggleGroup(row) {
    var open = row.getAttribute("data-open") !== "true";
    row.setAttribute("data-open", open ? "true" : "false");
    var sib = row.nextElementSibling;
    while (sib && !sib.classList.contains("group-row")) {
      if (!open) {
        sib.hidden = true;
      } else if (sib.classList.contains("detail-row")) {
        /* 展开分组时，详情行跟随其产品行自身的展开状态，而不是全部展开 */
        var prod = sib.previousElementSibling;
        sib.hidden = !(prod && prod.classList.contains("open"));
      } else {
        sib.hidden = false;
      }
      sib = sib.nextElementSibling;
    }
  }

  function initRowEvents() {
    var tbody = document.getElementById("tableBody");
    tbody.addEventListener("click", function (e) {
      var gr = e.target.closest("tr.group-row");
      if (gr) { toggleGroup(gr); return; }
      var pr = e.target.closest("tr.product-row");
      if (pr) { toggleDetail(pr); return; }
    });
    tbody.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      var pr = e.target.closest("tr.product-row");
      if (pr) { e.preventDefault(); toggleDetail(pr); }
    });
  }

  /* ---------- URL 状态 ---------- */

  function readStateFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var region = params.get("region");
    if (["all", "cn", "overseas"].indexOf(region) !== -1) state.region = region;
    var training = params.get("training");
    if (["all", "yes", "no"].indexOf(training) !== -1) state.training = training;
    var risk = params.get("risk");
    if (["all", "green", "yellow", "red"].indexOf(risk) !== -1) state.risk = risk;
    if (params.get("q")) state.q = params.get("q");
  }

  function writeStateToUrl() {
    var params = new URLSearchParams();
    if (state.region !== "all") params.set("region", state.region);
    if (state.training !== "all") params.set("training", state.training);
    if (state.risk !== "all") params.set("risk", state.risk);
    if (state.q) params.set("q", state.q);
    var qs = params.toString();
    history.replaceState(null, "", qs ? "?" + qs : window.location.pathname);
  }

  /* ---------- 控件 ---------- */

  function setActive(container, attr, value) {
    container.querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute(attr) === value);
    });
  }

  function bindFilter(containerId, attr, key) {
    var container = document.getElementById(containerId);
    if (!container) return;
    setActive(container, attr, state[key]);
    container.addEventListener("click", function (e) {
      var btn = e.target.closest("button[" + attr + "]");
      if (!btn) return;
      setActive(container, attr, btn.getAttribute(attr));
      state[key] = btn.getAttribute(attr);
      writeStateToUrl();
      render();
    });
  }

  function initSearch() {
    var box = document.getElementById("searchBox");
    box.value = state.q;
    box.addEventListener("input", function () {
      state.q = this.value.trim();
      writeStateToUrl();
      render();
    });
  }

  /* ---------- 监控状态 ---------- */

  function renderMonitorStatus() {
    var box = document.getElementById("monitorStatus");
    if (!monitorStatus || !monitorStatus.meta) {
      box.style.display = "none";
      return;
    }
    box.style.display = "block";
    var meta = monitorStatus.meta;
    var changed = changedProductIds();
    var when = (meta.last_run || "").replace("T", " ").slice(0, 16);

    if (changed.length === 0) {
      var failedNote = meta.failed > 0 ? "，" + meta.failed + " 个产品检查失败" : "";
      box.innerHTML =
        '<div class="monitor-ok">🔍 政策监控上次运行：' + PT.escapeHtml(when) +
        "，检查 " + meta.total_products + " 个产品" + failedNote +
        "，未检测到政策变更。</div>";
      return;
    }

    var byId = {};
    allProducts.forEach(function (p) { byId[p.id] = p; });
    var links = changed.map(function (id) {
      var p = byId[id];
      var label = p ? p.name : id;
      return '<a href="detail.html?id=' + encodeURIComponent(id) + '">' +
        PT.escapeHtml(label) + "</a>";
    }).join("、");

    box.innerHTML =
      '<div class="monitor-banner">⚠️ 政策监控于 ' + PT.escapeHtml(when) +
      " 检测到 " + changed.length + " 个产品政策可能已更新，待人工核实：" + links +
      "</div>";
  }

  /* ---------- 初始化 ---------- */

  document.addEventListener("DOMContentLoaded", function () {
    readStateFromUrl();
    initSearch();
    bindFilter("regionFilter", "data-region", "region");
    bindFilter("trainingFilter", "data-training", "training");
    bindFilter("riskFilter", "data-risk", "risk");
    initRowEvents();
    fetchMonitorStatus().then(function () {
      if (allProducts.length) renderMonitorStatus();
    });
    fetchAllProducts()
      .then(function (result) {
        allProducts = result.policies;
        var el = document.getElementById("updateDate");
        if (result.meta && result.meta.last_updated) {
          el.textContent = "数据最后更新日期：" + result.meta.last_updated;
        }
        renderMonitorStatus();
        render();
        document.getElementById("loading").style.display = "none";
        document.getElementById("compareTable").style.display = "table";
      })
      .catch(function (err) {
        document.getElementById("loading").innerHTML =
          '<div class="error">数据加载失败：' + PT.escapeHtml(err.message) + "</div>";
      });
  });
})();
