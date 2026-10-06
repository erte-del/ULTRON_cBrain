// The switch between typing and voice mode (App.css, "Voice mode").
//
// The chat, log and terminal slide out on the real page first, then a view transition
// morphs what stays (core, stage, usage panel) to its new place. Going back it runs in
// reverse: the view transition, then they slide back in. Only the morph uses the view
// transition: a panel that exists on one side of it only can just pop in WebKit.

import { flushSync } from 'react-dom'

const SLIDE = {
  down: 'translateY(110vh)',
  left: 'translateX(calc(-100% - 40px))',
  right: 'translateX(calc(100% + 40px))',
}
type Way = keyof typeof SLIDE | 'fold'

// How the chat, log and terminal leave in each animation; they come back the same way.
const PANELS = ['.comms-panel', '.log-panel', '.terminal-panel']
const WAYS: Record<number, Way[]> = {
  1: ['down', 'right', 'right'],
  2: ['left', 'down', 'down'],
  3: ['fold', 'right', 'down'], // the chat folds in half first, then drops
}

function slide(el: HTMLElement, way: Way, out: boolean, delay = 0) {
  return el.animate([{ transform: 'none' }, { transform: SLIDE[way === 'fold' ? 'down' : way] }], {
    duration: out ? 700 : 750,
    delay,
    easing: out ? 'cubic-bezier(0.5, 0, 0.75, 0)' : 'cubic-bezier(0.25, 1, 0.5, 1)',
    direction: out ? 'normal' : 'reverse',
    fill: 'both', // coming back: off screen until its delay is up
  })
}

// One switch at a time: a click mid-animation waits its turn.
let queue = Promise.resolve()

/** Animate a layout change. `anim` 1-3 slides the chat, log and terminal (switching
 *  mode); 0 just morphs (a canvas opening or closing in voice mode). */
export function morph(change: () => void, to: 'voice' | 'text', anim = 0) {
  queue = queue.then(() => run(change, to, anim)).catch(() => {})
}

async function run(change: () => void, to: 'voice' | 'text', anim: number) {
  if (!document.startViewTransition || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return change()
  // Voice mode only moves the panels on a desktop-sized window (App.css).
  const desktop = window.matchMedia('(min-width: 1201px) and (min-height: 501px)').matches
  const ways = desktop ? (WAYS[anim] ?? []) : []
  const panels = ways.map((_, i) => document.querySelector<HTMLElement>(PANELS[i]))
  const fold = ways[0] === 'fold' && panels[0]
  let leaf: ReturnType<typeof makeFold> | null = null

  if (to === 'voice' && ways.length) {
    if (fold) {
      leaf = makeFold(fold)
      await leaf.swing(true)
    }
    await Promise.all([
      ...panels.map((el, i) => el && slide(el, ways[i], true).finished),
      leaf && slide(leaf.el, 'down', true).finished,
    ])
  }

  const entering: Animation[] = []
  const t = document.startViewTransition(() => {
    flushSync(change)
    if (to === 'voice') {
      panels.forEach((el) => el?.getAnimations().forEach((a) => a.cancel())) // hidden now
      leaf?.remove()
    } else if (ways.length) {
      if (fold) leaf = makeFold(fold, true)
      panels.forEach((el, i) => el && entering.push(slide(el, ways[i], false, 550)))
      if (leaf) entering.push(slide(leaf.el, 'down', false, 550))
    }
  })
  await t.finished.catch(() => {})
  await Promise.all(entering.map((a) => a.finished))
  entering.forEach((a) => a.cancel())
  if (leaf && to === 'text') {
    await leaf.swing(false)
    leaf.remove()
  }
}

// Animation 3's paper fold: the top half (a static copy of the panel, .fold-leaf) swings
// down over the bottom half along the middle line, while the real panel is clipped to
// its bottom half. The leaf's other side is a panel back with a smiley.

const FLAT = 'perspective(1600px) rotateX(0deg)'
const FOLDED = 'perspective(1600px) rotateX(-180deg)'
// On the back of the fold: one eye a line, one a circle (tilted in App.css).
const SMILEY = `<svg viewBox="0 0 48 48" width="56" height="56" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M13 18h8"/><circle cx="31" cy="18" r="3.5"/><path d="M13 28q11 11 22 0"/></g></svg>`

function makeFold(panel: HTMLElement, folded = false) {
  const r = panel.getBoundingClientRect()
  const leaf = document.createElement('div')
  leaf.className = 'fold-leaf'
  Object.assign(leaf.style, { left: `${r.left}px`, width: `${r.width}px`, height: `${r.height / 2}px` })
  // Folded, it's the back lying flat on the bottom half, unrotated, so it can slide with
  // the panel (a second transform animation would undo the rotation).
  const setFolded = (on: boolean) => {
    leaf.getAnimations().forEach((a) => a.cancel())
    leaf.classList.toggle('folded', on)
    leaf.style.top = `${on ? r.top + r.height / 2 : r.top}px`
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
    el: leaf,
    swing: (down: boolean) => {
      setFolded(false)
      return leaf
        .animate([{ transform: down ? FLAT : FOLDED }, { transform: down ? FOLDED : FLAT }], {
          duration: 1000,
          easing: 'cubic-bezier(0.45, 0, 0.25, 1)',
          fill: 'forwards',
        })
        .finished.then(() => {
          if (down) setFolded(true)
        })
    },
    remove: () => {
      leaf.remove()
      panel.style.clipPath = ''
    },
  }
}
