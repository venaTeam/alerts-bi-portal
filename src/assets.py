"""Portal-specific dropdown styling layered over the shared presentation theme."""

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
.menu-list.filter-popover{width:max-content}
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
