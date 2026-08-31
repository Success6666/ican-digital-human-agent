import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const css = fs.readFileSync(path.resolve(here, '../src/pages/pages.css'), 'utf8')

test('console keeps navigation fixed while main content owns scrolling', () => {
  assert.match(css, /\.console-shell\s*\{[^}]*overflow:\s*hidden/)
  assert.match(css, /\.console-main\s*\{[^}]*overflow-x:\s*hidden;[^}]*overflow-y:\s*auto/)
  assert.match(css, /\.console-body\s*\{[^}]*height:\s*calc\(100dvh\s*-\s*64px\)[^}]*min-height:\s*0/)
})

test('desktop navigation uses the compact width contract', () => {
  assert.match(css, /\.console-body\s*\{[^}]*grid-template-columns:\s*208px\s+minmax\(0,\s*1fr\)/)
  assert.match(css, /@media\s*\(max-width:\s*1020px\)[\s\S]*grid-template-columns:\s*192px\s+minmax\(0,\s*1fr\)/)
  assert.match(css, /\.console-brand\s*\{[^}]*min-width:\s*198px/)
})
