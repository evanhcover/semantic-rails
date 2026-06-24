(function () {
  const searchInput = document.querySelector('[data-doc-search]');
  const navLinks = Array.from(document.querySelectorAll('.docs-nav a'));

  if (searchInput && navLinks.length > 0) {
    searchInput.addEventListener('input', function () {
      const term = searchInput.value.trim().toLowerCase();
      navLinks.forEach(function (link) {
        const label = (link.textContent || '').toLowerCase();
        link.style.display = label.includes(term) ? '' : 'none';
      });
    });
  }

  // A "section" is either an in-page <h2> (older / shorter pages) or a
  // collapsible <details class="doc-section"> (longer pages). For each one,
  // collect a stable id, a display label, and the element to scroll to.
  function collectSections() {
    const sections = [];
    const accordions = Array.from(
      document.querySelectorAll('.docs-main details.doc-section')
    );
    accordions.forEach(function (det, index) {
      if (!det.id) det.id = 'section-' + String(index + 1);
      const summary = det.querySelector(':scope > summary');
      const label = (summary ? summary.textContent : det.id).trim();
      sections.push({ id: det.id, label: label, element: det });
    });

    if (sections.length === 0) {
      const headings = Array.from(document.querySelectorAll('.docs-main h2'));
      headings.forEach(function (h, index) {
        if (!h.id) h.id = 'section-' + String(index + 1);
        sections.push({
          id: h.id,
          label: (h.textContent || h.id).trim(),
          element: h,
        });
      });
    }
    return sections;
  }

  const sections = collectSections();

  // Inject a sub-nav under the active sidebar entry so section headings
  // become a second-level nav that's always visible.
  const activeNavLink =
    document.querySelector('.docs-nav-children a.active') ||
    document.querySelector('.docs-nav a.active');

  let subnavInjected = false;

  if (activeNavLink && sections.length > 0) {
    subnavInjected = true;
    const subnav = document.createElement('div');
    subnav.className = 'docs-subnav';
    sections.forEach(function (s) {
      const a = document.createElement('a');
      a.href = '#' + s.id;
      a.textContent = s.label;
      a.dataset.targetId = s.id;
      subnav.appendChild(a);
    });
    activeNavLink.parentNode.insertBefore(subnav, activeNavLink.nextSibling);

    // Open the target <details> (and any ancestor <details>) when clicked,
    // then scroll into view smoothly.
    subnav.addEventListener('click', function (e) {
      const link = e.target.closest('a[data-target-id]');
      if (!link) return;
      const id = link.dataset.targetId;
      const target = document.getElementById(id);
      if (!target) return;
      if (target.tagName === 'DETAILS') target.open = true;
      let node = target.parentElement;
      while (node && node !== document.body) {
        if (node.tagName === 'DETAILS' && !node.open) node.open = true;
        node = node.parentElement;
      }
      subnav.querySelectorAll('a').forEach(function (n) {
        n.classList.remove('is-active');
      });
      link.classList.add('is-active');
    });

    // Scroll-spy: highlight the sub-nav entry for the section in view.
    if ('IntersectionObserver' in window) {
      const linkByid = {};
      subnav.querySelectorAll('a').forEach(function (n) {
        linkByid[n.dataset.targetId] = n;
      });
      const spy = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              const id = entry.target.id;
              if (!id) return;
              Object.values(linkByid).forEach(function (n) {
                n.classList.remove('is-active');
              });
              if (linkByid[id]) linkByid[id].classList.add('is-active');
            }
          });
        },
        { rootMargin: '-25% 0px -65% 0px', threshold: 0 }
      );
      sections.forEach(function (s) {
        spy.observe(s.element);
      });
    }

    // If the user lands on an anchor (e.g. /docs/foo.html#section-3), open
    // the target details on load.
    if (window.location.hash) {
      const id = window.location.hash.slice(1);
      const target = document.getElementById(id);
      if (target && target.tagName === 'DETAILS') target.open = true;
    }
  }

  // Populate the legacy "On this page" TOC slot only if the inline sub-nav
  // wasn't injected (to avoid showing the same anchor list twice).
  if (!subnavInjected) {
    const tocContainer = document.querySelector('[data-doc-toc]');
    if (tocContainer && sections.length > 0) {
      sections.forEach(function (s) {
        const anchor = document.createElement('a');
        anchor.href = '#' + s.id;
        anchor.textContent = s.label;
        tocContainer.appendChild(anchor);
      });
    }
  } else {
    // Hide the now-redundant "On this page" block on pages where we injected
    // the sub-nav (always, since the sub-nav covers the same anchors).
    const tocBlock = document.querySelector('.docs-sidebar .toc');
    if (tocBlock) tocBlock.style.display = 'none';
  }
})();
