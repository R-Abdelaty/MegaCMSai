function ChatMessage({ message }) {
  const isUser = message.role === 'user'

  return (
    <article className={`message ${message.role}`}>
      <div className="message-avatar" aria-hidden="true">
        {isUser ? 'You' : 'AI'}
      </div>

      <div className="message-content">
        <p>{message.content}</p>
      </div>
    </article>
  )
}

export default ChatMessage
