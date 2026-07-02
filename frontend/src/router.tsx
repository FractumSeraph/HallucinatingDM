import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './pages/AppLayout'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/campaigns" replace /> },
      // Routes land phase by phase: /login /register /campaigns /campaigns/:cid …
      { path: '*', element: <div className="page-pad">Coming soon…</div> },
    ],
  },
])
