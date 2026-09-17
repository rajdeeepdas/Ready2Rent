import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth.jsx'
import Layout from './components/Layout.jsx'
import RequireRole from './components/RequireRole.jsx'
import ApplicationDetail from './pages/ApplicationDetail.jsx'
import Health from './pages/Health.jsx'
import HomeownerHome from './pages/HomeownerHome.jsx'
import Intake from './pages/Intake.jsx'
import LandingPage from './pages/LandingPage.jsx'
import Login from './pages/Login.jsx'
import OpsApplication from './pages/OpsApplication.jsx'
import OpsQueue from './pages/OpsQueue.jsx'
import Register from './pages/Register.jsx'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public marketing page: has its own navbar, so it renders outside the app Layout. */}
          <Route path="/" element={<LandingPage />} />
          <Route path="signup" element={<Navigate to="/register" replace />} />

          <Route element={<Layout />}>
            <Route path="login" element={<Login />} />
            <Route path="register" element={<Register />} />

            <Route element={<RequireRole roles={['homeowner']} />}>
              <Route path="app" element={<HomeownerHome />} />
              <Route path="app/intake" element={<Intake />} />
              <Route path="app/applications/:id" element={<ApplicationDetail />} />
            </Route>

            <Route element={<RequireRole roles={['staff', 'admin']} />}>
              <Route path="ops" element={<OpsQueue />} />
              <Route path="ops/applications/:id" element={<OpsApplication />} />
              {/* Internal ops tool. Logged-out -> /login; homeowner -> their own dashboard. */}
              <Route path="health" element={<Health />} />
            </Route>

            <Route path="*" element={<p>Page not found.</p>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
