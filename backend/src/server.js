import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 5000;
const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://127.0.0.1:8000';

app.use(cors());
app.use(express.json({ limit: '2mb' }));

// Health check
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    service: 'backend-gateway',
    python_api: PYTHON_API_URL,
    timestamp: new Date().toISOString()
  });
});

// Proxy /api/* requests to Python FastAPI Agent backend
app.use('/api', async (req, res) => {
  const targetUrl = `${PYTHON_API_URL}${req.originalUrl}`;
  try {
    const fetchOptions = {
      method: req.method,
      headers: {}
    };

    if (req.headers['content-type']) {
      fetchOptions.headers['Content-Type'] = req.headers['content-type'];
    }
    if (req.headers.authorization) {
      fetchOptions.headers.Authorization = req.headers.authorization;
    }

    if (req.is('multipart/form-data')) {
      fetchOptions.body = req;
      fetchOptions.duplex = 'half';
    } else if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method) && req.body) {
      fetchOptions.body = JSON.stringify(req.body);
      fetchOptions.headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(targetUrl, fetchOptions);
    const contentType = response.headers.get('content-type') || '';
    res.status(response.status);
    if (contentType.includes('application/json')) {
      const data = await response.json().catch(() => ({}));
      res.json(data);
    } else {
      const disposition = response.headers.get('content-disposition');
      if (contentType) res.set('Content-Type', contentType);
      if (disposition) res.set('Content-Disposition', disposition);
      res.send(Buffer.from(await response.arrayBuffer()));
    }
  } catch (error) {
    res.status(502).json({
      success: false,
      error: `Could not connect to Python Agent API at ${PYTHON_API_URL}. Ensure 'python -m agent.api' is running.`,
      details: error.message
    });
  }
});

app.listen(PORT, () => {
  console.log(`Backend Express Gateway running on port ${PORT}`);
  console.log(`Proxying /api requests to Python API: ${PYTHON_API_URL}`);
});
