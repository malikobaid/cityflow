// web/assets/js/app.js
// make config available to page scripts

async function loadPartial(containerId, url) {
  const container = document.getElementById(containerId);
  if (!container) return;

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
  if (!v) return { baseRoot: '', baseV1: '' };
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
  await loadPartial("site-header", "partials/header.html");
  await loadPartial("site-footer", "partials/footer.html");

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
    fixLinks('site-header');
    fixLinks('site-footer');
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
