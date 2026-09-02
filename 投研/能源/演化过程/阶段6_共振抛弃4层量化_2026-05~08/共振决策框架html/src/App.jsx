import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import FrameworkPage from './pages/FrameworkPage'
import CompanyPage from './pages/CompanyPage'
import HomePage from './pages/HomePage'

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-neutral-50">
        <header className="bg-white shadow-sm border-b border-neutral-200 p-4">
          <nav className="max-w-5xl mx-auto flex gap-6">
            <Link to="/" className="text-blue-600 hover:text-blue-800">首页</Link>
            <Link to="/framework" className="text-blue-600 hover:text-blue-800">共振框架（通用版）</Link>
            <Link to="/company/ningde" className="text-blue-600 hover:text-blue-800">宁德时代·换电业务</Link>
          </nav>
        </header>
        <main>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/framework" element={<FrameworkPage />} />
            <Route path="/company/:companyId" element={<CompanyPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App