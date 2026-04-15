import { create } from 'zustand'

const useWorkspaceStore = create((set, get) => ({
  workspaces: [],
  activeWorkspace: null,
  loading: false,

  fetchWorkspaces: async () => {
    set({ loading: true })
    try {
      const resp = await fetch('/api/workspaces')
      const data = await resp.json()
      set({ workspaces: data, loading: false })
    } catch {
      set({ loading: false })
    }
  },

  createWorkspace: async (body) => {
    const resp = await fetch('/api/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const ws = await resp.json()
    set(s => ({ workspaces: [ws, ...s.workspaces], activeWorkspace: ws }))
    return ws
  },

  setActiveWorkspace: (ws) => set({ activeWorkspace: ws }),

  updateWorkspace: async (id, body) => {
    const resp = await fetch(`/api/workspaces/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const updated = await resp.json()
    set(s => ({
      workspaces: s.workspaces.map(w => w.id === id ? updated : w),
      activeWorkspace: s.activeWorkspace?.id === id ? updated : s.activeWorkspace,
    }))
    return updated
  },

  deleteWorkspace: async (id) => {
    await fetch(`/api/workspaces/${id}`, { method: 'DELETE' })
    set(s => ({
      workspaces: s.workspaces.filter(w => w.id !== id),
      activeWorkspace: s.activeWorkspace?.id === id ? null : s.activeWorkspace,
    }))
  },
}))

export default useWorkspaceStore
