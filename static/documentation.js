(() => {
  const links = [...document.querySelectorAll('.docs-nav a[href^="#"]')];
  const sections = links.map(link => document.getElementById(link.hash.slice(1))).filter(Boolean);
  if (!sections.length) return;
  const activate = id => links.forEach(link => {
    if (link.hash === `#${id}`) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
  const update = () => {
    const current = sections.filter(section => section.getBoundingClientRect().top <= 100).pop() || sections[0];
    activate(current.id);
  };
  let scheduled = false;
  window.addEventListener('scroll', () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { update(); scheduled = false; });
  }, {passive: true});
  links.forEach(link => link.addEventListener('click', () => activate(link.hash.slice(1))));
  window.addEventListener('hashchange', update);
  update();
})();
