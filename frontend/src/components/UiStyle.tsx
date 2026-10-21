// Ultron's own look for this chat: the style sheet it wrote (change_ui), applied on top of the
// standard look. Whatever it says, the top bar (with the reset button) and the approval cards
// stay on screen, so a bad sheet can always be undone and nothing can hide a question.

const KEEP = `
html body .hud > .hud-top,
html body .hud > .hud-top .hud-actions,
html body .hud > .hud-top .reset-ui,
html body .confirm-card {
  visibility: visible !important;
  opacity: 1 !important;
  transform: none !important;
  clip-path: none !important;
  filter: none !important;
  pointer-events: auto !important;
}
html body .hud > .hud-top { display: grid !important; position: relative !important; height: auto !important; max-height: none !important; overflow: visible !important; z-index: 50 !important; }
html body .hud > .hud-top .hud-actions { display: flex !important; }
html body .hud > .hud-top .reset-ui { display: grid !important; width: 36px !important; height: 36px !important; position: static !important; }
html body .confirm-card { display: block !important; position: relative !important; width: auto !important; height: auto !important; max-height: none !important; }
`

export default function UiStyle({ css }: { css: string }) {
  return css ? <style data-ultron-ui>{css + KEEP}</style> : null
}
