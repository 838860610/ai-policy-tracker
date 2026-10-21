(function () {
  "use strict";

  var PT = window.PolicyTracker;
  var currentId = "";
  var isStaticPage = false;

  function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function trainingStatus(version) {
    if (!version) return "unknown";
    var known = ["explicit_no", "default_off_opt_in", "default_on_opt_out",
                 "explicit_yes", "unknown", "inferred"];
    if (known.indexOf(version.training_status) !== -1) return version.training_status;
    var note = String(version.training_note || "");
    var state = String(version.default_state || "");
    if (version.used_for_training === false) {
      if (/(未明示|沉默|待核|待核实|未明确)/.test(state) || state.indexOf("—") === 0 ||
          /(对训练沉默|保持沉默|零命中|未明示模型训练)/.test(note)) return "unknown";
      if (/(加入式|opt-in|主动加入|主动选择)/i.test(note)) return "default_off_opt_in";
      return "explicit_no";
    }
    if (version.used_for_training === true) {
      if (/(按实质口径|推断|直接涵盖模型|未明示模型训练)/.test(note)) return "inferred";
      if (/(设置开关|联系|邮件|撤回|退出)/.test(String(version.opt_out || ""))) {
        return "default_on_opt_out";
      }
      return "explicit_yes";
    }
    return "unknown";
  }

  function trainingAlert(version) {
    var status = trainingStatus(version);
    var note = version && version.training_note;
    var cls = status === "unknown" ? "unknown" : (status === "explicit_no" || status === "default_off_opt_in" ? "no" : "yes");
    var icon = cls === "unknown" ? "❔" : (cls === "no" ? "✅" : "⚠️");
    var labels = {
      explicit_yes: "明确使用用户数据训练或优化模型",
      default_on_opt_out: "默认使用用户数据训练或优化模型，但可退出",
      inferred: "根据服务改善或优化条款推断可能用于训练",
      explicit_no: "明确不使用用户数据训练模型",
      default_off_opt_in: "默认不用于训练，加入相关计划后才会使用",
      unknown: "政策未明确是否用于训练"
    };
    return (
      '<div class="training-alert ' + cls + '">' +
      '<span class="icon">' + icon + "</span>" +
      "<strong>" + labels[status] + "</strong>" +
      (note ? " &mdash; " + PT.escapeHtml(note) : "") +
      "</div>"
    );
  }

  /** 风险评定依据卡（A1-a）：按方法论四项绿色标准逐条自动推导，供参考 */
  function riskDeriveCard(version) {
    // 与 scripts/validate_data.py 的绿色标准推导保持同一口径
    function retentionClear30(ret) {
      if (!ret) return null;
      if (/未明确|待核实|待核|未载明|未说明/.test(ret)) return false;
      return /30\s*天|≤\s*30|30日/.test(ret);
    }

    var trainingState = trainingStatus(version);
    var items = [
      {
        label: "默认不用于训练",
        state: ["explicit_no", "default_off_opt_in"].indexOf(trainingState) !== -1 ? "ok"
             : ["explicit_yes", "default_on_opt_out", "inferred"].indexOf(trainingState) !== -1 ? "no" : "q",
      },
      {
        label: "数据去标识化",
        state: version.deidentified === true ? "ok"
             : version.deidentified === false ? "no" : "q",
      },
      {
        label: "留存期限明确且≤30天",
        state: retentionClear30(version.data_retention) === true ? "ok"
             : retentionClear30(version.data_retention) === false ? "no" : "q",
      },
      {
        label: "版权归属用户",
        state: (version.copyright || "").indexOf("用户") !== -1 &&
               (version.copyright || "").indexOf("待核实") === -1 ? "ok" : "no",
      },
    ];
    var cls = { ok: "rd-ok", no: "rd-no", q: "rd-q" };
    var mark = { ok: "✓", no: "✗", q: "?" };
    var lines = items.map(function (it) {
      return '<div class="rd-line"><span class="' + cls[it.state] + '">' + mark[it.state] +
        "</span>" + PT.escapeHtml(it.label) + "</div>";
    }).join("");
    return (
      '<div class="risk-derive">' +
      '<div class="rd-title">绿色标准逐条对照（自动推导供参考，最终判定含人工复核）</div>' +
      lines + "</div>"
    );
  }

  function renderVersion(containerId, version) {
    var container = document.getElementById(containerId);
    var clausesHtml = (version.key_clauses || [])
      .map(function (c) {
        return '<div class="quote-block"><p>' + PT.escapeHtml(c) + "</p></div>";
      })
      .join("");

    var html =
      trainingAlert(version) +
      '<div class="info-grid">' +
      '<div class="info-item"><div class="label">默认状态</div><div class="value">' +
      PT.escapeHtml(version.default_state) + "</div></div>" +
      '<div class="info-item"><div class="label">退出机制</div><div class="value">' +
      PT.escapeHtml(version.opt_out) + "</div></div>" +
      '<div class="info-item"><div class="label">退出操作说明</div><div class="value">' +
      PT.escapeHtml(version.opt_out_method) + "</div></div>" +
      '<div class="info-item"><div class="label">是否去标识化</div><div class="value">' +
      PT.boolBadge(version.deidentified, true) + "</div></div>" +
      '<div class="info-item"><div class="label">数据留存期限</div><div class="value">' +
      PT.escapeHtml(version.data_retention) + "</div></div>" +
      '<div class="info-item"><div class="label">版权归属</div><div class="value">' +
      PT.escapeHtml(version.copyright) + "</div></div>" +
      '<div class="info-item"><div class="label">其他用途</div><div class="value">' +
      PT.escapeHtml(version.other_uses) + "</div></div>" +
      '<div class="info-item"><div class="label">风险等级</div><div class="value">' +
      PT.riskBadge(version.risk_level) + "</div></div>" +
      "</div>" +
      riskDeriveCard(version);

    if (clausesHtml) {
      html += "<h3>关键条款摘录</h3>" + clausesHtml;
    }

    var policyHref = PT.safeUrl(version.policy_link);
    if (policyHref) {
      html +=
        '<a href="' + PT.escapeHtml(policyHref) +
        '" class="policy-link" target="_blank" rel="noopener noreferrer">查看该版本完整政策 &rarr;</a>';
    }

    container.innerHTML = html;
  }

  function renderTimeline(timeline) {
    if (!timeline || timeline.length === 0) return;
    var card = document.getElementById("timelineCard");
    var container = document.getElementById("timeline");
    var html = timeline
      .map(function (item) {
        return (
          '<div class="timeline-item">' +
          '<div class="timeline-date">' + PT.escapeHtml(item.date) + "</div>" +
          '<div class="timeline-event">' + PT.escapeHtml(item.event) + "</div>" +
          "</div>"
        );
      })
      .join("");
    container.innerHTML = html;
    card.style.display = "block";
  }

  function renderList(containerId, items) {
    var container = document.getElementById(containerId);
    if (!items || items.length === 0) {
      container.innerHTML = '<li style="color:var(--text-tertiary)">暂无信息</li>';
      return;
    }
    container.innerHTML = items
      .map(function (item) {
        return "<li>" + PT.escapeHtml(item) + "</li>";
      })
      .join("");
  }

  /** 产品若没有某个版本的数据，隐藏对应标签页，避免点击后看到空内容。
   *  若两个版本都没有（占位条目），在内容区展示 toc_note/tob_note 说明文字。 */
  function syncTabs(versions, data) {
    var hasToc = !!versions.toc;
    var hasTob = !!versions.tob;
    [["tabToc", "toc"], ["tabTob", "tob"]].forEach(function (pair) {
      var tab = document.getElementById(pair[0]);
      if (tab) tab.style.display = versions[pair[1]] ? "" : "none";
    });
    // 默认面板必须切到"第一个可见的标签"：CSS 里 .tab-content 默认 display:none，
    // 只隐藏按钮而把 active 留在 contentToc，会让纯 ToB 产品打开后主内容区空白。
    // ?tab=toc|tob 可直接深链到指定版本（仅在该版本存在时生效）。
    var wanted = getQueryParam("tab");
    if (wanted === "tob" && hasTob) activateTab("tob");
    else if (wanted === "toc" && hasToc) activateTab("toc");
    else if (hasToc) activateTab("toc");
    else if (hasTob) activateTab("tob");

    if (!hasToc && !hasTob) {
      var notes = [];
      if (data.toc_note) notes.push("个人版：" + data.toc_note);
      if (data.tob_note) notes.push("企业版：" + data.tob_note);
      var html = notes.map(function (n) {
        return '<div class="quote-block"><p>' + PT.escapeHtml(n) + "</p></div>";
      }).join("");
      if (html) {
        document.getElementById("contentToc").innerHTML =
          '<p style="color:var(--text-secondary);line-height:1.8">该产品暂无完整条款数据，以下为维护说明：</p>' + html;
      }
    }
  }

  /** 切换标签页：同步按钮 active 与面板 active（面板 id 形如 contentToc / contentTob）。
   *  updateUrl 为 true 时把当前版本写进地址栏，便于复制/分享到具体版本。 */
  function activateTab(key, updateUrl) {
    var suffix = key.charAt(0).toUpperCase() + key.slice(1);
    document.querySelectorAll(".tab").forEach(function (t) {
      var on = t.getAttribute("data-tab") === key;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.setAttribute("tabindex", on ? "0" : "-1");
    });
    document.querySelectorAll(".tab-content").forEach(function (c) {
      c.classList.remove("active");
      c.setAttribute("aria-hidden", "true");
    });
    var panel = document.getElementById("content" + suffix);
    if (panel) {
      panel.classList.add("active");
      panel.removeAttribute("aria-hidden");
    }
    if (updateUrl) {
      // 静态页只需 ?tab=；旧版 detail.html?id= 必须保留 id，否则刷新后丢失产品
      var url = isStaticPage
        ? "?tab=" + key
        : "?id=" + encodeURIComponent(currentId) + "&tab=" + key;
      try {
        history.replaceState(null, "", url);
      } catch (e) {
        /* 老浏览器不支持时忽略，不影响内容展示 */
      }
    }
  }

  function initTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        activateTab(this.getAttribute("data-tab"), true);
      });
      /* 键盘：左右方向键切换，Home/End 跳到首尾（WAI-ARIA tab 模式） */
      tab.addEventListener("keydown", function (e) {
        var visible = tabs.filter(function (t) { return t.style.display !== "none"; });
        var i = visible.indexOf(this);
        if (i === -1) return;
        var next = null;
        if (e.key === "ArrowRight") next = visible[(i + 1) % visible.length];
        else if (e.key === "ArrowLeft") next = visible[(i - 1 + visible.length) % visible.length];
        else if (e.key === "Home") next = visible[0];
        else if (e.key === "End") next = visible[visible.length - 1];
        if (!next) return;
        e.preventDefault();
        next.focus();
        activateTab(next.getAttribute("data-tab"), true);
      });
    });
  }

  function showError(html) {
    document.getElementById("loading").innerHTML = '<div class="error">' + html + "</div>";
  }

  function detailHref(pid) {
    return "p/" + encodeURIComponent(pid) + ".html";
  }

  /** 详情页 URL：静态页用 p/{id}.html，旧入口保留 detail.html?id= */
  function canonicalUrl(pid) {
    var base = "https://838860610.github.io/ai-policy-tracker/";
    return isStaticPage
      ? base + detailHref(pid)
      : base + "detail.html?id=" + encodeURIComponent(pid);
  }

  /** 静态页的 OG 已在构建期写好；这里兜底动态刷新，兼容旧的 detail.html?id= 入口 */
  function updateMeta(data) {
    var url = canonicalUrl(data.id);
    var ogTitle = data.name + " 隐私政策与训练数据设置——AI 用户政策追踪器";
    var ogDesc = (data.analysis_summary || data.description || "").slice(0, 100);
    [["og:title", ogTitle], ["og:description", ogDesc], ["og:url", url]].forEach(function (pair) {
      var el = document.querySelector('meta[property="' + pair[0] + '"]');
      if (el) el.setAttribute("content", pair[1]);
    });
    var canonical = document.querySelector('link[rel="canonical"]');
    if (canonical) canonical.setAttribute("href", url);
  }

  /** 站内导航：同厂商其他产品 + 按列表顺序的上一个/下一个。
   *  属于增强功能，bundle 缺失或网络失败时静默不渲染。 */
  function renderNav(data) {
    var nav = document.getElementById("detailNav");
    if (!nav) return;
    fetch("generated/bundle.json")
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (bundle) {
        var products = (bundle && bundle.policies) || [];
        var idx = -1;
        products.forEach(function (p, i) {
          if (p.id === data.id) idx = i;
        });
        if (idx === -1) return;

        var vendor = PT.vendorOf(data.company);
        var siblings = products.filter(function (p) {
          return p.id !== data.id && PT.vendorOf(p.company) === vendor;
        });
        var prev = idx > 0 ? products[idx - 1] : null;
        var next = idx < products.length - 1 ? products[idx + 1] : null;

        var parts = [];
        if (siblings.length) {
          parts.push(
            '<div class="nav-group"><div class="nav-label">同厂商其他产品</div>' +
            '<div class="nav-links">' +
            siblings.map(function (p) {
              return '<a href="' + detailHref(p.id) + '">' +
                PT.escapeHtml(p.name || p.id) + "</a>";
            }).join("") + "</div></div>"
          );
        }

        var pager = [];
        if (prev) {
          pager.push('<a class="nav-prev" href="' + detailHref(prev.id) + '">' +
            "<span>&larr; 上一个</span><strong>" +
            PT.escapeHtml(prev.name || prev.id) + "</strong></a>");
        }
        if (next) {
          pager.push('<a class="nav-next" href="' + detailHref(next.id) + '">' +
            "<span>下一个 &rarr;</span><strong>" +
            PT.escapeHtml(next.name || next.id) + "</strong></a>");
        }
        if (pager.length) parts.push('<div class="nav-pager">' + pager.join("") + "</div>");

        if (!parts.length) return;
        nav.innerHTML = parts.join("");
        nav.hidden = false;
      })
      .catch(function () {
        /* 导航加载失败不影响正文 */
      });
  }

  function loadDetail(id) {
    currentId = id;
    fetch("data/policies/" + id + ".json")
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        document.title = data.name + " - AI 用户政策追踪器";
        document.getElementById("productName").textContent = data.name;
        document.getElementById("productMeta").innerHTML =
          "<span>公司：" + PT.escapeHtml(data.company) + "</span>" +
          "<span>地区：" + PT.escapeHtml(data.region) + "</span>";
        document.getElementById("productDesc").textContent = data.description || "";

        updateMeta(data);

        syncTabs(data.versions || {}, data);
        if (data.versions && data.versions.toc) {
          document.getElementById("tabToc").textContent =
            data.versions.toc.label || "个人版 (ToC)";
          renderVersion("contentToc", data.versions.toc);
        }
        if (data.versions && data.versions.tob) {
          document.getElementById("tabTob").textContent =
            data.versions.tob.label || "企业版 (ToB)";
          renderVersion("contentTob", data.versions.tob);
        }

        renderTimeline(data.timeline);
        document.getElementById("analysisSummary").textContent = data.analysis_summary || "";
        renderList("keyFindings", data.key_findings);
        renderList("recommendations", data.recommendations);

        document.getElementById("lastVerified").textContent = data.last_verified || "未知";
        var link = document.getElementById("policyLink");
        var policyUrl = PT.safeUrl(data.policy_url);
        if (policyUrl) {
          link.href = policyUrl;
        } else {
          link.style.display = "none";
          // .label 是 .value 的兄弟节点，不是后代；且取不到时不能让整页崩掉
          var item = link.closest ? link.closest(".info-item") : null;
          var label = item ? item.querySelector(".label") : null;
          if (label) label.textContent = "政策链接（暂无）";
        }

        document.getElementById("loading").style.display = "none";
        document.getElementById("detailContent").style.display = "block";
        initTabs();
        renderNav(data);
      })
      .catch(function (err) {
        showError(
          "详情加载失败：" + PT.escapeHtml(err.message) + "<br>" +
          "该产品可能不存在，请从<a href=\"index.html\">首页</a>选择产品进入。"
        );
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    // 静态页在 body 上写死产品 id；旧入口仍有 ?id=
    var staticId = document.body.getAttribute("data-product-id");
    isStaticPage = !!staticId;
    var id = staticId || getQueryParam("id");
    // ID 只允许字母数字和连字符，阻断路径拼接异常并给出友好提示
    if (!id || !/^[a-z0-9-]+$/i.test(id)) {
      showError('产品 ID 无效，请从<a href="index.html">首页</a>选择产品进入。');
      return;
    }
    loadDetail(id);
  });
})();
