import { Navigate, Route, Routes } from 'react-router'
import { LoginPage } from './auth/LoginPage'
import { LOGIN_PATH, RequireSession } from './auth/RequireSession'
import { RouteEditor } from './editor/RouteEditor'
import { InfoTab } from './editor/InfoTab'
import { MediaTab } from './editor/MediaTab'
import { PublishTab } from './editor/PublishTab'
import { StopsTab } from './editor/StopsTab'
import { VersionsTab } from './editor/VersionsTab'
import { AppShell } from './layout/AppShell'
import { ImportsPage } from './pages/ImportsPage'
import { RouteListPage } from './pages/RouteListPage'
import { TrashPage } from './pages/TrashPage'

/** Paths read like the design (page 04): /admin/lo-trinh/rt_…, /admin/dang-nhap. */
export function AppRoutes() {
  return (
    <Routes>
      <Route path={LOGIN_PATH} element={<LoginPage />} />
      <Route
        element={
          <RequireSession>
            <AppShell />
          </RequireSession>
        }
      >
        <Route path="/lo-trinh" element={<RouteListPage />} />
        <Route path="/nhap" element={<ImportsPage />} />
        <Route path="/thung-rac" element={<TrashPage />} />
      </Route>
      <Route
        path="/lo-trinh/:routeId"
        element={
          <RequireSession>
            <RouteEditor />
          </RequireSession>
        }
      >
        <Route index element={<Navigate to="diem-dung" replace />} />
        <Route path="thong-tin" element={<InfoTab />} />
        <Route path="diem-dung" element={<StopsTab />} />
        <Route path="anh-video" element={<MediaTab />} />
        <Route path="xuat-ban" element={<PublishTab />} />
        <Route path="phien-ban" element={<VersionsTab />} />
      </Route>
      <Route path="*" element={<Navigate to="/lo-trinh" replace />} />
    </Routes>
  )
}
