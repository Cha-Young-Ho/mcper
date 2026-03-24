/**
 * CodeMirror 5 (gfm) + marked + DOMPurify (see markdown_editor_assets partial).
 * Mounts on .md-split-root[data-markdown-split]; syncs to inner textarea for form POST.
 * GFM 모드는 overlay 애드온이 필요함. 실패 시에도 좌(textarea) / 우(미리보기) 분할은 유지.
 */
(function () {
  function parseMarkdown(src) {
    if (typeof marked === "undefined") return "";
    var fn = marked.parse || marked;
    if (typeof fn !== "function") return "";
    try {
      return fn(src, { breaks: true, gfm: true });
    } catch (e) {
      return "<p class=\"md-prose-error\">미리보기 파싱 오류</p>";
    }
  }

  function sanitize(html) {
    if (typeof DOMPurify !== "undefined") return DOMPurify.sanitize(html);
    return html.replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function initRoot(root) {
    var ta = root.querySelector(".md-split__fallback");
    var mount = root.querySelector(".md-split__editor-mount");
    var preview = root.querySelector(".md-split__preview");
    if (!ta || !mount || !preview) return;

    function updatePreview() {
      preview.innerHTML = sanitize(parseMarkdown(ta.value));
    }

    if (typeof CodeMirror !== "undefined") {
      try {
        var cm = CodeMirror(mount, {
          value: ta.value || "",
          mode: "gfm",
          lineNumbers: true,
          lineWrapping: true,
          theme: "default",
        });

        function syncToTextarea() {
          ta.value = cm.getValue();
        }

        function onChange() {
          syncToTextarea();
          updatePreview();
        }

        cm.on("change", onChange);
        root.classList.add("md-split--active");
        onChange();

        var col = mount.closest(".md-split__editor-col") || mount.parentElement;

        function fitCm() {
          var h = mount.clientHeight;
          if (h < 48) return;
          cm.setSize(null, h);
          cm.refresh();
        }

        requestAnimationFrame(function () {
          requestAnimationFrame(fitCm);
        });

        if (typeof ResizeObserver !== "undefined" && col) {
          var ro = new ResizeObserver(function () {
            fitCm();
          });
          ro.observe(col);
        } else {
          window.addEventListener("resize", fitCm);
        }

        var form = ta.form;
        if (form) {
          form.addEventListener("submit", function () {
            syncToTextarea();
          });
        }
        return;
      } catch (e) {
        if (typeof console !== "undefined" && console.warn) {
          console.warn("[markdown-split] CodeMirror init failed, using textarea fallback", e);
        }
      }
    }

    ta.addEventListener("input", updatePreview);
    ta.addEventListener("change", updatePreview);
    updatePreview();
  }

  function boot() {
    document.querySelectorAll("[data-markdown-split]").forEach(initRoot);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
