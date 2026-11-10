import { NavLink, Outlet } from 'react-router'
import { useSession } from '../auth/session'
import { Logo } from '../ui/Icon'
import css from './AppShell.module.css'

/** Top bar of the list pages (page 04 A). The editor has its own bar (page 04 B). */
export function AppShell() {
  const { logout } = useSession()
  const link = ({ isActive }: { isActive: boolean }) =>
    isActive ? `${css.link} ${css.active}` : css.link
  return (
    <div className={css.shell}>
      <header className={css.bar}>
        <NavLink to="/lo-trinh" className={css.brand}>
          <Logo size={26} />
          <span>Lữ Trình · quản trị</span>
        </NavLink>
        <nav className={css.nav} aria-label="Chính">
          <NavLink to="/lo-trinh" className={link}>
            Lộ trình
          </NavLink>
          <NavLink to="/thung-rac" className={link}>
            Thùng rác
          </NavLink>
        </nav>
        <div className={css.user}>
          admin ·{' '}
          <button type="button" className={css.logout} onClick={() => void logout()}>
            Đăng xuất
          </button>
        </div>
      </header>
      <main className={css.main}>
        <Outlet />
      </main>
    </div>
  )
}
