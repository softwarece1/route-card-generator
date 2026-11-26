(function () {
  try {
    var key = "rc-theme";
    var t = localStorage.getItem(key);
    if (t !== "light" && t !== "dark") {
      t =
        window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    }
    document.documentElement.setAttribute("data-theme", t);
    document.documentElement.style.colorScheme = t;
  } catch (e) {}
})();
