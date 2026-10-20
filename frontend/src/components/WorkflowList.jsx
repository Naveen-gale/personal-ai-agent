import React, { useState } from 'react';

export default function WorkflowList({
  workflows,
  onRun,
  onToggleStatus,
  onSelectWorkflow,
  onDelete,
  onOpenCreate,
  runningWfId,
}) {
  const [filter, setFilter] = useState('all');

  const filtered = workflows.filter((w) => {
    if (filter === 'active') return w.status === 'active';
    if (filter === 'paused') return w.status === 'paused';
    return true;
  });

  return (
    <div className="workflows-container">
      <div className="workflows-toolbar">
        <div className="filter-group">
          <button
            className={`filter-btn ${filter === 'all' ? 'active' : ''}`}
            onClick={() => setFilter('all')}
          >
            All ({workflows.length})
          </button>
          <button
            className={`filter-btn ${filter === 'active' ? 'active' : ''}`}
            onClick={() => setFilter('active')}
          >
            Active ({workflows.filter((w) => w.status === 'active').length})
          </button>
          <button
            className={`filter-btn ${filter === 'paused' ? 'active' : ''}`}
            onClick={() => setFilter('paused')}
          >
            Paused ({workflows.filter((w) => w.status === 'paused').length})
          </button>
        </div>

        <button className="btn btn-primary" onClick={onOpenCreate}>
          + Create Workflow
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <p>No workflows found in this view.</p>
          <button className="btn btn-secondary" onClick={onOpenCreate}>
            Create your first workflow
          </button>
        </div>
      ) : (
        <div className="workflow-grid">
          {filtered.map((wf) => (
            <div key={wf.id} className={`workflow-card ${wf.status}`}>
              <div className="card-header">
                <div>
                  <h3 className="wf-title" onClick={() => onSelectWorkflow(wf)}>
                    {wf.name}
                  </h3>
                  <span className="wf-id">{wf.id}</span>
                </div>
                <span className={`badge badge-${wf.status}`}>{wf.status}</span>
              </div>

              <p className="wf-desc">{wf.description || 'No description provided.'}</p>

              <div className="wf-meta">
                <div className="meta-item">
                  <span className="meta-label">Trigger:</span>
                  <span className="meta-value">
                    {wf.trigger_type === 'scheduled'
                      ? `⏰ ${wf.trigger_config?.recurrence || 'Daily'} at ${wf.trigger_config?.time || '08:00'}`
                      : '⚡ Manual'}
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Steps:</span>
                  <span className="meta-value">{wf.steps?.length || 0} steps</span>
                </div>
                {wf.last_run_status && (
                  <div className="meta-item">
                    <span className="meta-label">Last Result:</span>
                    <span className={`meta-value status-${wf.last_run_status}`}>
                      {wf.last_run_status}
                    </span>
                  </div>
                )}
              </div>

              <div className="card-actions">
                <button
                  className="btn btn-sm btn-success"
                  onClick={() => onRun(wf.id)}
                  disabled={runningWfId === wf.id}
                >
                  {runningWfId === wf.id ? 'Running...' : '▶ Run Now'}
                </button>

                <button
                  className="btn btn-sm btn-outline"
                  onClick={() => onToggleStatus(wf)}
                >
                  {wf.status === 'active' ? '⏸ Pause' : '▶ Resume'}
                </button>

                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => onSelectWorkflow(wf)}
                >
                  Details
                </button>

                <button
                  className="btn btn-sm btn-danger-outline"
                  onClick={() => onDelete(wf.id)}
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
