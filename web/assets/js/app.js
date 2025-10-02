// web/assets/js/app.js
// make config available to page scripts

// Load an HTML partial into a container. Accepts either
//   loadPartial('/partials/header.html', 'siteHeader')  // (path, targetId)
// or
//   loadPartial('siteHeader', '/partials/header.html')  // (targetId, path)
async function loadPartial(a, b) {
  let path, targetId;
  // Heuristic: if first arg looks like a URL/path or ends with .html, treat it as path
  if (typeof a === 'string' && (a.includes('/') || /\.html?$/i.test(a))) {
    path = a; targetId = b;
  } else {
    targetId = a; path = b;
  }
  if (!targetId || !path) return;

  const container = document.getElementById(String(targetId));
  if (!container) return;

  // Force absolute path so pages under subpaths (e.g., /docs/) still work
  const url = path.startsWith('/') ? path : ('/' + path.replace(/^\/+/, ''));

  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`Failed to fetch ${url}`);
    container.innerHTML = await resp.text();
  } catch (err) {
    console.error(`Error loading partial ${url}:`, err);
  }
}

function webRootPrefix(){
  try {
    const path = window.location.pathname || '';
    return path.startsWith('/web/') ? '/web' : '';
  } catch { return ''; }
}

async function loadSiteConfig() {
  const prefix = webRootPrefix();
  const candidates = [
    `${prefix}/config/site.json?v=${Date.now()}`,
    `/web/config/site.json?v=${Date.now()}`,
    `config/site.json?v=${Date.now()}`,
  ];
  for (const url of candidates) {
    try {
      const resp = await fetch(url);
      if (resp.ok) return await resp.json();
    } catch {}
  }
  return {}; // default = mock mode
}

function deriveApiBases(raw) {
  const v = (raw || '').trim();
  if (!v) return { baseRoot: '', baseV1: '/v1' };
  // Normalize: remove trailing slashes
  let u = v.replace(/\/+$/, '');
  // If it already ends with /v1, keep that as baseV1 and derive root
  if (/\/v1$/i.test(u)) {
    const baseRoot = u.replace(/\/v1$/i, '');
    return { baseRoot, baseV1: baseRoot + '/v1' };
  }
  // Otherwise treat as root and append /v1
  const baseRoot = u;
  return { baseRoot, baseV1: baseRoot + '/v1' };
}

async function initLayout() {
  await loadPartial('/partials/header.html', 'siteheader');
  await loadPartial('/partials/footer.html', 'sitefooter');

  // Adjust header/footer nav links to work when site is served under /web/ locally
  try {
    const path = window.location.pathname || '';
    const prefix = path.startsWith('/web/') ? '/web' : '';
    const fixLinks = (rootId) => {
      const root = document.getElementById(rootId);
      if (!root) return;
      root.querySelectorAll('a[href]')?.forEach(a => {
        const href = a.getAttribute('href') || '';
        if (!href || href.startsWith('http') || href.startsWith('#') || href.startsWith('mailto:')) return;
        if (href.startsWith('/')) {
          // already absolute to domain; prefix if needed
          if (prefix && !href.startsWith(prefix + '/')) a.setAttribute('href', prefix + href);
        } else {
          // make absolute to site root, with optional /web prefix for local testing
          a.setAttribute('href', prefix + '/' + href.replace(/^\/*/, ''));
        }
      });
    };
    fixLinks('siteheader');
    fixLinks('sitefooter');
  } catch {}

  // Load config and update UI
  const config = await loadSiteConfig();
  // make config and derived API bases available to page scripts
  window.SK = window.SK || {};
  const api = deriveApiBases((config && config.apiBaseUrl) || '');
  window.SK.config = config;
  window.SK.api = api; // { baseRoot, baseV1 }

  // Reflect in localStorage for legacy code that still reads it
  try {
    if (api.baseRoot) localStorage.setItem('API_BASE', api.baseRoot);
  } catch {}

  // Notify listeners (include derived api in event detail for convenience)
  window.dispatchEvent(new CustomEvent('sk:config-ready', { detail: { ...config, api } }));
  // Toggle Mock badge
  const mockBadge = document.getElementById("mock-badge");
  if (mockBadge) {
    if (config.apiBaseUrl && config.apiBaseUrl.trim() !== "") {
      mockBadge.style.display = "none";
    } else {
      mockBadge.style.display = "inline-block";
    }
  }

  // Update version in footer
  const versionSpan = document.getElementById("app-version");
  if (versionSpan && config.version) {
    versionSpan.textContent = config.version;
  }
}

document.addEventListener("DOMContentLoaded", initLayout);
