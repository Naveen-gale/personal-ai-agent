import { useEffect, useRef, useState } from 'react';
import DrivePanel from './DrivePanel';
import { apiErrorMessage, apiFetch } from '../api';

export default function ChatTab() {
  const [messages, setMessages] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [confirmations, setConfirmations] = useState([]);
  const [attachments, setAttachments] = useState([]);
  const [showDrivePanel, setShowDrivePanel] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    let cancelled = false;
    async function loadConversation() {
      try {
        const [conversationResponse, approvalsResponse] = await Promise.all([
          apiFetch('/api/v1/conversations?limit=1'),
          apiFetch('/api/v1/approvals'),
        ]);
        const conversationData = await conversationResponse.json();
        const approvalData = await approvalsResponse.json();
        if (!conversationResponse.ok) throw new Error(apiErrorMessage(conversationData));
        if (!approvalsResponse.ok) throw new Error(apiErrorMessage(approvalData));
        const conversation = conversationData.conversations?.[0];
        if (conversation) {
          const messagesResponse = await apiFetch(
            `/api/v1/conversations/${conversation.id}/messages?limit=200`,
          );
          const messagesData = await messagesResponse.json();
          if (!messagesResponse.ok) throw new Error(apiErrorMessage(messagesData));
          if (!cancelled) {
            setConversationId(conversation.id);
            setMessages(messagesData.messages || []);
          }
        }
        if (!cancelled) setConfirmations(approvalData.approvals || []);
      } catch (loadError) {
        if (!cancelled) {
          setMessages([{ role: 'assistant', content: `Could not load saved chat: ${loadError.message}` }]);
        }
      } finally {
        if (!cancelled) setInitialLoading(false);
      }
    }
    loadConversation();
    return () => { cancelled = true; };
  }, []);

  async function handleSend(textToSend) {
    const text = textToSend || input.trim() || (attachments.length ? 'Please analyze the attached files.' : '');
    if (!text || loading) return;

    const userMsg = { role: 'user', content: text, attachments };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInput('');
    setLoading(true);

    try {
      const res = await apiFetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          message: text,
          idempotency_key: crypto.randomUUID(),
          attachments: attachments.map(({ name, text: content }) => ({ name, text: content || '' })),
        }),
      });

      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(apiErrorMessage(data, 'Failed to get response.'));
      if (data.reply) {
        setConversationId(data.conversation_id);
        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: data.reply,
          created_at: new Date().toISOString(),
        }]);
        setConfirmations((previous) => [
          ...previous.filter((item) => !(data.confirmations || []).some(
            (next) => next.confirmation_id === item.confirmation_id,
          )),
          ...(data.confirmations || []),
        ]);
        setAttachments([]);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Connection error: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function respondToConfirmation(confirmationId, decision) {
    setLoading(true);
    try {
      const res = await apiFetch('/api/v1/chat/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation_id: confirmationId, decision }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(apiErrorMessage(data, 'Confirmation failed.'));
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }]);
      setConfirmations((previous) => previous.filter((item) => item.confirmation_id !== confirmationId));
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'assistant', content: `Action failed: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  function addAttachmentContent(items) {
    setAttachments((previous) => [
      ...previous,
      ...items.filter((item) => !previous.some(
        (existing) => existing.name === item.name && existing.web_view_link === item.web_view_link,
      )),
    ]);
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {initialLoading ? (
          <div className="chat-empty">Loading saved conversation…</div>
        ) : messages.length === 0 ? (
          <div className="chat-empty">
            Hello! I am your Personal AI Agent. I can help with your email, calendar, tasks, contacts, Drive, and workflows.
          </div>
        ) : null}
        {messages.map((m, idx) => (
          <div key={idx} className={`chat-bubble-row ${m.role}`}>
            <div className={`chat-bubble ${m.role}`}>
              <div className="bubble-header">
                <strong>{m.role === 'user' ? 'You' : '⚡ AI Agent'}</strong>
              </div>
              <div className="bubble-content">
                <pre>{m.content}</pre>
                {m.attachments?.length > 0 && (
                  <div className="chat-attachment-summary">
                    {m.attachments.map((attachment) => (
                      <span key={`${attachment.name}-${attachment.web_view_link || ''}`}>
                        📎 {attachment.name}{attachment.truncated ? ' (text excerpt)' : ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="chat-bubble-row assistant">
            <div className="chat-bubble assistant typing">
              <span>Thinking & reasoning...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {confirmations.map((confirmation) => (
        <div className="quick-confirm-bar" key={confirmation.confirmation_id}>
          <span>{confirmation.preview}</span>
          <button
            className="btn btn-sm btn-success"
            onClick={() => respondToConfirmation(confirmation.confirmation_id, 'yes')}
            disabled={loading || initialLoading}
          >
            ✓ Confirm
          </button>
          <button
            className="btn btn-sm btn-outline"
            onClick={() => respondToConfirmation(confirmation.confirmation_id, 'no')}
            disabled={loading}
          >
            ✕ Cancel
          </button>
        </div>
      ))}

      {attachments.length > 0 && (
        <div className="chat-pending-attachments">
          {attachments.map((attachment, index) => (
            <span key={`${attachment.name}-${attachment.web_view_link || index}`}>
              📎 {attachment.name}
              <button
                aria-label={`Remove ${attachment.name}`}
                onClick={() => setAttachments((previous) => previous.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="chat-drive-toggle">
        <button
          className="btn btn-secondary"
          onClick={() => setShowDrivePanel((visible) => !visible)}
        >
          {showDrivePanel ? 'Hide Drive & Photos' : 'Google Drive & Photos'}
        </button>
      </div>
      {showDrivePanel && <DrivePanel onAttachContent={addAttachmentContent} />}

      <div className="chat-input-bar">
        <textarea
          rows="2"
          className="form-control"
          placeholder="Ask a question, analyze attached files, or describe a workflow..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          className="btn btn-primary"
          onClick={() => handleSend()}
          disabled={loading || initialLoading || (!input.trim() && !attachments.length)}
        >
          Send
        </button>
      </div>
    </div>
  );
}
