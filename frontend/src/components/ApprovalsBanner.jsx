import { useState } from 'react';
import { apiFetch } from '../api';

export default function ApprovalsBanner({ approvals, onResolve }) {
  const [resolvingId, setResolvingId] = useState(null);

  if (!approvals || approvals.length === 0) {
    return (
      <div className="approvals-empty">
        <p>No actions are currently pending user approval.</p>
      </div>
    );
  }

  async function handleDecision(approval, decision) {
    setResolvingId(approval.id);
    try {
      const res = await apiFetch(`/api/executions/${approval.execution_id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      });
      const data = await res.json();
      if (data.success) {
        onResolve(approval.id);
      } else {
        alert(data.detail || 'Failed to process decision');
      }
    } catch (err) {
      alert('Error: ' + err.message);
    } finally {
      setResolvingId(null);
    }
  }

  return (
    <div className="approvals-section">
      <div className="alert alert-warning-box">
        <h3>🛡️ Human-in-the-Loop Actions Awaiting Approval ({approvals.length})</h3>
        <p>
          The agent has paused workflow execution before performing sensitive or external actions.
          Review the parameters below and decide whether to proceed.
        </p>
      </div>

      <div className="approval-cards-list">
        {approvals.map((appr) => (
          <div key={appr.id} className="approval-card">
            <div className="approval-card-header">
              <div>
                <h4>Step: <code>{appr.step_id}</code></h4>
                <span className="text-muted">Workflow ID: {appr.workflow_id}</span>
              </div>
              <span className="badge badge-warning">Awaiting Approval</span>
            </div>

            <div className="approval-details">
              <div><strong>Action / Tool:</strong> <code>{appr.tool_name}</code></div>
              <div className="approval-preview-box">
                <pre>{typeof appr.preview === 'string' ? appr.preview : JSON.stringify(appr.preview, null, 2)}</pre>
              </div>
            </div>

            <div className="approval-actions">
              <button
                className="btn btn-success"
                onClick={() => handleDecision(appr, 'approved')}
                disabled={resolvingId === appr.id}
              >
                {resolvingId === appr.id ? 'Processing...' : '✅ Approve & Execute'}
              </button>
              <button
                className="btn btn-danger-outline"
                onClick={() => handleDecision(appr, 'rejected')}
                disabled={resolvingId === appr.id}
              >
                ❌ Reject & Cancel
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
