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
    var domainParam = new URLSearchParams(window.location.search).get("domain") || "";

    var rulesOpen =
      path.indexOf("/admin/global-rules") === 0 ||
      path.indexOf("/admin/repo-rules") === 0 ||
      path.indexOf("/admin/app-rules") === 0 ||
      path.indexOf("/admin/rules-dev") === 0;

    var skillsOpen =
      path.indexOf("/admin/global-skills") === 0 ||
      path.indexOf("/admin/repo-skills") === 0 ||
      path.indexOf("/admin/app-skills") === 0 ||
      path.indexOf("/admin/skills-dev") === 0;

    var plansOpen =
      path.indexOf("/admin/plans") === 0 ||
      path.indexOf("/admin/plan-code") === 0;

    var rulesDetails  = qs("[data-nav-rules-group]");
    var skillsDetails = qs("[data-nav-skills-group]");
    var plansDetails  = qs("[data-nav-plans-group]");

    if (rulesDetails)  rulesDetails.open  = rulesOpen;
    if (skillsDetails) skillsDetails.open = skillsOpen;
    if (plansDetails)  plansDetails.open  = plansOpen;

    // 규칙/스킬 경로 판별 헬퍼
    var isRulesPath = path.indexOf("/admin/global-rules") === 0 ||
                      path.indexOf("/admin/repo-rules") === 0 ||
                      path.indexOf("/admin/app-rules") === 0;
    var isSkillsPath = path.indexOf("/admin/global-skills") === 0 ||
                       path.indexOf("/admin/repo-skills") === 0 ||
                       path.indexOf("/admin/app-skills") === 0;

    qsa(".admin-nav a[data-nav]").forEach(function (a) {
      var key = a.getAttribute("data-nav");
      var active = false;
      if (key === "home" && (path === "/admin" || path === "/admin/")) active = true;
      else if (key === "bulk-upload" && path.indexOf("/admin/plans/bulk-upload") === 0) active = true;
      else if (key === "plan-code" && path.indexOf("/admin/plan-code") === 0) active = true;
      else if (key === "plans" && path.indexOf("/admin/plans") === 0 && path.indexOf("/admin/plans/bulk-upload") !== 0) active = true;
      // 도메인 기반 Rules
      else if (key === "rules-planning" && isRulesPath && domainParam === "planning") active = true;
      else if (key === "rules-analysis" && isRulesPath && domainParam === "analysis") active = true;
      else if (key === "rules-development") {
        active = path.indexOf("/admin/rules-dev") === 0 ||
                 (isRulesPath && domainParam === "development");
      }
      // 도메인 기반 Skills
      else if (key === "skills-planning" && isSkillsPath && domainParam === "planning") active = true;
      else if (key === "skills-analysis" && isSkillsPath && domainParam === "analysis") active = true;
      else if (key === "skills-development") {
        active = path.indexOf("/admin/skills-dev") === 0 ||
                 (isSkillsPath && domainParam === "development");
      }
      // 기타
      else if (key === "users"  && path.indexOf("/admin/users") === 0) active = true;
      else if (key === "tools"  && path.indexOf("/admin/tools") === 0)  active = true;
      else if (key === "celery" && path.indexOf("/admin/celery") === 0) active = true;
      a.classList.toggle("is-active", active);
    });

    if (rulesDetails)  rulesDetails.classList.toggle("is-active-parent", rulesOpen);
    if (skillsDetails) skillsDetails.classList.toggle("is-active-parent", skillsOpen);
    if (plansDetails)  plansDetails.classList.toggle("is-active-parent", plansOpen);

    // details 토글 시 다른 그룹이 닫히지 않도록 — 클릭해도 열린 채 유지
    qsa(".admin-nav-group").forEach(function (details) {
      details.addEventListener("toggle", function () {
        // 브라우저가 details를 닫으려 할 때(open=false) 해당 그룹이 현재 경로와
        // 매칭되면 다시 강제로 열어준다
        if (!details.open) {
          var isRules  = details === rulesDetails  && rulesOpen;
          var isSkills = details === skillsDetails && skillsOpen;
          var isPlans  = details === plansDetails  && plansOpen;
          if (isRules || isSkills || isPlans) {
            details.open = true;
          }
        }
      });
    });
  }

  function bindDeleteForms() {
    qsa("form[data-confirm-delete]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        var msg = form.getAttribute("data-confirm-delete") || "삭제할까?";
        if (!window.confirm(msg)) e.preventDefault();
      });
    });
  }

  // ── 카드 실시간 검색 + 페이지네이션 ─────────────────────────────────
  function initCardSearch() {
    qsa("[data-card-container]").forEach(function (container) {
      var input   = container.querySelector("input[data-card-search]");
      var items   = qsa("[data-card-label]", container);
      var pgEl    = container.querySelector("[data-card-pagination]");
      var countEl = container.querySelector("[data-card-count]");
      var PER_PAGE = parseInt(container.getAttribute("data-per-page") || "20", 10);

      if (!items.length) return;

      var filtered = items.slice();
      var page = 1;

      function filterItems(q) {
        q = (q || "").toLowerCase().trim();
        filtered = items.filter(function (el) {
          return !q || el.getAttribute("data-card-label").toLowerCase().indexOf(q) >= 0;
        });
        page = 1;
        render();
      }

      function render() {
        items.forEach(function (el) { el.style.display = "none"; });
        var start = (page - 1) * PER_PAGE;
        filtered.slice(start, start + PER_PAGE).forEach(function (el) { el.style.display = ""; });
        if (countEl) countEl.textContent = filtered.length + "개";
        renderPagination();
      }

      function renderPagination() {
        if (!pgEl) return;
        var totalPages = Math.ceil(filtered.length / PER_PAGE);
        if (totalPages <= 1) { pgEl.innerHTML = ""; return; }

        var range = buildRange(page, totalPages);
        var html = '<nav class="pg-nav">';
        html += pgBtn(page - 1, "‹", page <= 1);
        range.forEach(function (p) {
          if (p === -1) html += '<span class="pg-ellipsis">…</span>';
          else html += pgBtn(p, p, false, p === page);
        });
        html += pgBtn(page + 1, "›", page >= totalPages);
        html += "</nav>";
        pgEl.innerHTML = html;

        qsa(".pg-btn:not([disabled])", pgEl).forEach(function (btn) {
          btn.addEventListener("click", function () {
            page = parseInt(btn.getAttribute("data-pg"), 10);
            render();
            container.scrollIntoView({ behavior: "smooth", block: "start" });
          });
        });
      }

      function pgBtn(pg, label, disabled, active) {
        var cls = "pg-btn" + (active ? " is-active" : "");
        return '<button class="' + cls + '" data-pg="' + pg + '"' +
          (disabled ? " disabled" : "") + ">" + label + "</button>";
      }

      function buildRange(cur, total) {
        if (total <= 7) {
          var a = [];
          for (var i = 1; i <= total; i++) a.push(i);
          return a;
        }
        var r = [1];
        if (cur > 3) r.push(-1);
        var s = Math.max(2, cur - 1), e = Math.min(total - 1, cur + 1);
        for (var i = s; i <= e; i++) r.push(i);
        if (cur < total - 2) r.push(-1);
        r.push(total);
        return r;
      }

      // 입력 이벤트
      if (input) {
        input.addEventListener("input", function () { filterItems(input.value); });
        // form 안에 있으면 submit 막기 (서버 재로드 방지)
        var form = input.closest("form");
        if (form) {
          form.addEventListener("submit", function (e) {
            e.preventDefault();
            e.stopImmediatePropagation();
            filterItems(input.value);
          }, true);
        }
      }

      render();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var layout = qs("#admin-layout");
    var toggle = qs("[data-nav-toggle]");
    var backdrop = qs("[data-nav-backdrop]");

    highlightNav();
    bindDeleteForms();
    initCardSearch();

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
