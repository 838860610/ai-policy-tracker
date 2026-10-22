(function () {
  "use strict";

  var KEY = "pt-theme";
  var root = document.documentElement;

  function storedTheme() {
    try {
      return window.localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  function actionLabel(theme) {
    return theme === "light" ? "切换到暗色主题" : "切换到明亮主题";
  }

  /* 只改 <html data-theme>；配色全部由 CSS 变量接管 */
  function apply(theme) {
    if (theme === "light") root.setAttribute("data-theme", "light");
    else root.removeAttribute("data-theme");

    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-label", actionLabel(theme));
      buttons[i].setAttribute("title", actionLabel(theme));
      buttons[i].setAttribute("aria-pressed", theme === "light" ? "true" : "false");
    }
  }

  /* 默认明亮主题；用户显式选过暗色才保持暗色。
     在 <head> 里同步执行，先于样式表应用主题，避免闪烁。 */
  apply(storedTheme() === "dark" ? "dark" : "light");

  document.addEventListener("DOMContentLoaded", function () {
    apply(root.getAttribute("data-theme") === "light" ? "light" : "dark");

    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener("click", function () {
        var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
        try {
          window.localStorage.setItem(KEY, next);
        } catch (e) {
          /* 隐私模式下 localStorage 不可用时，仅当前页面生效 */
        }
        apply(next);
      });
    }
  });
})();
