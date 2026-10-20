import { useState } from 'react';
import { apiFetch } from '../api';

const COMMON_TEMPLATES = [
  {
    name: 'Morning Executive Briefing',
    desc: 'Unread emails summary + today calendar events + pending tasks synthesized into a morning briefing.',
    trigger_type: 'scheduled',
    trigger_config: { recurrence: 'daily', time: '08:00', timezone: 'Asia/Kolkata' },
    steps: [
      { id: 'step_1', name: 'Get unread emails', tool: 'get_unread_emails', inputs: { max_results: 5 } },
      { id: 'step_2', name: 'Get today events', tool: 'get_today_events', inputs: { time_zone: 'Asia/Kolkata' } },
      { id: 'step_3', name: 'Get pending tasks', tool: 'list_pending_tasks', inputs: { max_results: 10 } },
      {
        id: 'step_4',
        name: 'Synthesize Briefing',
        tool: 'llm_synthesize',
        inputs: {
          prompt: 'Synthesize a morning briefing highlighting urgent emails, schedule, and pending tasks.',
          context_data: '{{all_outputs}}',
        },
      },
    ],
  },
  {
    name: 'Evening Task & Schedule Planner',
    desc: 'Review unfinished tasks and tomorrow schedule to plan the next day.',
    trigger_type: 'scheduled',
    trigger_config: { recurrence: 'daily', time: '19:00', timezone: 'Asia/Kolkata' },
    steps: [
      { id: 'step_1', name: 'Get pending tasks', tool: 'list_pending_tasks', inputs: { max_results: 15 } },
      { id: 'step_2', name: 'Get tomorrow schedule', tool: 'list_calendar_events', inputs: { start_time: 'tomorrow', max_results: 5 } },
      {
        id: 'step_3',
        name: 'Plan Tomorrow',
        tool: 'llm_synthesize',
        inputs: {
          prompt: 'Recommend a prioritized to-do list and study schedule for tomorrow based on pending tasks and calendar.',
          context_data: '{{all_outputs}}',
        },
      },
    ],
  },
  {
    name: 'Weekly Task Review & Reminder',
    desc: 'Review open tasks and schedule a reminder for the upcoming week.',
    trigger_type: 'scheduled',
    trigger_config: { recurrence: 'weekly', time: '10:00', days_of_week: ['MONDAY'], timezone: 'Asia/Kolkata' },
    steps: [
      { id: 'step_1', name: 'Get pending tasks', tool: 'list_pending_tasks', inputs: { max_results: 20 } },
      {
        id: 'step_2',
        name: 'Create Weekly Reminder',
        tool: 'create_reminder',
        inputs: {
          reminder_text: 'Review weekly project goals and tasks',
          scheduled_time: 'tomorrow at 9 AM',
        },
      },
    ],
  },
];

