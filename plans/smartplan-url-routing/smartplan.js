(function () {
  'use strict';

  var body = document.body;
  var planId = body.dataset.planId;
  var pageId = body.dataset.pageId;
  var pageDepth = parseInt(body.dataset.pageDepth || '0', 10);
  if (!planId || !pageId) return;

  var STORAGE_KEY = 'smartplan:' + planId;

  function loadState() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      // localStorage disabled / quota — silently fail
    }
  }

  function getTree() {
    var el = document.getElementById('smartplan-tree');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  var tree = getTree();

  // ---------------- Section checkboxes ----------------

  var checkboxes = Array.prototype.slice.call(
    document.querySelectorAll('.section-check')
  );

  function applyCheckboxesFromState() {
    var state = loadState();
    var pageState = state[pageId] || {};
    checkboxes.forEach(function (cb) {
      cb.checked = !!pageState[cb.dataset.sectionId];
    });
  }

  function handleCheckboxChange(cb) {
    var state = loadState();
    if (!state[pageId]) state[pageId] = {};
    if (cb.checked) {
      state[pageId][cb.dataset.sectionId] = true;
    } else {
      delete state[pageId][cb.dataset.sectionId];
      if (Object.keys(state[pageId]).length === 0) delete state[pageId];
    }
    saveState(state);
    renderSidebar();
  }

  checkboxes.forEach(function (cb) {
    cb.addEventListener('change', function () {
      handleCheckboxChange(cb);
    });
  });

  // Make the entire section click-to-toggle. Skips clicks on interactive elements
  // (links, buttons, inputs, the checkbox's own label) and skips toggling when
  // the user is selecting text.
  var INTERACTIVE_SELECTOR = 'a, button, input, label, summary, details, textarea, select';

  function sectionFor(checkbox) {
    var el = checkbox;
    while (el && el !== document.body) {
      if (el.tagName === 'SECTION') return el;
      el = el.parentNode;
    }
    return null;
  }

  checkboxes.forEach(function (cb) {
    var section = sectionFor(cb);
    if (!section) return;

    section.classList.add('sp-section-clickable');

    section.addEventListener('click', function (e) {
      if (e.target.closest(INTERACTIVE_SELECTOR)) return;
      var sel = window.getSelection && window.getSelection();
      if (sel && sel.toString().length > 0) return;
      e.preventDefault();
      cb.checked = !cb.checked;
      cb.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });

  // ---------------- Sidebar ----------------

  function relHref(href) {
    if (!href) return '#';
    if (/^([a-z]+:)?\/\//i.test(href) || href.charAt(0) === '/') return href;
    return pageDepth > 0 ? new Array(pageDepth + 1).join('../') + href : href;
  }

  function nodeStatus(node, state) {
    if (!node.sections || node.sections.length === 0) return 'none';
    var pageState = state[node.id] || {};
    var total = node.sections.length;
    var read = 0;
    for (var i = 0; i < total; i++) {
      if (pageState[node.sections[i]]) read++;
    }
    if (read === 0) return 'none';
    if (read >= total) return 'complete';
    return 'partial';
  }

  function countTotals(node, state, acc) {
    if (node.sections && node.sections.length) {
      var pageState = state[node.id] || {};
      for (var i = 0; i < node.sections.length; i++) {
        acc.total++;
        if (pageState[node.sections[i]]) acc.read++;
      }
    }
    if (node.children) {
      for (var j = 0; j < node.children.length; j++) {
        countTotals(node.children[j], state, acc);
      }
    }
    return acc;
  }

  function renderNode(node, state) {
    var li = document.createElement('li');
    li.className = 'sp-tree-node';

    var a = document.createElement('a');
    a.className = 'sp-link' + (node.id === pageId ? ' is-current' : '');
    a.href = relHref(node.href);

    var dot = document.createElement('span');
    var status = nodeStatus(node, state);
    dot.className = 'sp-dot' + (status === 'complete' ? ' is-complete' : status === 'partial' ? ' is-partial' : '');
    dot.setAttribute('aria-hidden', 'true');
    a.appendChild(dot);

    var label = document.createElement('span');
    label.className = 'sp-label';
    label.textContent = node.label;
    a.appendChild(label);

    li.appendChild(a);

    if (node.children && node.children.length) {
      var ul = document.createElement('ul');
      for (var i = 0; i < node.children.length; i++) {
        ul.appendChild(renderNode(node.children[i], state));
      }
      li.appendChild(ul);
    }

    return li;
  }

  function renderSidebar() {
    var sidebar = document.getElementById('smartplan-sidebar');
    if (!sidebar || !tree) return;

    var state = loadState();

    sidebar.innerHTML = '';

    var eyebrow = document.createElement('p');
    eyebrow.className = 'sp-sidebar-title';
    eyebrow.textContent = 'SmartPlan';
    sidebar.appendChild(eyebrow);

    var planTitle = document.createElement('p');
    planTitle.className = 'sp-sidebar-plan';
    planTitle.textContent = tree.title || 'Plan';
    sidebar.appendChild(planTitle);

    var ul = document.createElement('ul');
    ul.className = 'sp-tree';
    ul.appendChild(renderNode(tree.root, state));
    sidebar.appendChild(ul);

    // Progress
    var totals = countTotals(tree.root, state, { read: 0, total: 0 });
    var pct = totals.total === 0 ? 0 : Math.round((totals.read / totals.total) * 100);

    var prog = document.createElement('div');
    prog.className = 'sp-progress';
    prog.innerHTML =
      '<span>' + totals.read + ' / ' + totals.total + ' sections read · ' + pct + '%</span>' +
      '<div class="sp-progress-bar"><div class="sp-progress-fill" style="width:' + pct + '%"></div></div>';
    sidebar.appendChild(prog);

    var reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'sp-reset';
    reset.textContent = 'Reset read state';
    reset.addEventListener('click', function () {
      if (window.confirm('Clear read state for this whole plan?')) {
        try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
        applyCheckboxesFromState();
        renderSidebar();
      }
    });
    sidebar.appendChild(reset);
  }

  // Cross-tab sync
  window.addEventListener('storage', function (e) {
    if (e.key === STORAGE_KEY) {
      applyCheckboxesFromState();
      renderSidebar();
    }
  });

  applyCheckboxesFromState();
  renderSidebar();

  // ---------------- Mermaid ----------------
  // Initialised with a palette that matches the editorial theme.
  // The CDN script is loaded by each page; we wait for it.
  function initMermaidWhenReady() {
    if (typeof window.mermaid === 'undefined') {
      if (document.querySelectorAll('.mermaid').length === 0) return;
      setTimeout(initMermaidWhenReady, 50);
      return;
    }
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'base',
        themeVariables: {
          fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", "Helvetica Neue", sans-serif',
          fontSize: '14px',
          primaryColor: '#fbfaf7',
          primaryTextColor: '#1a1814',
          primaryBorderColor: '#c9c3b6',
          lineColor: '#6b6660',
          secondaryColor: '#f0d8c8',
          tertiaryColor: '#f5f3ee',
          tertiaryBorderColor: '#c9c3b6',
          tertiaryTextColor: '#1a1814',
          background: '#ffffff',
          mainBkg: '#fbfaf7',
          nodeBorder: '#c9c3b6',
          clusterBkg: '#f5f3ee',
          clusterBorder: '#e5e1d8',
          edgeLabelBackground: '#fbfaf7'
        }
      });
      window.mermaid.run({ querySelector: '.mermaid' });
    } catch (e) {
      // best-effort; failures shouldn't break the page
    }
  }
  initMermaidWhenReady();
})();
