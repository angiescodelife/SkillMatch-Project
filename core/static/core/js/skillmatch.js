/* SkillMatch: small progressive enhancements. Every action still posts a
   normal form, so pages work without JavaScript (except modals). */
(function () {
  'use strict';

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function csrfToken() {
    var input = $('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  // Password visibility toggles
  $$('[data-toggle-password]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = document.getElementById(btn.getAttribute('data-toggle-password'));
      if (!input) return;
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.setAttribute('aria-pressed', show ? 'true' : 'false');
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      $$('.eye-on', btn).forEach(function (el) { el.hidden = show; });
      $$('.eye-off', btn).forEach(function (el) { el.hidden = !show; });
    });
  });

  // Live password hint on registration
  $$('[data-password-hint]').forEach(function (input) {
    var hint = document.getElementById(input.getAttribute('data-password-hint'));
    if (!hint) return;
    function check() {
      var v = input.value;
      var ok = v.length >= 8 && /\d/.test(v) && /[^A-Za-z0-9]/.test(v);
      hint.classList.toggle('ok', ok);
    }
    input.addEventListener('input', check);
    check();
  });

  // Modals: <button data-open-modal="id">, <dialog id> with [data-close-modal]
  $$('[data-open-modal]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var dlg = document.getElementById(btn.getAttribute('data-open-modal'));
      if (!dlg || typeof dlg.showModal !== 'function') return;
      // Prefill edit modals from data-* attributes on the trigger
      $$('[data-fill]', dlg).forEach(function (el) {
        var key = el.getAttribute('data-fill');
        var value = btn.getAttribute('data-' + key);
        if (value === null) return;
        if (el.tagName === 'FORM') { el.action = value; }
        else if ('value' in el && el.tagName !== 'DIV' && el.tagName !== 'SPAN') { el.value = value; el.dispatchEvent(new Event('input')); }
        else { el.textContent = value; }
      });
      dlg.showModal();
      var first = $('input:not([type=hidden]), select, textarea', dlg);
      if (first) first.focus();
    });
  });
  $$('dialog.modal').forEach(function (dlg) {
    $$('[data-close-modal]', dlg).forEach(function (b) {
      b.addEventListener('click', function () { dlg.close(); });
    });
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
    if (dlg.hasAttribute('data-open-on-load')) dlg.showModal();
  });

  // Range inputs with a live value + level label
  $$('[data-range-output]').forEach(function (range) {
    var out = document.getElementById(range.getAttribute('data-range-output'));
    function level(v) { return v >= 80 ? 'Advanced' : (v >= 40 ? 'Intermediate' : 'Beginner'); }
    function update() {
      if (out) out.textContent = range.value + '% · ' + level(+range.value);
    }
    range.addEventListener('input', update);
    update();
  });
  $$('[data-range-value]').forEach(function (range) {
    var out = document.getElementById(range.getAttribute('data-range-value'));
    function update() { if (out) out.textContent = range.value + '%'; }
    range.addEventListener('input', update);
    update();
  });

  // Range track fill (WebKit has no native progress pseudo-element)
  $$('input[type=range]').forEach(function (r) {
    function fill() {
      var min = +r.min || 0, max = +r.max || 100;
      r.style.setProperty('--pct', ((r.value - min) / (max - min) * 100) + '%');
    }
    r.addEventListener('input', fill);
    fill();
  });

  // Close <details> menus when clicking elsewhere
  document.addEventListener('click', function (e) {
    $$('details[open].dropdown, details[open].user-menu').forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute('open');
    });
  });

  // Ctrl/⌘ + K focuses the search box
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      var s = $('#global-search');
      if (s) { e.preventDefault(); s.focus(); }
    }
  });

  // Confirm destructive actions
  $$('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.confirm(form.getAttribute('data-confirm'))) e.preventDefault();
    });
  });

  // Save / unsave without a page reload
  $$('form[data-save-toggle]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.fetch) return;
      e.preventDefault();
      fetch(form.action, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'fetch' },
        credentials: 'same-origin'
      }).then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
        .then(function (data) {
          $$('form[action="' + form.getAttribute('action') + '"]').forEach(function (f) {
            var btn = $('button', f);
            btn.classList.toggle('active', data.saved);
            btn.setAttribute('aria-pressed', data.saved ? 'true' : 'false');
            btn.setAttribute('aria-label', data.saved ? 'Remove from saved' : 'Save opportunity');
            var label = $('[data-save-label]', f);
            if (label) label.textContent = data.saved ? 'Saved' : 'Save opportunity';
          });
          $$('[data-saved-count]').forEach(function (el) { el.textContent = data.count; });
        })
        .catch(function () { form.submit(); });
    });
  });

  // Skills table: search + category filter (client-side, instant)
  var skillSearch = $('#skill-search');
  var skillCategory = $('#skill-category');
  function filterSkills() {
    var q = (skillSearch && skillSearch.value || '').trim().toLowerCase();
    var cat = skillCategory ? skillCategory.value : '';
    var shown = 0;
    $$('[data-skill-row]').forEach(function (row) {
      var ok = (!q || row.getAttribute('data-name').indexOf(q) !== -1) &&
               (!cat || row.getAttribute('data-category') === cat);
      row.hidden = !ok;
      if (ok) shown++;
    });
    var empty = $('#skill-filter-empty');
    if (empty) empty.hidden = shown !== 0;
  }
  if (skillSearch) skillSearch.addEventListener('input', filterSkills);
  if (skillCategory) skillCategory.addEventListener('change', filterSkills);

  // CV drag & drop: submits the upload form when a file is chosen/dropped
  $$('[data-dropzone]').forEach(function (zone) {
    var input = $('input[type=file]', zone);
    var form = zone.closest('form');
    var status = $('[data-dz-status]', zone);
    function submitWith(file) {
      if (!file) return;
      if (status) status.textContent = 'Uploading and reading ' + file.name + '…';
      zone.classList.add('dragging');
      form.submit();
    }
    $$('[data-browse]', zone).forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); input.click(); });
    });
    input.addEventListener('change', function () { submitWith(input.files[0]); });
    ['dragenter', 'dragover'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add('dragging'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.remove('dragging'); });
    });
    zone.addEventListener('drop', function (e) {
      if (!e.dataTransfer.files.length) return;
      input.files = e.dataTransfer.files;
      submitWith(input.files[0]);
    });
  });

  // Opportunity filters: auto-submit on change; mobile toggle
  // Submit a GET form without empty parameters (keeps URLs readable)
  function submitClean(form) {
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.name && !el.disabled && el.value === '' ) el.disabled = true;
      if (el.name === 'min' && el.value === '0') el.disabled = true;
    });
    form.submit();
  }
  $$('form[data-autosubmit]').forEach(function (form) {
    form.addEventListener('submit', function (e) { e.preventDefault(); submitClean(form); });
    // form.elements includes controls placed elsewhere with form="id"
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.type === 'checkbox' || el.type === 'range' || el.tagName === 'SELECT') {
        el.addEventListener('change', function () { submitClean(form); });
      }
    });
  });
  $$('[data-toggle-target]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var el = document.getElementById(btn.getAttribute('data-toggle-target'));
      if (!el) return;
      var open = el.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  });

  // Animate progress rings/bars in from zero
  if (!window.matchMedia || !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    $$('.ring-fill[data-offset]').forEach(function (c) {
      var target = c.getAttribute('data-offset');
      c.style.strokeDashoffset = c.getAttribute('stroke-dasharray');
      requestAnimationFrame(function () { requestAnimationFrame(function () { c.style.strokeDashoffset = target; }); });
    });
  }

  // Review page: select all / none
  $$('[data-check-all]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var on = btn.getAttribute('data-check-all') === 'on';
      $$('input[data-review-check]').forEach(function (c) { c.checked = on; });
    });
  });
})();
