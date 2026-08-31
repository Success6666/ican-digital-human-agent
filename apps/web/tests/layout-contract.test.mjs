import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const css = fs.readFileSync(path.resolve(here, '../src/pages/pages.css'), 'utf8')
const homeCss = fs.readFileSync(path.resolve(here, '../src/pages/home-reference.css'), 'utf8')

test('console keeps navigation fixed while main content owns scrolling', () => {
  assert.match(css, /\.console-shell\s*\{[^}]*overflow:\s*hidden/)
  assert.match(css, /\.console-main\s*\{[^}]*overflow-x:\s*hidden;[^}]*overflow-y:\s*auto/)
  assert.match(css, /\.console-body\s*\{[^}]*height:\s*calc\(100dvh\s*-\s*64px\)[^}]*min-height:\s*0/)
})

test('desktop navigation uses the compact width contract', () => {
  assert.match(css, /\.console-body\s*\{[^}]*--console-nav-width:\s*208px[^}]*grid-template-columns:\s+var\(--console-nav-width\)\s+minmax\(0,\s*1fr\)/)
  assert.match(css, /@media\s*\(max-width:\s*1020px\)[\s\S]*--console-nav-width:\s*192px/)
  assert.match(css, /\.console-brand\s*\{[^}]*min-width:\s*198px/)
  assert.match(css, /\.console-collapse-rail\s*\{[^}]*left:\s*calc\(var\(--console-nav-width\)\s*-\s*12px\)/)
})

test('avatar rendering layer cannot intercept conversation controls', () => {
  assert.match(homeCss, /\.avatar-runtime-host\s*\{[^}]*pointer-events:\s*none/)
  assert.match(homeCss, /\.avatar-runtime-shell\s*\{[^}]*pointer-events:\s*none/)
  assert.match(homeCss, /\.home-conversation-bar\s*\{[^}]*z-index:\s*20[^}]*pointer-events:\s*auto/)
})

test('home workspace owns the full console viewport', () => {
  assert.match(css, /\.console-main--home\s*\{[^}]*padding:\s*0[^}]*overflow:\s*hidden/)
  assert.match(homeCss, /\.console-main--home\s+\.home-page\s*\{[^}]*height:\s*100%[^}]*margin:\s*0/)
})
