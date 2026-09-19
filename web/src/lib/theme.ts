/**
 * Look and feel, kept on two independent axes.
 *
 *   mode    system | light | dark   -- the surfaces
 *   accent  which colour the buttons, links and progress bars use
 *
 * They are independent on purpose. A theme that bundles "dark plus orange"
 * gives you six themes and none of the twelve combinations anybody wanted, and
 * every new accent would need a second set of surfaces to go with it.
 *
 * What the accent deliberately does NOT touch is the chart series colours.
 * Those are chosen to stay distinguishable to a colourblind reader and to each
 * other; letting a theme repaint them would quietly break every chart in the
 * app for the people who need them most. A chart's identity colours are data,
 * not decoration.
 *
 * The preference is per browser, in localStorage, because that is exactly what
 * it is -- how this person likes to look at it on this screen. It is never sent
 * anywhere and it does not belong in the household's database.
 */

export type Mode = 'system' | 'light' | 'dark'

export type Accent = {
  key: string
  label: string
  /** A swatch for the picker: the accent as it appears in light mode. */
  swatch: string
}

/**
 * Desaturated, and each one is paired with an ink that actually reads on it.
 * No neon: this is an app people look at while worrying about money, and a
 * glowing button is the wrong note.
 */
export const ACCENTS: Accent[] = [
  { key: 'evergreen', label: 'Evergreen', swatch: '#127a57' },
  { key: 'ocean', label: 'Ocean', swatch: '#1f6feb' },
  { key: 'ember', label: 'Ember', swatch: '#b8501f' },
  { key: 'plum', label: 'Plum', swatch: '#8d3b6f' },
  { key: 'slate', label: 'Slate', swatch: '#4a5568' },
  { key: 'gold', label: 'Gold', swatch: '#8a6410' },
]

export const MODES: { key: Mode; label: string; hint: string }[] = [
  { key: 'system', label: 'System', hint: 'Follow the device' },
  { key: 'light', label: 'Light', hint: 'Always light' },
  { key: 'dark', label: 'Dark', hint: 'Always dark' },
]

const MODE_KEY = 'tally.mode'
const ACCENT_KEY = 'tally.accent'
const CONTRAST_KEY = 'tally.contrast'

/** localStorage throws in a private window and returns nothing after a clear,
 *  so every read and write is wrapped and every default stands on its own. */
function read(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) || fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* a preference that cannot be saved is still worth applying for this visit */
  }
}

export function getMode(): Mode {
  const m = read(MODE_KEY, 'system')
  return m === 'light' || m === 'dark' ? m : 'system'
}

export function getAccent(): string {
  const a = read(ACCENT_KEY, 'evergreen')
  return ACCENTS.some((x) => x.key === a) ? a : 'evergreen'
}

export function getContrast(): boolean {
  return read(CONTRAST_KEY, '0') === '1'
}

/** What `system` currently resolves to. */
export function resolvedMode(mode: Mode = getMode()): 'light' | 'dark' {
  if (mode !== 'system') return mode
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

/** Tell the browser chrome, so the phone status bar stops disagreeing with the page. */
function syncBrowserChrome(resolved: 'light' | 'dark') {
  const colour = getComputedStyle(document.documentElement).getPropertyValue('--page').trim()
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.remove())
  const meta = document.createElement('meta')
  meta.name = 'theme-color'
  meta.content = colour || (resolved === 'dark' ? '#0e0f0e' : '#f5f5f1')
  document.head.appendChild(meta)
}

export function apply(mode: Mode = getMode(), accent: string = getAccent(),
                      contrast: boolean = getContrast()) {
  const root = document.documentElement
  const resolved = resolvedMode(mode)
  root.setAttribute('data-theme', resolved)
  root.setAttribute('data-accent', accent)
  root.toggleAttribute('data-contrast', contrast)
  syncBrowserChrome(resolved)
  // Charts read CSS tokens rather than re-deriving colours, so one event is
  // enough to keep every one of them honest.
  window.dispatchEvent(new CustomEvent('tally:theme'))
}

export function setMode(mode: Mode) {
  write(MODE_KEY, mode)
  apply(mode)
}

export function setAccent(accent: string) {
  write(ACCENT_KEY, accent)
  apply(undefined, accent)
}

export function setContrast(on: boolean) {
  write(CONTRAST_KEY, on ? '1' : '0')
  apply(undefined, undefined, on)
}

/** Follow the OS while the choice is `system`, and stop when it is not. */
export function watchSystem() {
  try {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => { if (getMode() === 'system') apply() }
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  } catch {
    return () => {}
  }
}
