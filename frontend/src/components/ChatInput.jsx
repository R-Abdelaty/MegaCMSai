import { useState } from 'react'

function ChatInput({ onSend }) {
  const [message, setMessage] = useState('')

  function submitMessage(event) {
    event.preventDefault()

    const cleanMessage = message.trim()
    if (!cleanMessage) return

    onSend(cleanMessage)
    setMessage('')
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form.requestSubmit()
    }
  }

  return (
    <div className="chat-input-area">
      <form className="chat-form" onSubmit={submitMessage}>
        <textarea
          aria-label="Chat message"
          placeholder="Type your message..."
          rows="1"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          className="send-button"
          type="submit"
          disabled={!message.trim()}
        >
          Send
        </button>
      </form>
      <p className="input-help">Enter to send · Shift + Enter for a new line</p>
    </div>
  )
}

export default ChatInput
