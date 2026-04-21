import { BrowserRouter, Routes, Route } from 'react-router-dom'
import WorkspaceShell from './WorkspaceShell'
import Landing from './views/Landing/Landing'
import Dashboard from './views/Dashboard/Dashboard'
import CountryBrief from './views/CountryBrief/CountryBrief'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<WorkspaceShell />}>
          <Route index element={<Landing />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="country-brief" element={<CountryBrief />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
