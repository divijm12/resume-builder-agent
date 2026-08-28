import { NavLink, Outlet } from "react-router-dom";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center gap-6 px-6 py-4">
          <span className="text-lg font-semibold">Resume Pipeline</span>
          <nav className="flex gap-4 text-sm">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                isActive ? "font-medium text-slate-900" : "text-slate-500 hover:text-slate-900"
              }
            >
              Applications
            </NavLink>
            <NavLink
              to="/new"
              className={({ isActive }) =>
                isActive ? "font-medium text-slate-900" : "text-slate-500 hover:text-slate-900"
              }
            >
              New application
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