export default function WorkflowCreateModal({ onClose, onCreated, availableTools }) {
  const [activeMode, setActiveMode] = useState('template'); // 'template' | 'custom' | 'nl'
  const [nlPrompt, setNlPrompt] = useState('');
  const [nlLoading, setNlLoading] = useState(false);
  const [nlError, setNlError] = useState('');

  // Form state
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [triggerType, setTriggerType] = useState('scheduled');
  const [recurrence, setRecurrence] = useState('daily');
  const [timeStr, setTimeStr] = useState('08:00');
  const [steps, setSteps] = useState([
    { id: 'step_1', name: 'Get unread emails', tool: 'get_unread_emails', inputs: { max_results: 5 } },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  function loadTemplate(tpl) {
    setName(tpl.name);
    setDescription(tpl.desc);
    setTriggerType(tpl.trigger_type);
    setRecurrence(tpl.trigger_config.recurrence || 'daily');
    setTimeStr(tpl.trigger_config.time || '08:00');
    setSteps(tpl.steps);
    setActiveMode('custom');
  }

  function addStep() {
    const nextIdx = steps.length + 1;
    setSteps([
      ...steps,
      {
        id: `step_${nextIdx}`,
        name: `Step ${nextIdx}`,
        tool: availableTools[0]?.name || 'get_unread_emails',
        inputs: {},
      },
    ]);
  }

  function removeStep(idx) {
    setSteps(steps.filter((_, i) => i !== idx));
  }

  function updateStep(idx, field, val) {
    const updated = [...steps];
    updated[idx] = { ...updated[idx], [field]: val };
    setSteps(updated);
  }

  async function handleNlGenerate() {
    if (!nlPrompt.trim()) return;
    setNlLoading(true);
    setNlError('');
    try {
      const res = await apiFetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `Create a workflow plan for: ${nlPrompt}`,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      const data = await res.json();
      if (data.reply) {
        // Switch to custom mode with the generated prompt as description
        setName(nlPrompt.slice(0, 40));
        setDescription(`Workflow created from prompt: ${nlPrompt}`);
        setActiveMode('custom');
      }
    } catch (err) {
      setNlError('Failed to generate from natural language: ' + err.message);
    } finally {
      setNlLoading(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    if (!name.trim()) {
      setError('Workflow name is required.');
      return;
    }
    if (steps.length === 0) {
      setError('Please add at least one step.');
      return;
    }

    setSaving(true);
    try {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        trigger_type: triggerType,
        trigger_config:
          triggerType === 'scheduled'
            ? { recurrence, time: timeStr, timezone: 'Asia/Kolkata' }
            : {},
        steps,
        status: 'active',
      };

      const res = await apiFetch('/api/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.detail || data.message || 'Failed to save workflow');
      }
      onCreated(data.workflow);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Create Automated Workflow</h2>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-tabs">
          <button
            className={`tab-btn ${activeMode === 'template' ? 'active' : ''}`}
            onClick={() => setActiveMode('template')}
          >
            📋 Quick Templates
          </button>
          <button
            className={`tab-btn ${activeMode === 'nl' ? 'active' : ''}`}
            onClick={() => setActiveMode('nl')}
          >
            ✨ Natural Language
          </button>
          <button
            className={`tab-btn ${activeMode === 'custom' ? 'active' : ''}`}
            onClick={() => setActiveMode('custom')}
          >
            🛠️ Workflow Builder
          </button>
        </div>

        <div className="modal-body">
          {error && <div className="alert alert-danger">{error}</div>}

          {activeMode === 'template' && (
            <div className="template-grid">
              {COMMON_TEMPLATES.map((tpl, i) => (
                <div key={i} className="template-card">
                  <h4>{tpl.name}</h4>
                  <p>{tpl.desc}</p>
                  <div className="template-steps-preview">
                    {tpl.steps.map((s, idx) => (
                      <span key={idx} className="badge badge-light">
                        {s.tool}
                      </span>
                    ))}
                  </div>
                  <button className="btn btn-sm btn-primary" onClick={() => loadTemplate(tpl)}>
                    Use This Template
                  </button>
                </div>
              ))}
            </div>
          )}

          {activeMode === 'nl' && (
            <div className="nl-creator-box">
              <p>Describe your workflow routine in plain English. For example:</p>
              <div className="sample-prompts">
                <span onClick={() => setNlPrompt('Every morning at 8 AM summarize unread emails and show calendar')}>
                  "Every morning at 8 AM summarize unread emails and show calendar"
                </span>
                <span onClick={() => setNlPrompt('Every evening review pending tasks and prepare tomorrow study plan')}>
                  "Every evening review pending tasks and prepare tomorrow study plan"
                </span>
              </div>
              <textarea
                className="form-control"
                rows="3"
                placeholder="Type your desired workflow routine..."
                value={nlPrompt}
                onChange={(e) => setNlPrompt(e.target.value)}
              />
              {nlError && <div className="alert alert-danger">{nlError}</div>}
              <button
                className="btn btn-primary"
                onClick={handleNlGenerate}
                disabled={nlLoading || !nlPrompt.trim()}
              >
                {nlLoading ? 'Analyzing...' : 'Generate Plan'}
              </button>
            </div>
          )}

          {activeMode === 'custom' && (
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>Workflow Name *</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="e.g. Morning Briefing"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label>Description</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="What this workflow accomplishes..."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>

              <div className="form-row">
                <div className="form-group col">
                  <label>Trigger Type</label>
                  <select
                    className="form-control"
                    value={triggerType}
                    onChange={(e) => setTriggerType(e.target.value)}
                  >
                    <option value="scheduled">⏰ Scheduled (Recurring)</option>
                    <option value="manual">⚡ Manual (On-demand)</option>
                  </select>
                </div>

                {triggerType === 'scheduled' && (
                  <>
                    <div className="form-group col">
                      <label>Recurrence</label>
                      <select
                        className="form-control"
                        value={recurrence}
                        onChange={(e) => setRecurrence(e.target.value)}
                      >
                        <option value="daily">Daily</option>
                        <option value="weekly">Weekly (Mondays)</option>
                        <option value="once">Once</option>
                      </select>
                    </div>

                    <div className="form-group col">
                      <label>Time (Asia/Kolkata)</label>
                      <input
                        type="time"
                        className="form-control"
                        value={timeStr}
                        onChange={(e) => setTimeStr(e.target.value)}
                      />
                    </div>
                  </>
                )}
              </div>

              <div className="steps-builder">
                <div className="section-header-row">
                  <h4>Workflow Steps ({steps.length})</h4>
                  <button type="button" className="btn btn-sm btn-outline" onClick={addStep}>
                    + Add Step
                  </button>
                </div>

                {steps.map((st, idx) => (
                  <div key={idx} className="step-builder-card">
                    <span className="step-num">{idx + 1}</span>
                    <input
                      type="text"
                      className="form-control step-name-input"
                      placeholder="Step Name"
                      value={st.name}
                      onChange={(e) => updateStep(idx, 'name', e.target.value)}
                    />
                    <select
                      className="form-control step-tool-select"
                      value={st.tool}
                      onChange={(e) => updateStep(idx, 'tool', e.target.value)}
                    >
                      {availableTools.map((t) => (
                        <option key={t.name} value={t.name}>
                          {t.name} ({t.category})
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="btn btn-xs btn-danger"
                      onClick={() => removeStep(idx)}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={onClose}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? 'Saving...' : 'Save & Activate Workflow'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
