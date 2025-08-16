document.addEventListener('DOMContentLoaded', () => {
  const messagesContainer = document.getElementById('messagesContainer');
  const sendBtn = document.getElementById('sendButton');
  const messageInput = document.getElementById('messageInput');
  const platformSelect = document.getElementById('platformSelect');
  const recipientInput = document.getElementById('recipientInput');

  function renderMessage(msg) {
    const div = document.createElement('div');
    div.className = msg.direction === 'out' ? 'msg out' : 'msg in';
    div.textContent = `[${msg.platform}] ${msg.sender}: ${msg.content}`;
    messagesContainer.appendChild(div);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  async function loadMessages() {
    const res = await fetch('/api/messages');
    const data = await res.json();
    messagesContainer.innerHTML = '';
    data.forEach(renderMessage);
  }

  async function sendMessage() {
    const content = messageInput.value.trim();
    if (!content) return;

    const platform = platformSelect.value;
    const recipient = recipientInput.value.trim() || null;

    await fetch('/api/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platform,
        sender: "You",
        recipient,
        content,
        direction: "out"
      })
    });

    messageInput.value = '';
    await loadMessages();
  }

  sendBtn.addEventListener('click', sendMessage);
  messageInput.addEventListener('keypress', e => {
    if (e.key === 'Enter') sendMessage();
  });

  loadMessages();
  setInterval(loadMessages, 5000); // Poll every 5s
});
