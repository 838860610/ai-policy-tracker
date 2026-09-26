(function () {
  "use strict";
  var PT = window.PolicyTracker;

  var allProducts = [];      // policy JSON 对象，顺序与 data/products.json 索引一致
  var monitorStatus = null;  // generated/update_status.json（可能不存在）
  var monitorHealth = null;  // generated/monitor_health.json（抓取健康队列，可能不存在）
  var productsMeta = null;   // data/products.json 的 meta（静态回退字段）
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
    "月之暗面（Moonshot AI）": "yue", "智谱AI": "zhipu", "字节跳动": "zijiedong",
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
    // 优先加载 CI 生成/提交的合并 bundle（1 个请求）；不存在（CI 未跑/本地新改数据）时回退逐文件加载
    return fetchJson("generated/bundle.json").then(function (bundle) {
      return { meta: bundle.meta, policies: bundle.policies };
    }).catch(function () {
      return fetchJson("data/products.json").then(function (index) {
        var ids = index.products || [];
        return Promise.all(ids.map(function (id) {
          return fetchJson("data/policies/" + id + ".json");
        })).then(function (policies) {
          return { meta: index.meta, policies: policies };
        });
      });
    });
  }

  function fetchMonitorStatus() {
    return fetchJson("generated/update_status.json")
      .then(function (s) { monitorStatus = s; })
      .catch(function () { monitorStatus = null; });
  }

  /* 抓取健康队列：与"政策变化"分开，抓取坏了但政策没变时也能看到 */
  function fetchMonitorHealth() {
    return fetchJson("generated/monitor_health.json")
      .then(function (h) { monitorHealth = h; })
      .catch(function () { monitorHealth = null; });
  }

  function healthItems() {
    if (monitorHealth && monitorHealth.items) return monitorHealth.items;
    // 旧版站点没有该文件时，从状态明细里兜底推导
    var items = {};
    var products = (monitorStatus && monitorStatus.products) || {};
    Object.keys(products).forEach(function (pid) {
      var product = products[pid] || {};
      var targets = product.targets || {};
      Object.keys(targets).forEach(function (key) {
        var target = targets[key] || {};
        if (["degraded", "no_baseline", "blocked"].indexOf(target.health) === -1) return;
        items[pid + ":" + key] = {
          pid: pid, name: product.name || pid, key: key, health: target.health,
          message: target.message || "", url: target.url || "",
          last_good_at: target.last_good_at || null
        };
      });
    });
    return items;
  }

  /* 数据人工核实日期：监控运行时间只用于监控提示，不冒充数据更新时间 */
  function effectiveLastUpdated() {
    if (productsMeta && productsMeta.last_updated) return productsMeta.last_updated;
    return "";
  }

  function updateDataDate() {
    var el = document.getElementById("updateDate");
    if (!el) return;
    var d = effectiveLastUpdated();
    if (d) el.textContent = "数据最后人工核实日期：" + d;
  }

  function changedProductIds() {
    if (!monitorStatus || !monitorStatus.products) return [];
    return Object.keys(monitorStatus.products).filter(function (id) {
      return monitorStatus.products[id] && monitorStatus.products[id].status === "changed";
    });
  }

  function trainingStatus(v) {
    if (!v) return "unknown";
    var known = ["explicit_no", "default_off_opt_in", "default_on_opt_out",
                 "explicit_yes", "unknown", "inferred"];
    if (known.indexOf(v.training_status) !== -1) return v.training_status;
    var note = String(v.training_note || "");
    var state = String(v.default_state || "");
    if (v.used_for_training === false) {
      if (/(未明示|沉默|待核|待核实|未明确)/.test(state) || state.indexOf("—") === 0 ||
          /(对训练沉默|保持沉默|零命中|未明示模型训练)/.test(note)) return "unknown";
      if (/(加入式|opt-in|主动加入|主动选择)/i.test(note)) return "default_off_opt_in";
      return "explicit_no";
    }
    if (v.used_for_training === true) {
      if (/(按实质口径|推断|直接涵盖模型|未明示模型训练)/.test(note)) return "inferred";
      if (/(设置开关|联系|邮件|撤回|退出)/.test(String(v.opt_out || ""))) {
        return "default_on_opt_out";
      }
      return "explicit_yes";
    }
    return "unknown";
  }

  function trainingUsesData(v) {
    return ["explicit_yes", "default_on_opt_out", "inferred"].indexOf(trainingStatus(v)) !== -1;
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
      var anyTrue = trainingUsesData(toc) || trainingUsesData(tob);
      var anyKnownNo = [toc, tob].some(function (v) {
        return ["explicit_no", "default_off_opt_in"].indexOf(trainingStatus(v)) !== -1;
      });
      if (state.training === "yes" && !anyTrue) return false;
      if (state.training === "no" && (anyTrue || !anyKnownNo)) return false;
    }
    if (state.risk !== "all") {
      var r1 = toc && toc.risk_level, r2 = tob && tob.risk_level;
      if (state.risk !== r1 && state.risk !== r2) return false;
    }
    return true;
  }

  /* ---------- 渲染 ---------- */

  function trainCell(v) {
    var status = trainingStatus(v);
    if (status === "explicit_yes") {
      return '<span class="badge badge-bad" title="该版本明确使用用户数据训练或优化模型">使用用户数据</span>';
    }
    if (status === "default_on_opt_out") {
      return '<span class="badge badge-bad" title="默认使用用户数据，但提供退出机制">使用用户数据（可退出）</span>';
    }
    if (status === "inferred") {
      return '<span class="badge badge-bad" title="根据服务改善或优化条款推断，非直接训练表述">疑似使用</span>';
    }
    if (status === "explicit_no") {
      return '<span class="badge badge-good" title="该版本明确不用于模型训练">不使用用户数据</span>';
    }
    if (status === "default_off_opt_in") {
      return '<span class="badge badge-good" title="默认不训练，主动加入后才使用">默认不训练</span>';
    }
    return '<span class="cell-na" title="政策未明确或仍待核实">未明确</span>';
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
    var status = trainingStatus(v);
    var train = status === "explicit_yes"
      ? '<span class="badge badge-bad">明确使用用户数据</span>'
      : status === "default_on_opt_out"
        ? '<span class="badge badge-bad">使用用户数据</span><span class="dp-note">（可退出）</span>'
        : status === "inferred"
          ? '<span class="badge badge-bad">疑似使用</span><span class="dp-note">（依据优化条款推断）</span>'
          : status === "explicit_no"
            ? '<span class="badge badge-good">明确不使用用户数据</span>'
            : status === "default_off_opt_in"
              ? '<span class="badge badge-good">默认不训练</span><span class="dp-note">（加入式）</span>'
              : '<span class="cell-na">政策未明确</span>';
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

    /* 记录当前分组折叠状态，筛选后恢复 */
    var collapsedVendors = {};
    tbody.querySelectorAll('tr.group-row[data-open="false"]').forEach(function (r) {
      collapsedVendors[r.getAttribute("data-vendor")] = true;
    });

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
      html += '<tr class="group-row" data-open="' + (collapsedVendors[v] ? "false" : "true") +
        '" data-vendor="' + PT.escapeHtml(v) + '">' +
        '<td colspan="5"><div class="row-pin"><span class="tri">▾</span> ' + PT.escapeHtml(v) +
        '<span class="group-count">' + list.length + ' 款产品</span></div></td></tr>';
      list.forEach(function (p, idx) {
        var toc = (p.versions && p.versions.toc) || null;
        var tob = (p.versions && p.versions.tob) || null;
        var flag = changed[p.id]
          ? '<span class="monitor-flag" title="政策监控检测到该产品政策可能已更新，待核实">⚠️</span>'
          : "";
        var lastCls = idx === list.length - 1 ? " last-in-group" : "";
        var rowHidden = collapsedVendors[v] ? ' hidden' : '';
        html += '<tr class="product-row' + lastCls + '" data-id="' + PT.escapeHtml(p.id) +
          '" tabindex="0" role="button" aria-expanded="false"' + rowHidden + '>' +
          '<td class="cell-name"><strong>' + PT.escapeHtml(p.name) + "</strong>" + flag + "</td>" +
          "<td>" + trainCell(toc && toc.used_for_training) + "</td>" +
          "<td>" + trainCell(tob && tob.used_for_training) + "</td>" +
          "<td>" + riskMini(toc) + "</td>" +
          "<td>" + riskMini(tob) + "</td></tr>" +
          // 详情行按需渲染：50 个产品的展开面板不必在每次筛选时都重建，
          // 只在真正展开时生成（首次展开前保持空单元格）
          '<tr class="detail-row" hidden data-pid="' + PT.escapeHtml(p.id) +
          '"><td colspan="5"></td></tr>';
      });
    });
    tbody.innerHTML = html;
  }

  /* ---------- 交互（事件委托） ---------- */

  /** 按 id 找到产品（用于按需渲染详情行）。 */
  function findProduct(pid) {
    for (var i = 0; i < allProducts.length; i++) {
      if (allProducts[i].id === pid) return allProducts[i];
    }
    return null;
  }

  function toggleDetail(row) {
    var det = row.nextElementSibling;
    if (!det || !det.classList.contains("detail-row")) return;
    var open = det.hidden;
    if (open) {
      var cell = det.firstElementChild;
      if (cell && !cell.innerHTML) {
        var product = findProduct(det.getAttribute("data-pid"));
        if (product) cell.innerHTML = detailRowHtml(product);
      }
    }
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
    var timer = null;
    box.addEventListener("input", function () {
      state.q = this.value.trim();
      writeStateToUrl();
      /* 防抖：快速输入时只在停顿 200ms 后渲染 */
      if (timer) clearTimeout(timer);
      timer = setTimeout(render, 200);
    });
    /* "/" 快捷键聚焦搜索框（GitHub/Linear 习惯） */
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== box) {
        e.preventDefault();
        box.focus();
      }
    });
  }

  /* ---------- Hero 统计 ---------- */

  function renderHeroStats(meta) {
    var total = allProducts.length;
    var trainCount = 0, highCount = 0;
    allProducts.forEach(function (p) {
      var toc = (p.versions && p.versions.toc) || null;
      var tob = (p.versions && p.versions.tob) || null;
      if (trainingUsesData(toc) || trainingUsesData(tob)) trainCount++;
      if ((toc && toc.risk_level === "red") || (tob && tob.risk_level === "red")) highCount++;
    });
    var setNum = function (id, v) {
      var el = document.getElementById(id);
      if (el) el.textContent = v;
    };
    setNum("statTotal", total);
    setNum("statTrain", trainCount);
    setNum("statHigh", highCount);
    var upd = effectiveLastUpdated();
    setNum("statUpdated", upd ? upd.slice(5) : "—");
    var hs = document.getElementById("heroStats");
    if (hs) hs.removeAttribute("aria-hidden");
  }

  /* ---------- 监控状态 ---------- */

  function countMonitorStatuses() {
    var counts = { changed: 0, failed: 0, suspicious: 0, skipped: 0 };
    var products = (monitorStatus && monitorStatus.products) || {};
    Object.keys(products).forEach(function (id) {
      var product = products[id] || {};
      if (product.status === "changed") counts.changed += 1;
      if (product.status === "skipped") counts.skipped += 1;
      var targets = product.targets || {};
      var targetStatuses = Object.keys(targets).map(function (key) {
        return targets[key] && targets[key].status;
      });
      if (targetStatuses.indexOf("failed") !== -1) counts.failed += 1;
      if (targetStatuses.indexOf("suspicious") !== -1) counts.suspicious += 1;
    });
    return counts;
  }

  var HEALTH_LABELS = {
    blocked: "被拦截（反爬/限流）",
    no_baseline: "无可用基线",
    degraded: "抓取降级"
  };
  var HEALTH_ORDER = ["blocked", "no_baseline", "degraded"];

  function formatTime(value) {
    if (!value) return "从未成功";
    return String(value).replace("T", " ").slice(0, 16);
  }

  function renderHealthDetails() {
    var items = healthItems();
    var keys = Object.keys(items);
    if (!keys.length) return "";
    keys.sort(function (a, b) {
      var ia = HEALTH_ORDER.indexOf(items[a].health);
      var ib = HEALTH_ORDER.indexOf(items[b].health);
      if (ia !== ib) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      return (items[b].consecutive_runs || 0) - (items[a].consecutive_runs || 0);
    });
    var rows = keys.map(function (key) {
      var item = items[key] || {};
      var url = PT.safeUrl ? PT.safeUrl(item.url) : "";
      var urlHtml = url
        ? '<a href="' + PT.escapeHtml(url) + '" target="_blank" rel="noopener">来源</a>'
        : "";
      var runs = item.consecutive_runs
        ? "，连续 " + PT.escapeHtml(String(item.consecutive_runs)) + " 轮"
        : "";
      var action = item.next_action
        ? "；建议：" + PT.escapeHtml(item.next_action)
        : "";
      return '<li><span class="health-tag health-' + PT.escapeHtml(item.health) + '">' +
        PT.escapeHtml(HEALTH_LABELS[item.health] || item.health) + "</span>" +
        '<a href="detail.html?id=' + encodeURIComponent(item.pid) + '">' +
        PT.escapeHtml(item.name || item.pid) + "</a>（" +
        PT.escapeHtml(item.label || item.key) + "）" + urlHtml +
        '<span class="health-note">' + PT.escapeHtml(item.message || "") + runs +
        "；上次成功抓取：" + PT.escapeHtml(formatTime(item.last_good_at)) +
        action + "</span></li>";
    }).join("");
    return '<details class="monitor-health"><summary>抓取降级明细（' + keys.length +
      " 个目标，政策未变更但数据可能过期）</summary><ul>" + rows + "</ul></details>";
  }

  function renderMonitorStatus() {
    var box = document.getElementById("monitorStatus");
    if (!monitorStatus || !monitorStatus.meta) {
      box.style.display = "none";
      return;
    }
    box.style.display = "block";
    var meta = monitorStatus.meta;
    var counts = countMonitorStatuses();
    var changed = changedProductIds();
    var health = healthItems();
    var healthCount = Object.keys(health).length;
    var when = String(meta.last_run || "").replace("T", " ").slice(0, 16);
    var total = Number(meta.total_products) || allProducts.length;
    var anomalyParts = [];
    if (counts.failed > 0) anomalyParts.push(counts.failed + " 个产品检查失败");
    if (counts.suspicious > 0) anomalyParts.push(counts.suspicious + " 个产品正文可疑");
    if (counts.skipped > 0) anomalyParts.push(counts.skipped + " 个产品未监控");
    if (healthCount > 0) anomalyParts.push(healthCount + " 个目标抓取降级");

    if (changed.length === 0 && anomalyParts.length === 0) {
      box.innerHTML =
        '<div class="monitor-ok">🔍 政策监控上次运行：' + PT.escapeHtml(when) +
        "，检查 " + PT.escapeHtml(String(total)) + " 个产品，未检测到政策变更。</div>";
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
    var headline = changed.length > 0
      ? "检测到 " + changed.length + " 个产品政策可能已更新，待人工核实：" + links
      : "未检测到已确认的政策变更";
    var headlineHtml = changed.length > 0 ? headline : PT.escapeHtml(headline);
    var anomalyText = anomalyParts.length > 0 ? "；监控异常：" + anomalyParts.join("、") : "";
    box.innerHTML =
      '<div class="monitor-banner">⚠️ 政策监控于 ' + PT.escapeHtml(when) + " " +
      headlineHtml + PT.escapeHtml(anomalyText) + "</div>" + renderHealthDetails();
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
      updateDataDate();
      if (allProducts.length) renderMonitorStatus();
    });
    fetchMonitorHealth().then(function () {
      if (allProducts.length) renderMonitorStatus();
    });
    fetchAllProducts()
      .then(function (result) {
        allProducts = result.policies;
        productsMeta = result.meta || null;
        updateDataDate();
        renderHeroStats(productsMeta);
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
