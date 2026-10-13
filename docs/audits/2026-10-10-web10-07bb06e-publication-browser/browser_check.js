(async () => {
  const response = await fetch('/api/pursue');
  if (!response.ok) throw new Error(`pursuit API: ${response.status}`);
  const envelope = await response.json();
  return {
    title: document.title,
    url: location.href,
    text: document.getElementById('pursue-status').textContent,
    message: document.getElementById('message').textContent,
    startHidden: document.getElementById('pursue-start').hidden,
    stopHidden: document.getElementById('pursue-stop').hidden,
    view: envelope.data,
  };
})()
