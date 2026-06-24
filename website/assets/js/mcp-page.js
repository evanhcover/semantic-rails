(() => {
  const button = document.querySelector("[data-copy-endpoint]");
  const value = document.querySelector("[data-copy-value]");
  if (!button || !value) return;

  button.addEventListener("click", async () => {
    const copied = await window.semanticRailsCopyText(value.textContent.trim());
    const original = button.textContent;
    button.textContent = copied ? "Copied" : "Select URL";
    window.setTimeout(() => {
      button.textContent = original;
    }, 1400);
  });
})();
