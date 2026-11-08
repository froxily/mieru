(function () {
  var preference = "system";
  var resolved = "light";
  try {
    var stored = window.localStorage.getItem("mieru-theme");
    if (stored === "light" || stored === "dark") preference = stored;
  } catch (error) {}
  try {
    resolved = preference === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : preference;
  } catch (error) {}
  var root = document.documentElement;
  root.setAttribute("data-theme", resolved);
  root.style.colorScheme = resolved;
  var introPending = true;
  try {
    introPending = !window.sessionStorage.getItem("mieru:intro-seen");
  } catch (error) {}
  if (introPending) root.setAttribute("data-intro", "");
})();
