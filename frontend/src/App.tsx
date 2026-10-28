import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './lib/auth'
import AuthPage from './pages/AuthPage'
import GroupsPage from './pages/GroupsPage'
import GroupPage from './pages/GroupPage'
import JoinPage from './pages/JoinPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage />} />
      <Route path="/" element={<RequireAuth><GroupsPage /></RequireAuth>} />
      <Route path="/g/:groupId" element={<RequireAuth><GroupPage /></RequireAuth>} />
      <Route path="/join/:code" element={<RequireAuth><JoinPage /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
