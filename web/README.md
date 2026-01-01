# Transactoid ChatKit Demo

A minimal web frontend for Transactoid using OpenAI's ChatKit.

## Prerequisites

1. Start the ChatKit backend server:
   ```bash
   cd ..
   uv run python -m transactoid.ui.chatkit.server
   ```
   This runs the server on http://localhost:8000

## Running the Frontend

```bash
# Install dependencies
npm install

# Start dev server
npm run dev
```

Open http://localhost:3000 in your browser.

## Architecture

- **Backend**: FastAPI server at port 8000 (`/chatkit` endpoint)
- **Frontend**: Next.js app at port 3000 using `@openai/chatkit-react`

The frontend connects to the local ChatKit server to process messages through the Transactoid agent.
