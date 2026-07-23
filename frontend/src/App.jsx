import { useState } from 'react'
import ChatInput from './components/ChatInput'
import ChatMessage from './components/ChatMessage'
import Sidebar from './components/Sidebar'
import './App.css'

const welcomeMessage = {
  id: 1,
  role: 'assistant',
  content: 'Hello! How can I help you today?',
}

function App() {
  const [messages, setMessages] = useState([welcomeMessage])

  function startNewChat() {
    setMessages([welcomeMessage])
  }

  function sendMessage(messageText) {
    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: messageText,
    }

    const placeholderReply = {
      id: Date.now() + 1,
      role: 'assistant',
      content:
        'Your message was received. Connect this function to the backend when the API is ready.',
    }

    setMessages((currentMessages) => [
      ...currentMessages,
      userMessage,
      placeholderReply,
    ])
  }

  return (
    <div className="app-layout">
      <Sidebar onNewChat={startNewChat} />

      <main className="chat-page">
        <header className="chat-header">
          <div>
            <h1>MegaCMS AI</h1>
            <p>Chat assistant</p>
          </div>
          <span className="status">Online</span>
        </header>

        <section className="message-list" aria-live="polite">
          <div className="message-list-inner">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}
          </div>
        </section>

        <ChatInput onSend={sendMessage} />
      </main>
    </div>
  )
}

export default App
