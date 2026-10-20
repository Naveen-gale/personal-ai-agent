import { useEffect, useState } from 'react';
import { apiFetch } from '../api';

export default function WorkflowDetailModal({
  workflow,
  onClose,
  onRun,
  runningWfId,
}) {
  const [executions, setExecutions] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [selectedExec, setSelectedExec] = useState(null);

  useEffect(() => {
    if (workflow) {
      loadHistory();
    }
  }, [workflow]);

  async function loadHistory() {
    setLoadingHistory(true);
    try {
      const res = await apiFetch(`/api/workflows/${workflow.id}/executions?limit=10`);
      const data = await res.json();
      if (data.success) {
        setExecutions(data.executions || []);
      }
    } catch (err) {
      console.error('Failed to load history', err);
    } finally {
      setLoadingHistory(false);
    }
  }

  if (!workflow) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>{workflow.name}</h2>
            <span className="text-muted">{workflow.description}</span>
          </div>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          <div className="detail-section">
            <h3>Pipeline Steps ({workflow.steps?.length || 0})</h3>
            <div className="steps-timeline">
              {workflow.steps?.map((step, idx) => (
                <div key={step.id || idx} className="step-card">
                  <div className="step-badge">{idx + 1}</div>
                  <div className="step-info">
                    <div className="step-title-row">
                      <strong>{step.name || step.id}</strong>
                      <span className="tool-tag">{step.tool}</span>
                      {step.requires_approval && (
                        <span className="badge badge-warning">Requires Approval</span>
                      )}
                    </div>
                    {step.condition && (
                      <div className="step-condition">
                        <small>Condition: <code>{step.condition}</code></small>
                      </div>
                    )}
                    {step.inputs && Object.keys(step.inputs).length > 0 && (
                      <div className="step-inputs">
                        <small>Inputs:</small>
                        <pre>{JSON.stringify(step.inputs, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="detail-section">
            <div className="section-header-row">
              <h3>Execution History</h3>
              <button className="btn btn-sm btn-secondary" onClick={loadHistory}>
                ↻ Refresh
              </button>
            </div>

            {loadingHistory ? (
              <p>Loading runs...</p>
            ) : executions.length === 0 ? (
              <p className="text-muted">No runs recorded yet.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Execution ID</th>
                    <th>Trigger</th>
                    <th>Status</th>
                    <th>Started</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {executions.map((ex) => (
                    <tr key={ex.id}>
                      <td><code>{ex.id}</code></td>
                      <td>{ex.trigger_type}</td>
                      <td><span className={`badge status-${ex.status}`}>{ex.status}</span></td>
                      <td>{new Date(ex.started_at).toLocaleString()}</td>
                      <td>
                        <button
                          className="btn btn-xs btn-outline"
                          onClick={() => setSelectedExec(ex)}
                        >
                          View Logs
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {selectedExec && (
            <div className="detail-section exec-log-box">
              <div className="section-header-row">
                <h4>Execution Logs: <code>{selectedExec.id}</code></h4>
                <button
                  className="btn btn-xs btn-outline"
                  onClick={() => setSelectedExec(null)}
                >
                  Close Logs
                </button>
              </div>
              <pre>{JSON.stringify(selectedExec.step_results, null, 2)}</pre>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button
            className="btn btn-success"
            onClick={() => onRun(workflow.id)}
            disabled={runningWfId === workflow.id}
          >
            {runningWfId === workflow.id ? 'Running...' : '▶ Run Now'}
          </button>
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
