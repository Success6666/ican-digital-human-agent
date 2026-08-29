import { useState, type FormEvent } from 'react'
import { Eye, EyeOff, LockKeyhole, LogIn, UserRound } from 'lucide-react'
import { useAuth } from '../model'

export function LoginForm() {
  const { login, error, clearError, isLoading } = useAuth()
  const [username, setUsername] = useState('demo')
  const [password, setPassword] = useState('demo123')
  const [showPassword, setShowPassword] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!username.trim() || !password) return
    clearError()
    try {
      await login({ username: username.trim(), password })
    } catch {
      // 错误已由 AuthProvider 提供给表单反馈。
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="login-title">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true"><span /></div>
          <div>
            <p className="eyebrow">DIGITAL HUMAN AGENT</p>
            <h1 id="login-title">进入控制台</h1>
          </div>
        </div>
        <p className="auth-intro">连接数字人 Provider，观察 Agent 的每一步响应。</p>
        <form className="login-form" onSubmit={handleSubmit}>
          <label className="field-label" htmlFor="username">用户名</label>
          <div className="input-shell">
            <UserRound size={18} aria-hidden="true" />
            <input
              id="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              placeholder="输入用户名"
              required
            />
          </div>
          <label className="field-label" htmlFor="password">密码</label>
          <div className="input-shell">
            <LockKeyhole size={18} aria-hidden="true" />
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              placeholder="输入密码"
              required
            />
            <button
              className="icon-button input-action"
              type="button"
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
              title={showPassword ? '隐藏密码' : '显示密码'}
              onClick={() => setShowPassword((visible) => !visible)}
            >
              {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary-button login-button" type="submit" disabled={isLoading}>
            <LogIn size={18} aria-hidden="true" />
            {isLoading ? '正在验证…' : '登录控制台'}
          </button>
        </form>
        <p className="auth-footnote">演示环境默认使用 mock Provider，真实厂商凭证由服务端托管。</p>
      </section>
      <aside className="auth-aside" aria-label="系统概览">
        <div className="signal-grid" aria-hidden="true" />
        <div className="aside-content">
          <span className="live-dot" />
          <p className="eyebrow">RUNTIME / 01</p>
          <h2>让每一次对话，都能被看见。</h2>
          <p>从认证、会话到工具调用，实时查看数字人 Agent 的完整链路。</p>
        </div>
        <div className="aside-stat"><strong>5</strong><span>可插拔 Provider</span></div>
      </aside>
    </main>
  )
}
