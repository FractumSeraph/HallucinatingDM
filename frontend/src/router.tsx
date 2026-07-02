import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './pages/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { CampaignsPage } from './pages/CampaignsPage'
import { LobbyPage } from './pages/LobbyPage'
import { GameView } from './pages/GameView'
import { CharacterWizard } from './pages/CharacterWizard'
import { CharacterSheet } from './pages/CharacterSheet'

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
      { path: 'campaigns/:cid/scenes/:sid', element: <GameView /> },
      { path: 'campaigns/:cid/characters/new', element: <CharacterWizard /> },
      { path: 'campaigns/:cid/characters/:charId', element: <CharacterSheet /> },
      { path: '*', element: <div className="page-pad">Coming soon…</div> },
    ],
  },
])
