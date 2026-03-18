import "./App.css";

function App() {
  return (
    <main className="app-shell">
      <section className="hero-panel">
        <p className="eyebrow">ProxyMind</p>
        <h1>Bootstrap completed</h1>
        <p className="lead">
          The frontend scaffold is running on Vite, the backend is expected on
          FastAPI, and the repository is ready for the next vertical slice.
        </p>
        <div className="status-grid">
          <article>
            <span>Frontend</span>
            <strong>React 19 + Vite 8</strong>
          </article>
          <article>
            <span>Backend</span>
            <strong>FastAPI + structlog</strong>
          </article>
          <article>
            <span>Infra</span>
            <strong>Postgres, Qdrant, MinIO, Redis</strong>
          </article>
        </div>
      </section>
    </main>
  );
}

export default App;
