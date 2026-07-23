const sampleConversations = [
  'Welcome conversation',
  'Project questions',
  'Content ideas',
]

const exampleButtons = Array.from({ length: 8 }, (_, index) => ({
  id: index + 1,
  label: 'Example button',
}))

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

      <section className="sidebar-menu">
        <h2>Menu</h2>
        <div className="sidebar-button-grid">
          {exampleButtons.map((button) => (
            <button
              className="sidebar-grid-button"
              type="button"
              key={button.id}
            >
              {button.label}
            </button>
          ))}
        </div>
      </section>
    </aside>
  )
}

export default Sidebar
