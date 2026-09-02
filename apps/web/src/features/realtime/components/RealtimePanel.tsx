import { Mic, MicOff, Plug, Radio, RotateCcw, Square, Volume2, WifiOff } from 'lucide-react'
import type { CSSProperties } from 'react'
import { StatusPill } from '../../../shared/components/StatusPill'
import type { RealtimeController } from '../model'

interface RealtimePanelProps {
  realtime: RealtimeController
}

export function RealtimePanel({ realtime }: RealtimePanelProps) {
  const { state } = realtime
  const connected = state.connection === 'connected'
  const recording = state.recording === 'recording' || state.recording === 'requesting'
  const connecting = state.connection === 'connecting' || state.connection === 'reconnecting'
  const status = statusPill(state.connection, state.phase)
  const transcript = state.interimTranscript || state.transcript

  return (
    <section className="realtime-panel" aria-labelledby="realtime-title">
      <div className="realtime-head">
        <div className="section-heading">
          <Radio size={16} aria-hidden="true" />
          <div><p className="eyebrow">REALTIME</p><h2 id="realtime-title">实时交互</h2></div>
        </div>
        <div className="realtime-actions">
          <StatusPill status={status.status} label={status.label} />
          {connected ? (
            <button className="icon-button" type="button" onClick={() => void realtime.disconnect()} aria-label="断开实时通道" title="断开实时通道"><WifiOff size={15} /></button>
          ) : (
            <button className="icon-button" type="button" onClick={() => void realtime.connect()} disabled={connecting || !realtime.textSupported} aria-label="连接实时通道" title="连接实时通道"><Plug size={15} className={connecting ? 'spin' : undefined} /></button>
          )}
      </div>
      </div>

      {!realtime.textSupported ? (
        <div className="realtime-degraded"><MicOff size={15} aria-hidden="true" /><span>先建立一个数字人会话</span></div>
      ) : (
        <>
          <div className="realtime-status-line"><span>{state.statusText}</span>{state.droppedFrames > 0 && <small>已丢弃 {state.droppedFrames} 帧</small>}</div>
          <div className="realtime-transcript" aria-live="off">
            <span>用户</span><p className={!transcript ? 'realtime-placeholder' : undefined}>{transcript || '按住麦克风或点击开始说话'}</p>
          </div>
          <div className="realtime-response" aria-live="polite">
            <div><Volume2 size={13} aria-hidden="true" /><span>数字人</span></div>
            <p className={!state.assistantText ? 'realtime-placeholder' : undefined}>{state.assistantText || '等待 Agent 响应'}</p>
          </div>
          {state.audioSupported ? (
            <div className="realtime-controls">
              <button className={`realtime-mic${recording ? ' realtime-mic--active' : ''}`} style={{ '--voice-level': String(state.audioLevel) } as CSSProperties} type="button" onClick={() => void realtime.toggleRecording()} disabled={connecting || state.connection !== 'connected'} aria-label={recording ? '结束录音' : '开始录音'} title={recording ? '结束录音' : '开始录音'}>
                {recording ? <Square size={16} /> : <Mic size={18} />}
                <span>{recording ? '结束' : '说话'}</span>
              </button>
              <button className="icon-button realtime-stop" type="button" onClick={() => void realtime.interrupt('user_interrupt')} disabled={!recording && !state.runId && state.playback !== 'playing'} aria-label="停止当前表达" title="停止当前表达"><RotateCcw size={15} /></button>
              <small>可以随时改口，上一轮会立即停止</small>
            </div>
          ) : (
            <div className="realtime-degraded"><MicOff size={15} aria-hidden="true" /><span>当前未配置语音输入，可继续使用文本对话</span></div>
          )}
        </>
      )}
    </section>
  )
}

function statusPill(connection: RealtimeController['state']['connection'], phase: RealtimeController['state']['phase']): { status: 'online' | 'offline' | 'pending' | 'active' | 'idle' | 'error'; label: string } {
  if (connection === 'connected') return phase === 'speaking' ? { status: 'active', label: '表达中' } : { status: 'online', label: '已连接' }
  if (connection === 'connecting' || connection === 'reconnecting') return { status: 'pending', label: '连接中' }
  if (connection === 'error' || phase === 'error') return { status: 'error', label: '异常' }
  if (connection === 'unsupported') return { status: 'offline', label: '文本模式' }
  return { status: 'idle', label: '未连接' }
}
