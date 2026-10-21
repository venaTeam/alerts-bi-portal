"""Portal dropdown assets layered over the shared presentation theme."""

from hashlib import sha256
from typing import Final

from alerts_bi_shared.ui.assets import STYLESHEET as SHARED_STYLESHEET

STYLESHEET: Final = (
    SHARED_STYLESHEET
    + """
.filter-toggle{font:inherit;color:var(--ink);cursor:pointer;display:inline-flex;align-items:center;gap:8px;min-height:38px;padding:0 12px;border:1px solid var(--line-strong);border-radius:6px;background:var(--surface);font-weight:600;font-size:13.5px;white-space:nowrap}
.filter-toggle:hover{border-color:var(--ink-2)}
.app-menu .filter-toggle{gap:20px;padding:9px 12px;font-size:14px;font-weight:400;background:var(--surface-2)}
#application-filter-toggle{anchor-name:--application-filter}
#week-filter-toggle{anchor-name:--week-filter}
.app-menu:has(:popover-open) .chev,.wk:has(:popover-open) .chev{transform:rotate(180deg)}
.app-popover.filter-popover,.menu-list.filter-popover{position:fixed;inset:0;margin:auto;color:var(--ink);max-width:calc(100vw - 32px);max-height:70vh;overflow-y:auto}
.app-popover.filter-popover{width:320px}
.app-search-label{display:block;font-size:13px;font-weight:600;margin-bottom:6px}
.app-search{box-sizing:border-box;width:100%;font:inherit;padding:8px 10px;border:1px solid var(--line-strong);border-radius:6px;background:var(--surface);color:var(--ink);margin-bottom:12px}
.app-options{max-height:35vh;overflow-y:auto}
.app-chips{align-items:flex-start}
.app-option[hidden],.app-search-empty[hidden]{display:none}
.app-chips-more{min-width:0;max-width:100%}
.app-chips-more summary{cursor:pointer;list-style:none;width:fit-content}
.app-chips-more summary::-webkit-details-marker{display:none}
.app-chips-more .app-chips{margin-top:8px}
.app-show-less,.app-chips-more[open] .app-show-more{display:none}
.app-chips-more[open] .app-show-less{display:inline}
.app-chip{overflow-wrap:anywhere}
.app-chip .app-show-more,.app-chip .app-show-less{font-size:13px;line-height:inherit}
.menu-list.filter-popover{width:max-content}
.ops{display:flex;flex-direction:column;gap:10px;margin:0}
.ops dt{display:flex;gap:6px;align-items:center;font-size:12.5px;color:var(--ink-2);margin-bottom:6px}
.ops dd{margin:0}
.op-list{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.op-list .chip{white-space:normal;overflow-wrap:anywhere;font-family:var(--mono);background:var(--surface-2);color:var(--ink);border:1px solid var(--line)}
.ops details summary{cursor:pointer;width:fit-content;font-size:12.5px;margin-top:6px}
.ops details[open] summary{margin-bottom:6px}
@supports(top:anchor(bottom)){
  .app-popover.filter-popover,.menu-list.filter-popover{inset:auto;top:anchor(bottom);margin:8px 0 0;position-try-fallbacks:flip-block,flip-inline}
  .app-popover.filter-popover{position-anchor:--application-filter;left:anchor(left)}
  .menu-list.filter-popover{position-anchor:--week-filter;right:anchor(right)}
  @media(max-width:600px){
    .app-popover.filter-popover,.menu-list.filter-popover{left:16px;right:16px;width:auto}
  }
}
"""
)

STYLESHEET_PATH: Final = f"/assets/portal-{sha256(STYLESHEET.encode()).hexdigest()[:12]}.css"

# Static code only: application names remain escaped HTML, never interpolated into JS.
APPLICATION_FILTER_SCRIPT: Final = """
(() => {
  const form = document.getElementById('application-filter-menu');
  if (!form) return;
  const search = form.querySelector('input[type="search"]');
  const options = Array.from(form.querySelectorAll('.app-option'));
  const checks = options.map(option => option.querySelector('input[type="checkbox"]'));
  const empty = form.querySelector('.app-search-empty');
  const scope = form.querySelector('input[name="scope"]');
  const filter = () => {
    const term = search.value.trim().toLocaleLowerCase();
    let matches = 0;
    options.forEach(option => {
      option.hidden = !option.textContent.toLocaleLowerCase().includes(term);
      if (!option.hidden) matches += 1;
    });
    empty.hidden = options.length === 0 || matches > 0;
  };
  const reset = () => {
    form.reset();
    checks.forEach(check => { check.disabled = false; });
    scope.disabled = false;
    filter();
  };
  search.addEventListener('input', filter);
  search.addEventListener('keydown', event => {
    if (event.key === 'Enter') event.preventDefault();
  });
  form.addEventListener('beforetoggle', reset);
  form.addEventListener('submit', () => {
    // Keep the initial all-applications meaning; never broaden an explicit subset.
    if (form.dataset.allApplications === 'true' && checks.every(check => check.checked)) {
      scope.disabled = true;
      checks.forEach(check => { check.disabled = true; });
    }
  });
})();
"""
APPLICATION_FILTER_SCRIPT_PATH: Final = (
    f"/assets/application-filter-{sha256(APPLICATION_FILTER_SCRIPT.encode()).hexdigest()[:12]}.js"
)
