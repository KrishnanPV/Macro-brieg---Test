import { BrowserRouter, Routes, Route } from 'react-router-dom'
import WorkspaceShell from './WorkspaceShell'
import Landing from './views/Landing/Landing'
import Dashboard from './views/Dashboard/Dashboard'
import CountryBrief from './views/CountryBrief/CountryBrief'
import Notebook from './views/Notebook/Notebook'
import KnowledgeGraph from './views/KnowledgeGraph/KnowledgeGraph'
import NewsLab from './views/NewsLab/NewsLab'
import BriefBuilder from './views/BriefBuilder/BriefBuilder'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<WorkspaceShell />}>
          <Route index element={<Landing />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="country-brief" element={<CountryBrief />} />
          <Route path="notebook" element={<Notebook />} />
          <Route path="graph" element={<KnowledgeGraph />} />
          <Route path="news" element={<NewsLab />} />
          <Route path="briefs" element={<BriefBuilder />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
