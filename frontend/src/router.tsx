import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './pages/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { CampaignsPage } from './pages/CampaignsPage'
import { LobbyPage } from './pages/LobbyPage'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage mode="login" /> },
  { path: '/register', element: <LoginPage mode="register" /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/campaigns" replace /> },
      { path: 'campaigns', element: <CampaignsPage /> },
      { path: 'campaigns/:cid', element: <LobbyPage /> },
      { path: '*', element: <div className="page-pad">Coming soon…</div> },
    ],
  },
])
