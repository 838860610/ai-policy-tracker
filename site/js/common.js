/**
 * 共享工具函数：首页与详情页共用的渲染辅助。
 * 依赖：无（纯原生 JS）。
 */
(function (global) {
  "use strict";

  var RISK_LABELS = { green: "低风险", yellow: "中风险", red: "高风险" };

  /* 厂商归一化：与 scripts/gen_readme_table.py 的 VENDOR_RULES 保持同步 */
  var VENDOR_RULES = [
    ["火山引擎", "字节跳动"], ["字节跳动", "字节跳动"], ["腾讯", "腾讯"],
    ["阿里云", "阿里巴巴"], ["阿里巴巴", "阿里巴巴"], ["百度", "百度"],
    ["深度求索", "DeepSeek（深度求索）"], ["OpenAI", "OpenAI"], ["Anthropic", "Anthropic"],
    ["Google", "Google"], ["智谱AI", "智谱AI"], ["月之暗面", "月之暗面（Moonshot AI）"],
    ["科大讯飞", "科大讯飞"], ["快手", "快手"], ["MiniMax", "MiniMax"],
    ["阶跃星辰", "阶跃星辰"], ["昆仑万维", "昆仑万维"], ["商汤", "商汤科技"],
    ["360", "360"], ["华为", "华为"], ["百川", "百川智能"], ["零一万物", "零一万物"]
  ];

  function vendorOf(company) {
    company = String(company || "");
    for (var i = 0; i < VENDOR_RULES.length; i++) {
      if (company.indexOf(VENDOR_RULES[i][0]) === 0) return VENDOR_RULES[i][1];
    }
    return company;
  }

  function safeUrl(value) {
    if (value == null || String(value).trim() === "") return "";
    try {
      var url = new URL(String(value), window.location.href);
      if (url.protocol !== "http:" && url.protocol !== "https:") return "";
      return url.href;
    } catch (e) {
      return "";
    }
  }

  function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** 把布尔值或中文布尔字符串（"是"/"支持"/"否"/"不支持"）归一化为 true/false，其余返回 null */
  function truthy(value) {
    if (value === true || value === "是" || value === "支持") return true;
    if (value === false || value === "否" || value === "不支持") return false;
    return null;
  }

  /**
   * 语义化布尔徽章：goodWhenTrue 为 true 时，真值显示绿色、假值显示红色；
   * 为 false 时相反（如"用于训练"）。未知值原样展示。
   */
  function boolBadge(value, goodWhenTrue) {
    var t = truthy(value);
    if (t === null) {
      return '<span style="color:var(--text-tertiary)">' + escapeHtml(value) + "</span>";
    }
    var isGood = goodWhenTrue ? t : !t;
    var cls = isGood ? "badge-good" : "badge-bad";
    return '<span class="badge ' + cls + '">' + (t ? "是" : "否") + "</span>";
  }

  function riskBadge(level) {
    return (
      '<span class="risk-cell">' +
      '<span class="risk-dot ' + escapeHtml(level) + '"></span>' +
      '<span class="badge badge-' + escapeHtml(level) + '">' +
      (RISK_LABELS[level] || escapeHtml(level)) +
      "</span></span>"
    );
  }

  global.PolicyTracker = {
    RISK_LABELS: RISK_LABELS,
    vendorOf: vendorOf,
    safeUrl: safeUrl,
    escapeHtml: escapeHtml,
    truthy: truthy,
    boolBadge: boolBadge,
    riskBadge: riskBadge
  };
})(window);
