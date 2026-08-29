import { LoaderCircle, Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import type { SearchInput, SearchHit } from '../types'

interface SearchFormProps {
  isBusy: boolean
  hits: SearchHit[]
  onSubmit: (input: SearchInput) => Promise<unknown>
}

export function SearchForm({ isBusy, hits, onSubmit }: SearchFormProps) {
  const [query, setQuery] = useState('')
  const [collection, setCollection] = useState('default')
  const [topK, setTopK] = useState(5)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!query.trim() || !collection.trim() || isBusy) return
    await onSubmit({ query: query.trim(), collection: collection.trim(), topK })
  }

  return (
    <section className="work-panel" aria-labelledby="search-title">
      <div className="section-heading"><div><p className="eyebrow">RETRIEVAL</p><h2 id="search-title">检索增强</h2></div><Search size={17} /></div>
      <form className="stack-form" onSubmit={submit}>
        <label>检索问题<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入要查找的内容" maxLength={4000} /></label>
        <div className="form-row"><label>知识集合<input value={collection} onChange={(event) => setCollection(event.target.value)} maxLength={100} /></label><label>返回数量<input type="number" min={1} max={20} value={topK} onChange={(event) => setTopK(Math.max(1, Math.min(20, Number(event.target.value) || 1)))} /></label></div>
        <div className="form-actions"><small>{hits.length ? `最近命中 ${hits.length} 个片段` : '等待检索'}</small><button className="secondary-button" type="submit" disabled={isBusy || !query.trim()}>{isBusy ? <LoaderCircle size={15} className="spin" /> : <Search size={15} />}{isBusy ? '检索中' : '执行检索'}</button></div>
      </form>
      <div className="search-results" aria-live="polite">
        {hits.length === 0 ? <div className="data-empty data-empty--small"><Search size={17} /><span>输入问题后查看命中片段</span></div> : hits.map((hit, index) => <article className="search-hit" key={`${hit.chunk?.ordinal ?? index}-${index}`}><div><span>片段 {hit.chunk?.ordinal ?? index + 1}</span><strong>{Math.max(0, Math.round((hit.score ?? 0) * 100))}% 相关</strong></div><p>{hit.chunk?.text || '无文本内容'}</p></article>)}
      </div>
    </section>
  )
}
