import { Route, Routes } from 'react-router-dom'

import { AppShell } from '@/layout/AppShell'
import { Console } from '@/routes/Console'
import { NewRun } from '@/routes/NewRun'
import { NotFound } from '@/routes/NotFound'
import { Overview } from '@/routes/Overview'
import { Project } from '@/routes/Project'
import { Settings } from '@/routes/Settings'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Overview />} />
        <Route path="projects/:projectId" element={<Project />} />
        <Route path="projects/:projectId/runs/new" element={<NewRun />} />
        <Route path="projects/:projectId/runs/:runId" element={<Console />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
