import { useEffect, useState } from 'react';
import Navbar from './components/Navbar';
import WorkflowList from './components/WorkflowList';
import WorkflowDetailModal from './components/WorkflowDetailModal';
import WorkflowCreateModal from './components/WorkflowCreateModal';
import ApprovalsBanner from './components/ApprovalsBanner';
import ChatTab from './components/ChatTab';
import { apiErrorMessage, apiFetch } from './api';
import { GoogleSignInButton } from './auth';
import { useAuth } from './auth-context';
import './App.css';

export default function App() {
  const { user, signOut } = useAuth();
  const [activeTab, setActiveTab] = useState('workflows');
  const [workflows, setWorkflows] = useState([]);
  const [availableTools, setAvailableTools] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [apiHealthy, setApiHealthy] = useState(false);
  const [selectedWorkflow, setSelectedWorkflow] = useState(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [runningWfId, setRunningWfId] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return undefined;
    checkHealthAndLoad();
    const interval = setInterval(checkHealthAndLoad, 10000);
    return () => clearInterval(interval);
  }, [user]);

  async function checkHealthAndLoad() {
    try {
      const healthRes = await apiFetch('/api/health');
      if (healthRes.ok) {
        setApiHealthy(true);
      } else {
        setApiHealthy(false);
      }
    } catch {
      setApiHealthy(false);
    }

    loadWorkflows();
    loadApprovals();
    loadTools();
  }

  async function loadWorkflows() {
    try {
      const res = await apiFetch('/api/workflows');
      const data = await res.json();
      if (data.success) {
        setWorkflows(data.workflows || []);
      }
    } catch (err) {
      console.error('Failed to load workflows', err);
    } finally {
      setLoading(false);
    }
  }

  async function loadApprovals() {
    try {
      const res = await apiFetch('/api/approvals');
      const data = await res.json();
      if (data.success) {
        setApprovals(data.approvals || []);
      }
    } catch (err) {
      console.error('Failed to load approvals', err);
    }
  }

  async function loadTools() {
    try {
      const res = await apiFetch('/api/tools');
      const data = await res.json();
      if (data.success) {
        setAvailableTools(data.tools || []);
      }
    } catch (err) {
      console.error('Failed to load tools', err);
    }
  }

  async function handleRunWorkflow(id) {
    setRunningWfId(id);
    try {
      const res = await apiFetch(`/api/workflows/${id}/run`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        await loadWorkflows();
        await loadApprovals();
        if (selectedWorkflow && selectedWorkflow.id === id) {
          const updated = workflows.find((w) => w.id === id);
          if (updated) setSelectedWorkflow(updated);
        }
      } else {
        alert(apiErrorMessage(data, 'Execution failed'));
      }
    } catch (err) {
      alert('Error running workflow: ' + err.message);
    } finally {
      setRunningWfId(null);
    }
  }

  async function handleToggleStatus(wf) {
    const action = wf.status === 'active' ? 'pause' : 'resume';
    try {
      const res = await apiFetch(`/api/workflows/${wf.id}/${action}`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        loadWorkflows();
      }
    } catch (err) {
      alert(`Failed to ${action} workflow: ` + err.message);
    }
  }

  async function handleDeleteWorkflow(id) {
    if (!window.confirm('Are you sure you want to delete this workflow?')) return;
    try {
      const res = await apiFetch(`/api/workflows/${id}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        if (selectedWorkflow?.id === id) setSelectedWorkflow(null);
        loadWorkflows();
      }
    } catch (err) {
      alert('Failed to delete: ' + err.message);
    }
  }

  if (!user) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <div className="brand-logo">⚡</div>
          <h1>Personal AI Agent</h1>
          <p>Sign in with the authorized Google account to continue.</p>
          <GoogleSignInButton />
        </section>
      </main>
    );
  }

  return (
    <div className="app-layout">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        pendingCount={approvals.length}
        apiHealthy={apiHealthy}
      />
      <div className="signed-in-user">
        <span>{user.email}</span>
        <button className="btn btn-sm btn-secondary" onClick={signOut}>Sign out</button>
      </div>

      <main className="app-main">
        {approvals.length > 0 && activeTab !== 'approvals' && (
          <div className="approval-toast" onClick={() => setActiveTab('approvals')}>
            ⚠️ <strong>{approvals.length}</strong> action(s) require your confirmation!{' '}
            <span className="toast-link">Review Approvals →</span>
          </div>
        )}

        {activeTab === 'workflows' && (
          <section className="tab-pane">
            <div className="page-header">
              <h2>Workflow Automations</h2>
              <p className="page-subtitle">
                Combine your emails, calendar, tasks, and reminders into autonomous schedules and triggers.
              </p>
            </div>

            {loading ? (
              <p>Loading workflows...</p>
            ) : (
              <WorkflowList
                workflows={workflows}
                onRun={handleRunWorkflow}
                onToggleStatus={handleToggleStatus}
                onSelectWorkflow={setSelectedWorkflow}
                onDelete={handleDeleteWorkflow}
                onOpenCreate={() => setIsCreateOpen(true)}
                runningWfId={runningWfId}
              />
            )}
          </section>
        )}

        {activeTab === 'chat' && (
          <section className="tab-pane">
            <ChatTab />
          </section>
        )}

        {activeTab === 'approvals' && (
          <section className="tab-pane">
            <ApprovalsBanner
              approvals={approvals}
              onResolve={() => {
                loadApprovals();
                loadWorkflows();
              }}
            />
          </section>
        )}
      </main>

      {selectedWorkflow && (
        <WorkflowDetailModal
          workflow={selectedWorkflow}
          onClose={() => setSelectedWorkflow(null)}
          onRun={handleRunWorkflow}
          runningWfId={runningWfId}
        />
      )}

      {isCreateOpen && (
        <WorkflowCreateModal
          onClose={() => setIsCreateOpen(false)}
          onCreated={() => {
            loadWorkflows();
            setIsCreateOpen(false);
          }}
          availableTools={availableTools}
        />
      )}
    </div>
  );
}
