import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { canAccessPath, firstAllowedPath } from '../config/pages'

/** Redirects away from routes the user is not allowed to open. */
export default function PageAccessGuard({ children }) {
  const { user } = useAuth()
  const location = useLocation()
  const allowed = user?.allowed_pages || []

  if (!canAccessPath(allowed, location.pathname)) {
    return <Navigate to={firstAllowedPath(allowed)} replace />
  }

  return children
}
