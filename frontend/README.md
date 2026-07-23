# MegaCMS AI Frontend

A simple React and Vite skeleton for the MegaCMS AI chatbot.

## Run locally

```bash
npm install
npm run dev
```

Open the local URL printed by Vite.

## Main files

- `src/App.jsx` holds the chat state and message logic.
- `src/components/Sidebar.jsx` contains the sidebar and recent chats.
- `src/components/ChatMessage.jsx` renders each message.
- `src/components/ChatInput.jsx` handles typing and sending.
- `src/App.css` contains the page and component styles.
- `src/index.css` contains the basic global styles.

## Connect the backend later

Replace the placeholder response inside `sendMessage` in `src/App.jsx` with a
request to the backend API.

## Useful commands

```bash
npm run dev
npm run build
npm run lint
```
