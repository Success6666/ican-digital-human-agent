const pendingScripts = new Map<string, Promise<void>>()

export function loadExternalScript(url: string, ready: () => boolean): Promise<void> {
  if (ready()) return Promise.resolve()
  const existing = pendingScripts.get(url)
  if (existing) return existing

  const promise = retryLoad(url, ready)
    .catch((cause) => {
      pendingScripts.delete(url)
      throw cause
    })

  pendingScripts.set(url, promise)
  return promise
}

async function retryLoad(url: string, ready: () => boolean): Promise<void> {
  let lastError: unknown
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await loadOnce(url, ready)
      return
    } catch (cause) {
      lastError = cause
      if (attempt < 2) await new Promise((resolve) => window.setTimeout(resolve, 220 * (attempt + 1)))
    }
  }
  throw lastError instanceof Error ? lastError : new Error('外部运行时加载失败')
}

function loadOnce(url: string, ready: () => boolean): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    const timeout = window.setTimeout(() => {
      script.remove()
      reject(new Error('外部运行时加载超时'))
    }, 20_000)
    script.src = url
    script.async = true
    script.crossOrigin = 'anonymous'
    script.onload = () => {
      window.clearTimeout(timeout)
      if (ready()) resolve()
      else reject(new Error('外部运行时未正确初始化'))
    }
    script.onerror = () => {
      window.clearTimeout(timeout)
      script.remove()
      reject(new Error('外部运行时加载失败'))
    }
    document.head.appendChild(script)
  })
}
