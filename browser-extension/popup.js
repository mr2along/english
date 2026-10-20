const button = document.querySelector("#download");
const status = document.querySelector("#status");

button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Đang mở bộ tải video trên máy…";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url) throw new Error("Không đọc được địa chỉ tab hiện tại.");

    const page = new URL(tab.url);
    const allowedHosts = new Set([
      "youtube.com",
      "www.youtube.com",
      "m.youtube.com",
      "youtu.be",
    ]);
    if (!allowedHosts.has(page.hostname.toLowerCase())) {
      throw new Error("Hãy mở trang video YouTube trước.");
    }

    const helperPage = new URL("http://127.0.0.1:8765/download");
    helperPage.searchParams.set("url", tab.url);
    await chrome.tabs.create({ url: helperPage.toString() });
    status.textContent = "Đã mở bộ tải. Theo dõi tiến trình ở tab mới.";
  } catch (error) {
    status.textContent = error?.message || "Không mở được bộ tải trên máy.";
  } finally {
    button.disabled = false;
  }
});
