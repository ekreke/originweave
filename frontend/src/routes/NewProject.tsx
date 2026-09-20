import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { useCreateProject } from '@/api/hooks'

// New-project form (CreateProject). A project must exist before a run can be created,
// so this is the entry point that lets a fresh server be used at all. The id is the
// registry key (frozen after creation); the server rejects duplicates (ALREADY_EXISTS)
// and the reserved id "new" (which collides with this route).
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const RESERVED_IDS = new Set(['new'])

export function NewProject() {
  const navigate = useNavigate()
  const createProject = useCreateProject()

  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [accent, setAccent] = useState('')
  const [error, setError] = useState('')

  const valid = ID_RE.test(id.trim()) && !RESERVED_IDS.has(id.trim()) && Boolean(name.trim())

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!valid || createProject.isPending) return
    setError('')
    try {
      const project = await createProject.mutateAsync({
        id: id.trim(),
        name: name.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
        ...(accent.trim() ? { accent: accent.trim() } : {}),
      })
      const projectId = project?.id ?? id.trim()
      navigate(`/projects/${projectId}`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>新建项目</h2>
          <span className="cnt mono">CreateProject</span>
        </div>
        <form className="new-run" onSubmit={submit}>
          <label>
            <div className="cnt">项目 id（字母数字开头，可用 . _ -；不可用 new）</div>
            <input
              className="btn"
              aria-label="project id"
              placeholder="copilot-productivity"
              value={id}
              onChange={(event) => setId(event.target.value)}
            />
          </label>
          <label>
            <div className="cnt">名称</div>
            <input
              className="btn"
              aria-label="project name"
              placeholder="项目名称"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            <div className="cnt">描述（可选）</div>
            <input
              className="btn"
              aria-label="project description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label>
            <div className="cnt">强调色（可选，如 #4c8bf5）</div>
            <input
              className="btn"
              aria-label="project accent"
              value={accent}
              onChange={(event) => setAccent(event.target.value)}
            />
          </label>
          <div>
            <button className="btn" type="submit" disabled={!valid || createProject.isPending}>
              {createProject.isPending ? '创建中…' : '创建项目'}
            </button>
          </div>
          {error ? <p className="form-error">{error}</p> : null}
        </form>
      </div>
    </div>
  )
}
