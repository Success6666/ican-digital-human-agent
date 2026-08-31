import { FilePlus2, LoaderCircle } from 'lucide-react'
import { useState, type ChangeEvent, type FormEvent } from 'react'
import type { IngestInput, IngestResult } from '../types'

interface IngestFormProps {
  isBusy: boolean
  result: IngestResult | null
  onSubmit: (input: IngestInput) => Promise<unknown>
}

export function IngestForm({ isBusy, result, onSubmit }: IngestFormProps) {
  const [sourceName, setSourceName] = useState('手工笔记.md')
  const [collection, setCollection] = useState('default')
  const [content, setContent] = useState('')
  const [file, setFile] = useState<File | undefined>()

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!sourceName.trim() || !collection.trim() || (!content.trim() && !file) || isBusy) return
    await onSubmit({ sourceName: sourceName.trim(), collection: collection.trim(), content: content.trim(), file })
    setContent('')
    setFile(undefined)
  }

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.files?.[0]
    setFile(next)
    if (next) setSourceName(next.name)
  }

  return (
    <section className="work-panel" aria-labelledby="ingest-title">
      <div className="section-heading"><div><p className="eyebrow">DOCUMENT INGEST</p><h2 id="ingest-title">文档文本入库</h2></div><FilePlus2 size={17} /></div>
      <form className="stack-form" onSubmit={submit}>
        <label>来源名称<input value={sourceName} onChange={(event) => setSourceName(event.target.value)} maxLength={200} /></label>
        <label>知识集合<input value={collection} onChange={(event) => setCollection(event.target.value)} maxLength={100} /></label>
        <label>本地文档<input type="file" accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.html" onChange={selectFile} /></label>
        <label>正文内容<textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="粘贴 Markdown 或纯文本内容" maxLength={100000} rows={10} /></label>
        <div className="form-actions"><small>{file ? `已选择 ${file.name}` : `${content.length.toLocaleString()} 字符`}</small><button className="primary-button" type="submit" disabled={isBusy || (!content.trim() && !file)}>{isBusy ? <LoaderCircle size={15} className="spin" /> : <FilePlus2 size={15} />}{isBusy ? '处理中' : '开始入库'}</button></div>
      </form>
      {result && <div className="success-note" role="status">已完成：{result.source_name || sourceName} · {result.chunk_count ?? 0} 个片段 · {result.parser === 'docling' ? 'Docling' : '文本解析'}</div>}
    </section>
  )
}
