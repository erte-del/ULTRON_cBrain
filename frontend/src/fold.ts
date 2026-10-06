// Voice-mode animation 3: the chat panel folds like paper. The top half (a static copy of
// the panel, .fold-leaf) swings down over the bottom half along the middle line, while the
// real panel is clipped to its bottom half. The leaf's other side is a panel back with a smiley.

const FLAT = 'perspective(1600px) rotateX(0deg)'
const FOLDED = 'perspective(1600px) rotateX(-180deg)'
// On the back of the fold: one eye a line, one a circle (tilted in App.css).
const SMILEY = `<svg viewBox="0 0 48 48" width="56" height="56" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M13 18h8"/><circle cx="31" cy="18" r="3.5"/><path d="M13 28q11 11 22 0"/></g></svg>`

export function makeFold(panel: HTMLElement, folded = false) {
  const r = panel.getBoundingClientRect()
  const leaf = document.createElement('div')
  leaf.className = 'fold-leaf'
  Object.assign(leaf.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height / 2}px` })
  // Folded, it's the back lying flat on the bottom half, unrotated (a rotated leaf would
  // drop upwards) and named for the drop (App.css). The name flattens 3D, so the swing
  // itself runs unnamed.
  const setFolded = (on: boolean) => {
    leaf.getAnimations().forEach((a) => a.cancel())
    leaf.classList.toggle('folded', on)
    leaf.style.top = `${on ? r.top + r.height / 2 : r.top}px`
    leaf.style.viewTransitionName = on ? 'fold' : 'none'
  }

  const front = panel.cloneNode(true) as HTMLElement
  front.classList.add('fold-front')
  front.style.height = `${r.height}px`
  const back = document.createElement('div')
  back.className = 'fold-back'
  back.innerHTML = SMILEY
  leaf.append(front, back)
  document.body.append(leaf)
  // A copy starts scrolled to the top: match the chat's scroll.
  const [from, to] = [panel, front].map((el) => el.querySelector('.messages'))
  if (from && to) to.scrollTop = from.scrollTop
  panel.style.clipPath = 'inset(50% 0 0 0)'
  setFolded(folded)

  return {
    swing: (down: boolean) => {
      setFolded(false)
      return leaf.animate([{ transform: down ? FLAT : FOLDED }, { transform: down ? FOLDED : FLAT }], {
        duration: 1000,
        easing: 'cubic-bezier(0.45, 0, 0.25, 1)',
        fill: 'forwards',
      }).finished.then(() => {
        if (down) setFolded(true)
      })
    },
    remove: () => {
      leaf.remove()
      panel.style.clipPath = ''
    },
  }
}
