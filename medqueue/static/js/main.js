// Shared behaviour: poll unread notification count for the bell badge.
(function () {
  const badge = document.getElementById("unread-badge");
  if (!badge) return;

  async function refresh() {
    try {
      const res = await fetch("/api/notifications/unread_count");
      if (!res.ok) return;
      const data = await res.json();
      if (data.count > 0) {
        badge.textContent = data.count > 9 ? "9+" : data.count;
        badge.style.display = "flex";
      } else {
        badge.style.display = "none";
      }
    } catch (e) {
      /* silent */
    }
  }

  refresh();
  setInterval(refresh, 15000);
})();
