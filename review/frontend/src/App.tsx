// Shared shell (header + nav) rendered around every page via <Outlet />.
import { NavLink, Outlet } from "react-router-dom";

export default function App() {
  return (
    <div className="min-h-screen bg-[#0c0f16]">
      <header className="border-b border-[#1c2431]">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <NavLink to="/" className="text-[17px] font-bold tracking-tight text-[#e4e8f0]">
            Resume<span className="text-[#4fd6f0]">Pipeline</span>
          </NavLink>
          <nav className="flex gap-2 text-sm">
            <NavLink
              to="/new"
              className={({ isActive }) =>
                `rounded-md border px-4 py-2 font-semibold transition-colors ${
                  isActive
                    ? "border-[#232b3a] bg-[#141924] text-[#e4e8f0]"
                    : "border-transparent text-[#6b7690] hover:text-[#e4e8f0]"
                }`
              }
            >
              + New
            </NavLink>
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `rounded-md border px-4 py-2 transition-colors ${
                  isActive
                    ? "border-[#232b3a] bg-[#141924] text-[#e4e8f0]"
                    : "border-transparent text-[#6b7690] hover:text-[#e4e8f0]"
                }`
              }
            >
              Applications
            </NavLink>
            <NavLink
              to="/master-resume"
              className={({ isActive }) =>
                `rounded-md border px-4 py-2 transition-colors ${
                  isActive
                    ? "border-[#232b3a] bg-[#141924] text-[#e4e8f0]"
                    : "border-transparent text-[#6b7690] hover:text-[#e4e8f0]"
                }`
              }
            >
              Resume
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
