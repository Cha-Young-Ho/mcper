/**
 * Admin shell: mobile nav, active link, delete confirm, optional Escape to close.
 */
(function () {
  "use strict";

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function setNavOpen(layout, open) {
    if (!layout) return;
    layout.classList.toggle("is-nav-open", open);
    var toggle = qs("[data-nav-toggle]");
    if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function highlightNav() {
    var path = window.location.pathname;
    var rulesOpen =
      path.indexOf("/admin/global-rules") === 0 ||
      path.indexOf("/admin/repo-rules") === 0 ||
      path.indexOf("/admin/app-rules") === 0;
    var rulesDetails = qs("[data-nav-rules-group]");
    if (rulesDetails && rulesOpen) {
      rulesDetails.open = true;
    }
    qsa(".admin-nav a[data-nav]").forEach(function (a) {
      var key = a.getAttribute("data-nav");
      var active = false;
      if (key === "home" && (path === "/admin" || path === "/admin/")) active = true;
      else if (key === "plan-code" && path.indexOf("/admin/plan-code") === 0) active = true;
      else if (key === "plans" && path.indexOf("/admin/plans") === 0) active = true;
      else if (key === "global-rules" && path.indexOf("/admin/global-rules") === 0) active = true;
      else if (key === "repo-rules" && path.indexOf("/admin/repo-rules") === 0) active = true;
      else if (key === "app-rules" && path.indexOf("/admin/app-rules") === 0) active = true;
      else if (key === "tools" && path.indexOf("/admin/tools") === 0) active = true;
      else if (key === "seed" && path.indexOf("/admin/seed") === 0) active = true;
      a.classList.toggle("is-active", active);
    });
    if (rulesDetails) {
      rulesDetails.classList.toggle("is-active-parent", rulesOpen);
    }
  }

  function bindDeleteForms() {
    qsa("form[data-confirm-delete]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        var msg = form.getAttribute("data-confirm-delete") || "삭제할까?";
        if (!window.confirm(msg)) e.preventDefault();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var layout = qs("#admin-layout");
    var toggle = qs("[data-nav-toggle]");
    var backdrop = qs("[data-nav-backdrop]");

    highlightNav();
    bindDeleteForms();

    if (toggle && layout) {
      toggle.addEventListener("click", function () {
        setNavOpen(layout, !layout.classList.contains("is-nav-open"));
      });
    }

    if (backdrop && layout) {
      backdrop.addEventListener("click", function () {
        setNavOpen(layout, false);
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && layout && layout.classList.contains("is-nav-open")) {
        setNavOpen(layout, false);
      }
    });
  });
})();
