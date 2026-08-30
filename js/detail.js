(function () {
  "use strict";

  var PT = window.PolicyTracker;

  function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function trainingAlert(used, note) {
    var cls = used ? "yes" : "no";
    var icon = used ? "\u26a0\ufe0f" : "\u2705";
    var optin = !used && note && note.indexOf("加入") !== -1;
    var label = used
      ? "使用用户数据训练模型"
      : (optin ? "默认不使用用户数据训练模型（加入式：加入相关计划后才会用于训练）"
               : "不使用用户数据训练模型");
    return (
      '<div class="training-alert ' + cls + '">' +
      '<span class="icon">' + icon + "</span>" +
      "<strong>" + label + "</strong>" +
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

    var items = [
      {
        label: "默认不用于训练",
        state: version.used_for_training === false ? "ok"
             : version.used_for_training === true ? "no" : "q",
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
      trainingAlert(PT.truthy(version.used_for_training), version.training_note) +
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

    if (version.policy_link) {
      html +=
        '<a href="' + PT.escapeHtml(version.policy_link) +
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

  /** 产品若没有某个版本的数据，隐藏对应标签页，避免点击后看到空内容 */
  function syncTabs(versions) {
    [["tabToc", "toc"], ["tabTob", "tob"]].forEach(function (pair) {
      var tab = document.getElementById(pair[0]);
      if (tab) tab.style.display = versions[pair[1]] ? "" : "none";
    });
  }

  function initTabs() {
    var tabs = document.querySelectorAll(".tab");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var target = this.getAttribute("data-tab");
        tabs.forEach(function (t) { t.classList.remove("active"); });
        this.classList.add("active");
        document.querySelectorAll(".tab-content").forEach(function (c) {
          c.classList.remove("active");
        });
        document.getElementById("content" + target.charAt(0).toUpperCase() + target.slice(1))
          .classList.add("active");
      });
    });
  }

  function showError(html) {
    document.getElementById("loading").innerHTML = '<div class="error">' + html + "</div>";
  }

  function loadDetail(id) {
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

        syncTabs(data.versions || {});
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
        if (data.policy_url) {
          link.href = data.policy_url;
        } else {
          link.style.display = "none";
          link.parentElement.querySelector(".label").textContent = "政策链接（暂无）";
        }

        document.getElementById("loading").style.display = "none";
        document.getElementById("detailContent").style.display = "block";
        initTabs();
      })
      .catch(function (err) {
        showError(
          "详情加载失败：" + PT.escapeHtml(err.message) + "<br>" +
          "该产品可能不存在，请从<a href=\"index.html\">首页</a>选择产品进入。"
        );
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var id = getQueryParam("id");
    // ID 只允许字母数字和连字符，阻断路径拼接异常并给出友好提示
    if (!id || !/^[a-z0-9-]+$/i.test(id)) {
      showError('产品 ID 无效，请从<a href="index.html">首页</a>选择产品进入。');
      return;
    }
    loadDetail(id);
  });
})();
