import { FormEvent, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useCampaign } from '../api/hooks'
import type { DocumentInfo, SearchHit } from '../api/types'
import { useLiveCache } from '../ws/useLiveCache'

export function SearchPage() {
  const { cid } = useParams() as { cid: string }
  const { data: campaign } = useCampaign(cid)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [searchError, setSearchError] = useState('')
  useLiveCache(cid)

  async function search(e: FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    setBusy(true)
    setSearchError('')
    try {
      setHits(await api.get<SearchHit[]>(`/campaigns/${cid}/search?q=${encodeURIComponent(query)}`))
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : 'Search failed — try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-pad container">
      <Link to={`/campaigns/${cid}`}>← {campaign?.name ?? 'Campaign'}</Link>
      <h1>Rules & lore search</h1>
      <form onSubmit={search} className="row" style={{ maxWidth: 640 }}>
        <input
          placeholder="e.g. grappled condition, opportunity attacks, fireball…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="grow"
        />
        <button className="btn-primary" disabled={busy}>
          Search
        </button>
      </form>

      {searchError && <p className="error-text">{searchError}</p>}
      {hits !== null && (
        <div className="col" style={{ marginTop: '1rem' }}>
          {hits.length === 0 && <p className="muted">No matches found.</p>}
          {hits.map((h, i) => (
            <div key={i} className="card">
              <div className="muted" style={{ fontSize: '0.8rem' }}>
                {h.section_path || h.document_title}
                {h.page_start > 0 && ` · p.${h.page_start}${h.page_end > h.page_start ? `–${h.page_end}` : ''}`}
              </div>
              <p style={{ whiteSpace: 'pre-wrap', margin: '0.4rem 0 0' }}>
                {h.text.length > 900 ? h.text.slice(0, 900) + '…' : h.text}
              </p>
            </div>
          ))}
        </div>
      )}

      <DocumentsPanel campaignId={cid} isDm={campaign?.my_role === 'dm'} />
    </div>
  )
}

export function DocumentsPanel({ campaignId, isDm }: { campaignId: string; isDm: boolean }) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')
  const { data: docs } = useQuery<DocumentInfo[]>({
    queryKey: ['campaigns', campaignId, 'documents'],
    queryFn: () => api.get(`/campaigns/${campaignId}/documents`),
    refetchInterval: (q) =>
      q.state.data?.some((d) => d.status === 'processing') ? 2000 : false,
  })

  async function upload(file: File) {
    setError('')
    const form = new FormData()
    form.append('file', file)
    try {
      await api.upload(`/campaigns/${campaignId}/documents`, form)
      await qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'documents'] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    }
  }

  return (
    <section style={{ marginTop: '2rem' }}>
      <h3>Sourcebooks</h3>
      <ul className="plain-list" style={{ maxWidth: 640 }}>
        {docs?.map((d) => (
          <li key={d.id} className="row card" style={{ padding: '0.5rem 0.9rem' }}>
            <span className="grow">
              📖 {d.title}
              <span className="muted" style={{ fontSize: '0.8rem' }}>
                {' '}
                {d.page_count > 0 && `· ${d.page_count} pages `}· {d.chunk_count} passages
              </span>
            </span>
            {d.status === 'processing' && <span className="badge">processing {d.progress}%</span>}
            {d.status === 'error' && (
              <span className="badge badge-fail" title={d.error}>
                error
              </span>
            )}
            {isDm && d.filename && (
              <button
                className="btn-danger"
                onClick={async () => {
                  await api.delete(`/documents/${d.id}`)
                  qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'documents'] })
                }}
              >
                Remove
              </button>
            )}
          </li>
        ))}
      </ul>
      {isDm && (
        <div style={{ marginTop: '0.75rem' }}>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            style={{ display: 'none' }}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) upload(file)
              e.target.value = ''
            }}
          />
          <button onClick={() => fileRef.current?.click()}>Upload PDF rulebook</button>
          <p className="muted" style={{ fontSize: '0.8rem' }}>
            Uploaded books are indexed so both you and the AI DM can cite them.
          </p>
          {error && <p className="error-text">{error}</p>}
        </div>
      )}
    </section>
  )
}
