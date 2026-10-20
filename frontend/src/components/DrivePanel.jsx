import { Fragment, useEffect, useRef, useState } from 'react';
import { apiErrorMessage, apiFetch, apiUrl, getAccessToken } from '../api';

async function requestJson(url, options = {}) {
  const response = await apiFetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    throw new Error(apiErrorMessage(data));
  }
  return data;
}

function parsePollInterval(value) {
  const match = /^(\d+(?:\.\d+)?)s$/.exec(value || '');
  return match ? Math.max(1000, Number(match[1]) * 1000) : 3000;
}

export default function DrivePanel({ onAttachContent }) {
  const [files, setFiles] = useState([]);
  const [folderStack, setFolderStack] = useState([]);
  const [query, setQuery] = useState('');
  const [mimeType, setMimeType] = useState('');
  const [pageTokens, setPageTokens] = useState([null]);
  const [nextPageToken, setNextPageToken] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [pickerSession, setPickerSession] = useState(null);
  const [photoItems, setPhotoItems] = useState([]);
  const [selectedPhotoIds, setSelectedPhotoIds] = useState([]);
  const [photoNextToken, setPhotoNextToken] = useState(null);
  const [uploadProgress, setUploadProgress] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const pickerPopup = useRef(null);

  const currentFolder = folderStack.at(-1);
  const currentFolderId = currentFolder?.id || '';

  async function loadFiles(token = null, folderId = currentFolderId) {
    setBusy(true);
    setError('');
    try {
      const params = new URLSearchParams({ page_size: '50' });
      if (folderId) params.set('folder_id', folderId);
      if (query.trim()) params.set('q', query.trim());
      if (mimeType) params.set('mime_type', mimeType);
      if (token) params.set('page_token', token);
      const data = await requestJson(`/api/drive/files?${params}`);
      setFiles(data.files || []);
      setNextPageToken(data.next_page_token || null);
      setSelectedIds([]);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    // Loading remote folder contents is the synchronization side effect for navigation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadFiles(null, currentFolderId);
    // The folder stack changes only when the user navigates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentFolderId]);

  useEffect(() => {
    if (!pickerSession) return undefined;
    let timer;
    let cancelled = false;

    async function pollPicker() {
      try {
        const data = await requestJson(`/api/photos/sessions/${pickerSession.id}`);
        if (data.session.media_items_set) {
          await loadPhotoItems(pickerSession.id);
          setNotice('Google Photos selection is ready.');
          return;
        }
        if (pickerPopup.current?.closed) {
          setError('The Google Photos Picker was closed before a selection was completed.');
          setPickerSession(null);
          return;
        }
        if (data.session.expire_time && Date.parse(data.session.expire_time) <= Date.now()) {
          setError('The Google Photos Picker session expired. Start a new selection.');
          setPickerSession(null);
          return;
        }
        timer = window.setTimeout(
          pollPicker,
          parsePollInterval(pickerSession.pollInterval),
        );
      } catch (pollError) {
        if (!cancelled) {
          setError(pollError.message);
          setPickerSession(null);
        }
      }
    }

    timer = window.setTimeout(pollPicker, parsePollInterval(pickerSession.pollInterval));
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      apiFetch(`/api/photos/sessions/${pickerSession.id}`, { method: 'DELETE' }).catch(() => {});
    };
  }, [pickerSession]);

  async function loadPhotoItems(sessionId, pageToken = null, append = false) {
    const params = new URLSearchParams({ page_size: '50' });
    if (pageToken) params.set('page_token', pageToken);
    const data = await requestJson(
      `/api/photos/sessions/${sessionId}/items?${params}`,
    );
    setPhotoItems((previous) =>
      append ? [...previous, ...(data.media_items || [])] : data.media_items || [],
    );
    setPhotoNextToken(data.next_page_token || null);
    setSelectedPhotoIds([]);
  }

  function setSelection(id, checked) {
    setSelectedIds((previous) =>
      checked ? [...new Set([...previous, id])] : previous.filter((item) => item !== id),
    );
  }

  function setPhotoSelection(id, checked) {
    setSelectedPhotoIds((previous) =>
      checked ? [...new Set([...previous, id])] : previous.filter((item) => item !== id),
    );
  }

  function openFolder(folder) {
    setFolderStack((previous) => [...previous, { id: folder.id, name: folder.name }]);
    setPageTokens([null]);
    setSelectedIds([]);
  }

  async function createFolder() {
    const name = window.prompt('Name for the new Google Drive folder:');
    if (name === null) return;
    setError('');
    try {
      await requestJson('/api/drive/folders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, parent_id: currentFolderId || null }),
      });
      setNotice(`Created folder “${name}”.`);
      await loadFiles();
    } catch (createError) {
      setError(createError.message);
    }
  }

  async function resolveDestination() {
    const path = window.prompt('Destination folder path (leave blank for My Drive root):');
    if (path === null) return null;
    if (!path.trim()) return 'root';
    const params = new URLSearchParams({ path: path.trim() });
    const result = await requestJson(`/api/drive/folders/resolve?${params}`);
    return result.folder.id;
  }

  async function renameSelected() {
    if (selectedIds.length !== 1) return;
    const file = files.find((item) => item.id === selectedIds[0]);
    const name = window.prompt('New name:', file?.name || '');
    if (!name || !window.confirm(`Rename “${file?.name}” to “${name}”?`)) return;
    try {
      await requestJson(`/api/drive/files/${encodeURIComponent(file.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, confirmed: true }),
      });
      setNotice('Drive item renamed.');
      await loadFiles();
    } catch (actionError) {
      setError(actionError.message);
    }
  }

  async function moveSelected() {
    if (selectedIds.length !== 1) return;
    const file = files.find((item) => item.id === selectedIds[0]);
    try {
      const destinationId = await resolveDestination();
      if (!destinationId) return;
      if (!window.confirm(`Move “${file?.name}” to the selected destination?`)) return;
      await requestJson(`/api/drive/files/${encodeURIComponent(file.id)}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ destination_folder_id: destinationId, confirmed: true }),
      });
      setNotice('Drive item moved.');
      await loadFiles();
    } catch (actionError) {
      setError(actionError.message);
    }
  }

  async function copySelected() {
    if (selectedIds.length !== 1) return;
    const file = files.find((item) => item.id === selectedIds[0]);
    try {
      const destinationId = await resolveDestination();
      if (!destinationId) return;
      const name = window.prompt('Copy name (leave blank to keep the original name):', '');
      if (name === null) return;
      const result = await requestJson(`/api/drive/files/${encodeURIComponent(file.id)}/copy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() || null, parent_id: destinationId }),
      });
      setNotice(`Created copy: ${result.item.name}`);
      await loadFiles();
    } catch (actionError) {
      setError(actionError.message);
    }
  }

  async function trashSelected() {
    const selected = files.filter((file) => selectedIds.includes(file.id));
    if (!selected.length || !window.confirm(`Move ${selected.length} item(s) to Drive trash?`)) return;
    setError('');
    try {
      for (const file of selected) {
        await requestJson(`/api/drive/files/${encodeURIComponent(file.id)}`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirmed: true }),
        });
      }
      setNotice(`Moved ${selected.length} item(s) to Drive trash.`);
      await loadFiles();
    } catch (actionError) {
      setError(actionError.message);
    }
  }

  async function importSelectedToChat() {
    const selected = files.filter((file) => selectedIds.includes(file.id));
    if (!selected.length) return;
    setError('');
    setBusy(true);
    const imported = [];
    const failures = [];
    for (const file of selected) {
      try {
        const data = await requestJson(
          `/api/drive/files/${encodeURIComponent(file.id)}/content`,
        );
        imported.push({
          name: data.name,
          text: data.text,
          mime_type: data.mime_type,
          web_view_link: data.web_view_link,
          truncated: data.truncated,
        });
      } catch (importError) {
        failures.push(`${file.name}: ${importError.message}`);
      }
    }
    if (imported.length) {
      onAttachContent(imported);
      setNotice(`Imported ${imported.length} file(s) into this chat.`);
    }
    if (failures.length) setError(failures.join('\n'));
    setBusy(false);
  }

  function uploadWithProgress(file, operationId) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append('file', file, file.name);
      if (currentFolderId) form.append('parent_id', currentFolderId);
      form.append('operation_id', operationId);
      const request = new XMLHttpRequest();
      request.open('POST', apiUrl('/api/drive/upload'));
      const accessToken = getAccessToken();
      if (accessToken) request.setRequestHeader('Authorization', `Bearer ${accessToken}`);
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          setUploadProgress((previous) => ({
            ...previous,
            [file.name]: Math.round((event.loaded / event.total) * 100),
          }));
        }
      };
      request.onload = () => {
        try {
          const data = JSON.parse(request.responseText || '{}');
          if (request.status >= 200 && request.status < 300 && data.success) resolve(data.file);
          else reject(new Error(data.detail || 'Upload failed.'));
        } catch (parseError) {
          reject(new Error(`Could not read the upload response: ${parseError.message}`));
        }
      };
      request.onerror = () => reject(new Error(`Network error uploading ${file.name}.`));
      request.send(form);
    });
  }

  async function uploadFiles(fileList) {
    const selected = [...fileList];
    if (!selected.length) return;
    setError('');
    setUploadProgress({});
    setBusy(true);
    const failures = [];
    for (const file of selected) {
      try {
        const operationId = window.crypto?.randomUUID
          ? window.crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const result = await uploadWithProgress(file, operationId);
        setNotice(`Uploaded “${result.name}” to Google Drive.`);
      } catch (uploadError) {
        failures.push(`${file.name}: ${uploadError.message}`);
      }
    }
    if (failures.length) setError(failures.join('\n'));
    await loadFiles();
    setBusy(false);
  }

  async function downloadFile(file) {
    setError('');
    try {
      const response = await apiFetch(`/api/drive/files/${encodeURIComponent(file.id)}/download`);
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(apiErrorMessage(data, 'Download failed.'));
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.download = file.name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
    } catch (downloadError) {
      setError(downloadError.message);
    }
  }

  async function startPhotosPicker() {
    const popup = window.open('about:blank', '_blank');
    if (!popup) {
      setError('Allow pop-ups to open Google Photos Picker.');
      return;
    }
    pickerPopup.current = popup;
    setPhotoItems([]);
    setSelectedPhotoIds([]);
    setError('');
    try {
      const data = await requestJson('/api/photos/sessions', { method: 'POST' });
      popup.location.href = data.session.picker_uri;
      setPickerSession({
        id: data.session.id,
        pollInterval: data.session.poll_interval,
      });
      setNotice('Select photos in the Google Photos tab. This panel will update when ready.');
    } catch (pickerError) {
      popup.close();
      setError(pickerError.message);
    }
  }

  async function saveSelectedPhotos() {
    if (!pickerSession || !selectedPhotoIds.length) return;
    setBusy(true);
    setError('');
    try {
      const data = await requestJson(
        `/api/photos/sessions/${pickerSession.id}/save-to-drive`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            media_item_ids: selectedPhotoIds,
            parent_id: currentFolderId || null,
          }),
        },
      );
      setNotice(`Saved ${data.files.length} selected media item(s) to Google Drive.`);
      setPickerSession(null);
      pickerPopup.current?.close();
      await loadFiles();
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setBusy(false);
    }
  }

  const selectedCount = selectedIds.length;
  const pageIndex = pageTokens.length - 1;

  return (
    <section className="drive-panel">
      <div className="drive-panel-header">
        <div>
          <h3>Google Drive & Photos</h3>
          <p>Browse, import, upload, and organize files in your connected Google account.</p>
        </div>
        <div className="drive-panel-actions">
          <button className="btn btn-secondary" onClick={createFolder} disabled={busy}>
            New folder
          </button>
          <button className="btn btn-secondary" onClick={startPhotosPicker} disabled={busy}>
            Choose from Photos
          </button>
          <label className="btn btn-secondary drive-upload-label">
            Upload to Drive
            <input
              type="file"
              multiple
              onChange={(event) => {
                uploadFiles(event.target.files);
                event.target.value = '';
              }}
              disabled={busy}
            />
          </label>
        </div>
      </div>

      <div className="drive-breadcrumbs">
        <button
          className="drive-breadcrumb"
          onClick={() => {
            setFolderStack([]);
            setPageTokens([null]);
          }}
        >
          My Drive
        </button>
        {folderStack.map((folder, index) => (
          <Fragment key={folder.id}>
            <span>/</span>
            <button
              className="drive-breadcrumb"
              onClick={() => {
                setFolderStack((previous) => previous.slice(0, index + 1));
                setPageTokens([null]);
              }}
            >
              {folder.name}
            </button>
          </Fragment>
        ))}
      </div>

      <div className="drive-search-row">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search file names across Drive"
          aria-label="Search Drive"
        />
        <select
          value={mimeType}
          onChange={(event) => setMimeType(event.target.value)}
          aria-label="Filter by file type"
        >
          <option value="">All file types</option>
          <option value="application/pdf">PDF</option>
          <option value="image/">Images (MIME filter)</option>
          <option value="text/plain">Text</option>
          <option value="application/vnd.google-apps.folder">Folders</option>
        </select>
        <button
          className="btn btn-secondary"
          onClick={() => {
            setPageTokens([null]);
            loadFiles();
          }}
          disabled={busy}
        >
          Search
        </button>
      </div>

      <div className="drive-action-row">
        <button onClick={importSelectedToChat} disabled={!selectedCount || busy}>
          Add selected to chat
        </button>
        <button onClick={renameSelected} disabled={selectedCount !== 1 || busy}>
          Rename
        </button>
        <button onClick={moveSelected} disabled={selectedCount !== 1 || busy}>
          Move
        </button>
        <button onClick={copySelected} disabled={selectedCount !== 1 || busy}>
          Copy
        </button>
        <button onClick={trashSelected} disabled={!selectedCount || busy}>
          Move to trash
        </button>
      </div>

      {error && <div className="drive-message error">{error}</div>}
      {notice && <div className="drive-message success">{notice}</div>}
      {Object.entries(uploadProgress).map(([name, progress]) => (
        <div className="drive-upload-progress" key={name}>
          <span>{name}</span>
          <progress value={progress} max="100" />
          <span>{progress}%</span>
        </div>
      ))}

      <div className="drive-file-list">
        {files.map((file) => {
          const isFolder = file.mimeType === 'application/vnd.google-apps.folder';
          return (
            <div className="drive-file-row" key={file.id}>
              <input
                type="checkbox"
                checked={selectedIds.includes(file.id)}
                onChange={(event) => setSelection(file.id, event.target.checked)}
                aria-label={`Select ${file.name}`}
              />
              <span className="drive-file-icon">{isFolder ? '📁' : '📄'}</span>
              {isFolder ? (
                <button className="drive-file-name" onClick={() => openFolder(file)}>
                  {file.name}
                </button>
              ) : (
                <span className="drive-file-name">
                  {file.thumbnailLink && (
                    <img
                      className="drive-file-thumb"
                      src={file.thumbnailLink}
                      alt=""
                      referrerPolicy="no-referrer"
                    />
                  )}
                  {file.name}
                </span>
              )}
              <span className="drive-file-meta">{file.mimeType}</span>
              <span className="drive-file-meta">
                {file.size ? `${Math.ceil(Number(file.size) / 1024)} KB` : ''}
              </span>
              <span className="drive-file-meta">
                {file.modifiedTime ? new Date(file.modifiedTime).toLocaleDateString() : ''}
              </span>
              {file.webViewLink && (
                <a href={file.webViewLink} target="_blank" rel="noreferrer">
                  Open
                </a>
              )}
              {!isFolder && (
                <button className="drive-download" onClick={() => downloadFile(file)}>
                  Download
                </button>
              )}
            </div>
          );
        })}
        {!files.length && <p className="drive-empty">{busy ? 'Loading Drive…' : 'No files found.'}</p>}
      </div>

      <div className="drive-pagination">
        <button
          disabled={pageIndex === 0 || busy}
          onClick={() => {
            const previous = pageTokens.slice(0, -1);
            setPageTokens(previous);
            loadFiles(previous.at(-1) || null);
          }}
        >
          Previous
        </button>
        <button
          disabled={!nextPageToken || busy}
          onClick={() => {
            setPageTokens((previous) => [...previous, nextPageToken]);
            loadFiles(nextPageToken);
          }}
        >
          Next
        </button>
      </div>

      {pickerSession && (
        <div className="drive-photos-selection">
          <div className="drive-photos-heading">
            <strong>Selected Google Photos media</strong>
            <button
              onClick={() => {
                setPickerSession(null);
                pickerPopup.current?.close();
                setPhotoItems([]);
              }}
            >
              Cancel
            </button>
          </div>
          <div className="drive-photo-grid">
            {photoItems.map((item) => (
              <label key={item.id} className="drive-photo-card">
                <input
                  type="checkbox"
                  checked={selectedPhotoIds.includes(item.id)}
                  onChange={(event) => setPhotoSelection(item.id, event.target.checked)}
                />
                <span>{item.video ? '🎬' : '🖼️'}</span>
                <span>{item.filename}</span>
                <small>{item.mime_type}</small>
              </label>
            ))}
          </div>
          {photoNextToken && (
            <button
              className="btn btn-secondary"
              onClick={() => loadPhotoItems(pickerSession.id, photoNextToken, true)}
            >
              Load more
            </button>
          )}
          <button
            className="btn btn-primary"
            onClick={saveSelectedPhotos}
            disabled={!selectedPhotoIds.length || busy}
          >
            Save selected media to Drive
          </button>
        </div>
      )}
    </section>
  );
}
