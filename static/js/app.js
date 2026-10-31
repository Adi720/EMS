/* EMS Seva: theme switch and copy-to-clipboard. No dependencies besides Bootstrap. */
(function () {
  "use strict";

  var root = document.documentElement;

  function currentTheme() {
    return root.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
  }

  function paintThemeButtons() {
    var dark = currentTheme() === "dark";
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      var icon = button.querySelector(".bi");
      if (icon) {
        icon.classList.toggle("bi-moon-stars", !dark);
        icon.classList.toggle("bi-sun", dark);
      }
      button.setAttribute("aria-pressed", dark ? "true" : "false");
      button.setAttribute("title", dark ? "Switch to light theme" : "Switch to dark theme");
    });
  }

  document.addEventListener("click", function (event) {
    var themeButton = event.target.closest("[data-theme-toggle]");
    if (themeButton) {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-bs-theme", next);
      try { localStorage.setItem("ems-theme", next); } catch (e) { /* private mode */ }
      paintThemeButtons();
      return;
    }

    var copyButton = event.target.closest("[data-copy-target]");
    if (copyButton) {
      var source = document.querySelector(copyButton.getAttribute("data-copy-target"));
      var status = document.querySelector(copyButton.getAttribute("data-copy-status"));
      if (!source) { return; }
      var text = source.value !== undefined ? source.value : source.textContent;
      var done = function () { if (status) { status.textContent = "Copied"; } };
      var fallback = function () {
        if (source.select) { source.select(); }
        try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ }
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
    }
  });

  paintThemeButtons();
})();
