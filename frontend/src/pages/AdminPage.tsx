import { FormEvent, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'

interface Settings {
  provider: string
  llm_base_url: string
  llm_model: string
  llm_api_key_set: boolean
  llm_toolcall_mode: string
  embedding_base_url: string
  embedding_model: string
  embedding_api_key_set: boolean
  temperature: number
  max_tokens: number
}

interface TestReport {
  model: string
  base_url: string
  chat_ok?: boolean
  chat_reply?: string
  chat_error?: string
  embedding_ok?: boolean
  embedding_dim?: number
  embedding_error?: string
}

export function AdminPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [status, setStatus] = useState('')
  const [report, setReport] = useState<TestReport | null>(null)

  useEffect(() => {
    api.get<Settings>('/admin/settings').then(setSettings).catch(() => setStatus('Admin only.'))
  }, [])

  function field(key: string, fallback: string) {
    return form[key] ?? fallback
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setStatus('Saving…')
    try {
      const updated = await api.put<Settings>('/admin/settings', form)
      setSettings(updated)
      setForm({})
      setStatus('Saved. New settings apply to the next AI turn.')
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : 'Save failed')
    }
  }

  async function test() {
    setStatus('Testing connection…')
    setReport(null)
    try {
      const result = await api.post<TestReport>('/admin/settings/test-llm')
      setReport(result)
      setStatus('')
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : 'Test failed')
    }
  }

  async function reindex() {
    setStatus('Reindexing embeddings (this can take a while)…')
    try {
      const result = await api.post<{ chunks: number; embedded: number; error?: string }>(
        '/admin/reindex',
      )
      setStatus(
        result.error
          ? `Reindex failed: ${result.error}`
          : `Reindexed ${result.embedded}/${result.chunks} passages.`,
      )
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : 'Reindex failed')
    }
  }

  if (!settings) return <div className="page-pad muted">{status || 'Loading…'}</div>

  return (
    <div className="page-pad container" style={{ maxWidth: 720 }}>
      <h1>LLM settings</h1>
      <p className="muted">
        Point at any OpenAI-compatible endpoint: Ollama (<code>http://localhost:11434/v1</code>),
        LM Studio, vLLM, OpenRouter, OpenAI… Values here override the server's .env.
      </p>
      <form onSubmit={save} className="col card">
        <label className="muted">
          Provider
          <select
            value={field('provider', settings.provider)}
            onChange={(e) => setForm({ ...form, provider: e.target.value })}
          >
            <option value="openai_compat">OpenAI-compatible API</option>
            <option value="mock">Mock (demo, no LLM)</option>
          </select>
        </label>
        <label className="muted">
          Chat base URL
          <input
            value={field('base_url', settings.llm_base_url)}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          />
        </label>
        <label className="muted">
          Chat model
          <input
            value={field('model', settings.llm_model)}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
          />
        </label>
        <label className="muted">
          API key {settings.llm_api_key_set ? '(saved — leave blank to keep)' : '(not set)'}
          <input
            type="password"
            placeholder="sk-…"
            value={field('api_key', '')}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          />
        </label>
        <label className="muted">
          Tool-calling mode
          <select
            value={field('toolcall_mode', settings.llm_toolcall_mode)}
            onChange={(e) => setForm({ ...form, toolcall_mode: e.target.value })}
          >
            <option value="auto">auto (recommended)</option>
            <option value="native">native function calling</option>
            <option value="prompted">prompted JSON (small local models)</option>
          </select>
        </label>
        <label className="muted">
          Embedding base URL
          <input
            value={field('embedding_base_url', settings.embedding_base_url)}
            onChange={(e) => setForm({ ...form, embedding_base_url: e.target.value })}
          />
        </label>
        <label className="muted">
          Embedding model
          <input
            value={field('embedding_model', settings.embedding_model)}
            onChange={(e) => setForm({ ...form, embedding_model: e.target.value })}
          />
        </label>
        <div className="row">
          <button className="btn-primary">Save</button>
          <button type="button" onClick={test}>
            Test connection
          </button>
          <button type="button" onClick={reindex}>
            Rebuild search index
          </button>
        </div>
        {status && <p className="muted">{status}</p>}
        {report && (
          <div className="card" style={{ background: 'var(--bg-inset)' }}>
            <p>
              Chat: {report.chat_ok ? `✅ "${report.chat_reply}"` : `❌ ${report.chat_error}`}
            </p>
            <p>
              Embeddings:{' '}
              {report.embedding_ok
                ? `✅ ${report.embedding_dim} dimensions`
                : `❌ ${report.embedding_error}`}
            </p>
          </div>
        )}
      </form>

      <RegistrationSettings />
    </div>
  )
}

interface Instance {
  signup_mode: string
  signup_code: string
}

function RegistrationSettings() {
  const [instance, setInstance] = useState<Instance | null>(null)
  const [mode, setMode] = useState('open')
  const [code, setCode] = useState('')
  const [status, setStatus] = useState('')

  useEffect(() => {
    api
      .get<Instance>('/admin/instance')
      .then((i) => {
        setInstance(i)
        setMode(i.signup_mode)
        setCode(i.signup_code)
      })
      .catch(() => {})
  }, [])

  async function save(e: FormEvent) {
    e.preventDefault()
    setStatus('Saving…')
    try {
      const updated = await api.put<Instance>('/admin/instance', {
        signup_mode: mode,
        signup_code: code,
      })
      setInstance(updated)
      setStatus('Saved.')
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : 'Save failed')
    }
  }

  if (!instance) return null
  return (
    <>
      <h1 style={{ marginTop: '2rem' }}>Registration</h1>
      <p className="muted">
        Control who can create an account on this instance. Each group runs its own
        campaign; this only gates <em>signup</em>.
      </p>
      <form onSubmit={save} className="col card">
        <label className="muted">
          Who can sign up
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="open">Open — anyone with the link</option>
            <option value="invite">Invite code required</option>
            <option value="closed">Closed — no new accounts</option>
          </select>
        </label>
        {mode === 'invite' && (
          <label className="muted">
            Invite code (share with people you want to let in)
            <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. DRAGONS" />
          </label>
        )}
        <div className="row">
          <button className="btn-primary">Save</button>
          {status && <span className="muted">{status}</span>}
        </div>
      </form>
    </>
  )
}
