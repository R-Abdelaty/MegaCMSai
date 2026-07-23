const sampleConversations = [
  'Welcome conversation',
  'Project questions',
  'Content ideas',
]

function Sidebar({ onNewChat }) {
  return (
    <aside className="sidebar">
      <div className="brand">MegaCMS AI</div>

      <button className="new-chat-button" type="button" onClick={onNewChat}>
        + New chat
      </button>

      <nav className="conversation-list" aria-label="Recent conversations">
        <h2>Recent chats</h2>
        {sampleConversations.map((conversation) => (
          <button
            className="conversation-button"
            type="button"
            key={conversation}
          >
            {conversation}
          </button>
        ))}
      </nav>
    </aside>
  )
}

export default Sidebar
