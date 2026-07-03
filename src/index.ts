/**
 * Personal AI Assistant - Main Entry Point
 *
 * Cloud-hosted JARVIS-style AI assistant with voice interaction,
 * RAG-grounded knowledge retrieval, and real-time data fetching.
 *
 * This module bootstraps the application by creating all services,
 * wiring them together, and starting the Express HTTP server.
 */

import { createApp } from './app.js';

const PORT = process.env['PORT'] ?? 3000;

const app = createApp();

app.listen(PORT, () => {
  console.log(`Personal AI Assistant running on port ${PORT}`);
});

export { app };
