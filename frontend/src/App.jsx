import { useState } from 'react'

function App() {
  const [count, setCount] = useState(0)

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-slate-100 flex items-center justify-center px-4">
      <div className="max-w-xl w-full text-center space-y-8">
        <h1 className="text-5xl font-bold tracking-tight">
          AWS Frontend
        </h1>
        <p className="text-slate-300">
          React + Vite + Tailwind CSS v3.4 (JavaScript)
        </p>

        <div className="flex items-center justify-center gap-4">
          <button
            onClick={() => setCount((c) => c - 1)}
            className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition shadow"
          >
            -
          </button>
          <span className="text-3xl font-mono w-16">{count}</span>
          <button
            onClick={() => setCount((c) => c + 1)}
            className="px-4 py-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 transition shadow"
          >
            +
          </button>
        </div>

        <p className="text-sm text-slate-400">
          Edit <code className="px-1 py-0.5 rounded bg-slate-800">src/App.jsx</code> and save to test HMR.
        </p>
      </div>
    </div>
  )
}

export default App
