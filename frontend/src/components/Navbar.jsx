import React from 'react';

export default function Navbar({ activeTab, setActiveTab, pendingCount, apiHealthy }) {
  return (
    <header className="app-header">
      <div className="header-brand">
        <div className="brand-logo">⚡</div>
        <div>
          <h1 className="brand-title">Personal AI Agent</h1>
          <span className="brand-subtitle">Automation & LangGraph Workflow Engine</span>
        </div>
      </div>

      <nav className="header-nav">
        <button
          className={`nav-tab ${activeTab === 'workflows' ? 'active' : ''}`}
          onClick={() => setActiveTab('workflows')}
        >
          Workflows
        </button>

        <button
          className={`nav-tab ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          💬 AI Chat
        </button>

        <button
          className={`nav-tab ${activeTab === 'approvals' ? 'active' : ''}`}
          onClick={() => setActiveTab('approvals')}
        >
          🛡️ Approvals
          {pendingCount > 0 && <span className="badge-count">{pendingCount}</span>}
        </button>
      </nav>

      <div className="header-status">
        <span className={`status-indicator ${apiHealthy ? 'online' : 'offline'}`}></span>
        <span className="status-label">{apiHealthy ? 'API Online' : 'API Connecting...'}</span>
      </div>
    </header>
  );
}
