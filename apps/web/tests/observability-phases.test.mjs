import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const here = path.dirname(fileURLToPath(import.meta.url))

/**
 * Compare array contents by value.
 *
 * The presentation module is executed in a separate VM realm, so its arrays
 * have a different Array prototype and `deepStrictEqual` would reject two
 * structurally identical arrays as "not reference-equal".
 */
function sameValues(actual, expected, message) {
  assert.equal(actual.length, expected.length, message)
  expected.forEach((value, index) => {
    assert.equal(actual[index], value, message)
  })
}

/**
 * Load the real presentation module so the assertions cover the shipped
 * aggregation logic rather than a re-implementation of it.
 */
function loadPresentation() {
  const source = fs.readFileSync(path.resolve(here, '../src/features/observability/presentation.ts'), 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(output, { module, exports: module.exports, require: () => ({}) })
  return module.exports
}

const { groupPhases, groupTraces, TRACE_PHASE_KEYS, eventLabel } = loadPresentation()

function event(name, offsetMs, extra = {}) {
  return {
    event_id: `${name}-${offsetMs}`,
    name,
    event_type: 'realtime',
    trace_id: 'trace-1',
    timestamp: new Date(Date.UTC(2026, 8, 11, 7, 0, 0, 0) + offsetMs).toISOString(),
    status: 'ok',
    attributes: {},
    ...extra,
  }
}

test('groups a full turn into the five end-to-end phases', () => {
  const events = [
    event('capture.recorder_started', 0),
    event('asr.response', 120),
    event('realtime.run_started', 200),
    event('agent.first_byte', 260),
    event('realtime.first_delta', 320),
    event('speech.assembled', 340),
    event('speak.dispatched', 360),
    event('speak.started', 380),
    event('speak.ended', 900),
  ]
  const phases = groupPhases(events)
  sameValues(phases.map((phase) => phase.key), TRACE_PHASE_KEYS)
  sameValues(phases.map((phase) => phase.key), ['capture', 'asr', 'agent', 'speech', 'playback'])
  assert.ok(phases.every((phase) => phase.observed))
  // The playback phase spans several markers, so it has a real duration.
  const playback = phases.find((phase) => phase.key === 'playback')
  assert.equal(playback.eventCount, 3)
  assert.equal(playback.durationMs, 540)
})

test('reports phases with no markers as gaps instead of hiding them', () => {
  const phases = groupPhases([event('agent.stream', 0)])
  const capture = phases.find((phase) => phase.key === 'capture')
  assert.equal(capture.observed, false)
  assert.equal(capture.eventCount, 0)
  // A missing phase must not claim a span, or it would look instantaneous.
  assert.equal(capture.durationMs, undefined)
  const agent = phases.find((phase) => phase.key === 'agent')
  assert.equal(agent.observed, true)
})

test('a single-marker phase keeps its offset but claims no duration', () => {
  const phases = groupPhases([event('capture.recorder_started', 0), event('speak.dispatched', 400)])
  const playback = phases.find((phase) => phase.key === 'playback')
  assert.equal(playback.observed, true)
  assert.equal(playback.startOffsetMs, 400)
  assert.equal(playback.durationMs, undefined)
})

test('a failing marker drives its phase status and carries the reason', () => {
  const phases = groupPhases([
    event('speak.dispatched', 0),
    event('speak.failed', 50, { status: 'error', error_message: '星云播报失败' }),
  ])
  const playback = phases.find((phase) => phase.key === 'playback')
  assert.equal(playback.status, 'error')
  assert.equal(playback.errorMessage, '星云播报失败')
})

test('TTSA warnings land in the playback phase they explain', () => {
  const phases = groupPhases([
    event('ttsa.warning', 0, { status: 'error', attributes: { reason: '暂无空闲房间' } }),
  ])
  const playback = phases.find((phase) => phase.key === 'playback')
  assert.equal(playback.observed, true)
  assert.equal(playback.status, 'error')
})

test('groupTraces marks browser-backed traces as end-to-end', () => {
  const browser = groupTraces([
    event('capture.recorder_started', 0, { attributes: { source: 'browser' } }),
    event('agent.stream', 100),
  ])[0]
  assert.equal(browser.origin, 'browser')
  assert.ok(browser.coverage.includes('capture'))

  const serverOnly = groupTraces([event('agent.stream', 0)])[0]
  assert.equal(serverOnly.origin, 'server')
  sameValues(serverOnly.coverage, ['agent'])
})

test('every phase bucket has a label and a known phase key', () => {
  for (const key of TRACE_PHASE_KEYS) {
    const phases = groupPhases([event('agent.stream', 0)])
    assert.ok(phases.every((phase) => typeof phase.label === 'string' && phase.label.length > 0))
  }
})

test('realtime markers have human-readable labels', () => {
  for (const name of ['capture.recorder_started', 'speech.assembled', 'speak.dispatched', 'ttsa.warning']) {
    const label = eventLabel({ name })
    assert.notEqual(label, name, `${name} should have a mapped label`)
  }
})
