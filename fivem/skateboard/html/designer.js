// The skate shop's board page: Skate 3's own SKATEBOARD section (DECK / TRUCKS / WHEELS), as a page over the game.
// It is shown inside an iframe that sound.js makes when the Lua side (deck.lua) sends { t: 'designer', open: true }.
// Everything that is Skate 3's (names, brands, prices, words, thumbnails, logos) is read from skate3_assets at run
// time: <assets>decks/catalog.json. The words that are OURS, because the game has none for them here, are in OWN below.
//
// Lua -> page:   { t: 'designer', open: true, resource, assets, state }   { t: 'designer', open: false }
//                { t: 'designer_state', state }
// page -> Lua:   POST https://<resource>/designer_pick { kind, id }  ->  { ok, error, code, state }
//                POST https://<resource>/designer_close {}
// state = { money: number | false, owned: { deck: [ids], truck: [ids], wheel: [ids] }, design: { deck, truck, wheel } }
(function () {
  'use strict';

  const OWN = { use: 'Use', riding: 'On your board', none: 'Skate 3\'s board parts are not installed on this server.',
                noAnswer: 'The shop did not answer.' };
  const KINDS = [['deck', 'decks'], ['truck', 'trucks'], ['wheel', 'wheels']];
  const $ = (id) => document.getElementById(id);

  let resource = null, assets = '', cat = null, state = null;
  let tab = 'deck', filter = 'all', brand = null, selected = {}, busy = false, shown = [];

  function post(name, data) {
    return fetch('https://' + resource + '/' + name, {
      method: 'POST', headers: { 'Content-Type': 'application/json; charset=UTF-8' }, body: JSON.stringify(data || {}),
    }).then((r) => r.json()).catch(() => ({ ok: false, error: OWN.noAnswer }));
  }

  const word = (key, fallback) => (cat && cat.strings && cat.strings[key]) || fallback || key;
  const list = (kind) => (cat && cat[KINDS.find((k) => k[0] === kind)[1]]) || [];
  const owns = (kind, id) => !!(state && state.owned && state.owned[kind] && state.owned[kind].indexOf(id) >= 0);
  const riding = (kind) => state && state.design && state.design[kind];
  const money = () => (state && typeof state.money === 'number' ? state.money : null);

  // what the grid shows: the tab's parts through the filter (all / one brand / the ones I own)
  function visible() {
    return list(tab).filter((p) => (filter === 'owned' ? owns(tab, p.id) : filter === 'brands' && brand ? p.brand === brand : true));
  }

  function button(text, on, click) {
    const b = document.createElement('button');
    b.textContent = text;
    if (on) b.className = 'on';
    b.addEventListener('click', click);
    return b;
  }

  function render() {
    if (!cat || !state) return;
    $('title').textContent = word('skateboard', 'Skateboard');
    const tabs = $('tabs');
    tabs.textContent = '';
    KINDS.forEach(([kind, key]) => tabs.appendChild(button(word(key === 'decks' ? 'deck' : key, key), kind === tab, () => {
      tab = kind; brand = null; render(); })));
    $('wallet').textContent = money() === null ? '' : word('wallet', 'Total Cash:') + ' $' + money();

    const filters = $('filters');
    filters.textContent = '';
    const prefix = document.createElement('span');
    prefix.textContent = word('filterPrefix', 'Filter:');
    filters.appendChild(prefix);
    ['all', 'brands', 'owned'].forEach((f) => filters.appendChild(button(word(f, f), f === filter, () => { filter = f; render(); })));

    // the brands of this tab, by their logos (a brand the game has no logo for shows its name)
    const brands = $('brands');
    brands.textContent = '';
    brands.classList.toggle('hidden', filter !== 'brands');
    if (filter === 'brands') {
      const seen = {};
      list(tab).forEach((p) => {
        if (!p.brand || seen[p.brand]) return;
        seen[p.brand] = true;
        if (!brand) brand = p.brand;
        const b = button('', p.brand === brand, () => { brand = p.brand; render(); });
        b.title = p.brandName || p.brand;
        if (p.logo) { const i = document.createElement('img'); i.src = assets + p.logo; b.appendChild(i); } else b.textContent = p.brandName || p.brand;
        brands.appendChild(b);
      });
    }

    shown = visible();
    if (!shown.some((p) => p.id === selected[tab])) {
      const mine = shown.find((p) => p.id === riding(tab));
      selected[tab] = mine ? mine.id : (shown[0] && shown[0].id);
    }
    const grid = $('grid');
    grid.textContent = '';
    shown.forEach((p) => {
      const cell = document.createElement('div');
      cell.className = 'cell' + (owns(tab, p.id) ? ' owned' : '') + (p.id === riding(tab) ? ' riding' : '') + (p.id === selected[tab] ? ' on' : '');
      cell.dataset.id = p.id;
      cell.title = p.name;
      if (p.thumb) { const i = document.createElement('img'); i.src = assets + p.thumb; cell.appendChild(i); }
      cell.addEventListener('click', () => { selected[tab] = p.id; detail(); mark(); });
      cell.addEventListener('dblclick', act);
      grid.appendChild(cell);
    });
    detail();
    const on = grid.querySelector('.cell.on');
    if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
  }

  function mark() {
    document.querySelectorAll('#grid .cell').forEach((c) => c.classList.toggle('on', c.dataset.id === selected[tab]));
    const on = document.querySelector('#grid .cell.on');
    if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
  }

  // the part that is highlighted: its picture large, its brand and name, what it costs, and what the button does
  function detail(message) {
    const p = shown.find((x) => x.id === selected[tab]);
    const big = $('big'), act = $('act'), price = $('price');
    $('msg').textContent = '';
    if (message) {
      const m = $('msg');
      if (message.title) { const b = document.createElement('b'); b.textContent = message.title; m.appendChild(b); }
      m.appendChild(document.createTextNode(message.text || ''));
    }
    if (!p) { big.removeAttribute('src'); $('name').textContent = ''; $('brand').textContent = ''; price.textContent = ''; act.disabled = true; act.textContent = ''; $('logo').style.visibility = 'hidden'; return; }
    big.className = p.preview ? '' : 'small';
    // (the old picture must not stand in for the new one while it loads)
    const src = assets + (p.preview || p.thumb || '');
    if (big.dataset.src !== src) {
      big.dataset.src = src;
      big.style.visibility = 'hidden';
      big.onload = () => { big.style.visibility = 'visible'; };
      big.src = src;
    }
    $('logo').style.visibility = p.logo ? 'visible' : 'hidden';
    if (p.logo) $('logo').src = assets + p.logo;
    $('name').textContent = p.name;
    $('brand').textContent = p.brandName || '';
    price.textContent = '';
    const mine = owns(tab, p.id), on = p.id === riding(tab);
    if (mine) {
      price.textContent = on ? OWN.riding : word('alreadyOwned', 'Already Owned');
      act.textContent = OWN.use;
      act.disabled = on || busy;
    } else {
      const cost = p.price > 0 ? word('cost', 'Cost') + ' $' + p.price : word('free', 'Free!');
      price.textContent = cost;
      const short = money() !== null && p.price > money();
      if (short) { const s = document.createElement('span'); s.className = 'bad'; s.textContent = word('insufficient', 'Insufficient Funds'); price.appendChild(s); }
      act.textContent = cost;
      act.disabled = short || busy;
    }
  }

  // the button: ride a part I own, or buy one I do not (the server decides; the page only shows what it answers)
  function act() {
    const p = shown.find((x) => x.id === selected[tab]);
    if (!p || busy || $('act').disabled) return;
    busy = true;
    $('act').disabled = true;
    post('designer_pick', { kind: tab, id: p.id }).then((r) => {
      busy = false;
      if (r && r.state) state = r.state;
      render();
      if (!r || !r.ok) {
        detail(r && r.code === 'funds' ? { title: word('noCashTitle', 'Not enough cash!'), text: word('noCashDesc', '') }
          : { text: (r && r.error) || OWN.noAnswer });
      }
    });
  }

  function close() { if (resource) post('designer_close', {}); }

  function move(dx, dy) {
    const cells = Array.prototype.slice.call(document.querySelectorAll('#grid .cell'));
    if (!cells.length) return;
    let i = cells.findIndex((c) => c.dataset.id === selected[tab]);
    if (i < 0) i = 0;
    // how many cells are in a row, from where they have been laid out
    let cols = cells.findIndex((c) => c.offsetTop !== cells[0].offsetTop);
    if (cols < 1) cols = cells.length;
    const j = Math.max(0, Math.min(cells.length - 1, i + dx + dy * cols));
    selected[tab] = cells[j].dataset.id;
    mark();
    detail();
  }

  window.addEventListener('keydown', (e) => {
    if (!cat) { if (e.key === 'Escape') close(); return; }
    const order = KINDS.map((k) => k[0]);
    if (e.key === 'Escape') close();
    else if (e.key === 'Enter' || e.key === ' ') act();
    else if (e.key === 'ArrowLeft') move(-1, 0);
    else if (e.key === 'ArrowRight') move(1, 0);
    else if (e.key === 'ArrowUp') move(0, -1);
    else if (e.key === 'ArrowDown') move(0, 1);
    else if (e.key === 'Tab' || e.key === 'e' || e.key === 'E') { tab = order[(order.indexOf(tab) + 1) % 3]; brand = null; render(); }
    else if (e.key === 'q' || e.key === 'Q') { tab = order[(order.indexOf(tab) + 2) % 3]; brand = null; render(); }
    else if (e.key === 'f' || e.key === 'F') { const f = ['all', 'brands', 'owned']; filter = f[(f.indexOf(filter) + 1) % 3]; render(); }
    else return;
    e.preventDefault();
  });
  $('close').addEventListener('click', close);
  $('act').addEventListener('click', act);

  function open(m) {
    resource = m.resource;
    assets = m.assets || '';
    state = m.state || null;
    window.focus();
    fetch(assets + 'decks/catalog.json').then((r) => { if (!r.ok) throw new Error('no catalogue'); return r.json(); }).then((c) => {
      cat = c;
      $('none').classList.add('hidden');
      $('shop').classList.remove('hidden');
      render();
    }).catch(() => {
      cat = null;
      $('shop').classList.add('hidden');
      $('none').textContent = OWN.none;
      $('none').classList.remove('hidden');
    });
  }

  window.addEventListener('message', (e) => {
    const m = e.data;
    if (!m || typeof m !== 'object') return;
    if (m.t === 'designer' && m.open) open(m);
    else if (m.t === 'designer_state' && m.state) { state = m.state; if (!busy) render(); }
  });
})();
