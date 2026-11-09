/* annals media progress: tells the annals page what a framed document is playing.
   The server inlines this into published html pages (annals.media). A spoken overview is
   such a page, shown in a sandboxed frame, so only the frame can see its <audio>; this
   script relays what it plays to the page around it, which records what was heard
   (annals.listening). It does nothing in a page opened on its own (no parent).
   To the parent:  {annals: "media", why, t, d, playing, ended}   (t, d in seconds)
     on play, pause, seeking, seeked, ended, loadedmetadata, and timeupdate at most once
     per THROTTLE_MS.
   From the parent: {annals: "media-cmd", seek: s}: start the audio at s seconds (applied
     when the audio is ready, or on its first play: a player may build its element late).
   An element is found when it plays (HTMLMediaElement.play is wrapped, which also catches
   an Audio() never added to the page) or when a media event reaches the document. */
(function () {
  "use strict";
  if (window.annalsMedia || window.parent === window) return;
  var THROTTLE_MS = 1000;
  var EVENTS = ["play", "pause", "seeking", "seeked", "ended", "loadedmetadata"];
  var seen = [], pendingSeek = null, lastSent = 0;

  function post(el, why) {
    try {
      window.parent.postMessage({
        annals: "media", why: why, t: el.currentTime || 0,
        d: isFinite(el.duration) ? el.duration : null,
        playing: !el.paused && !el.ended, ended: !!el.ended
      }, "*");
    } catch (e) { /* a parent that went away */ }
  }
  function applySeek(el) {
    var at = pendingSeek;
    pendingSeek = null;
    function seek() { if (isFinite(el.duration) && at >= 0 && at < el.duration - 1) el.currentTime = at; }
    if (el.readyState >= 1) seek(); else el.addEventListener("loadedmetadata", seek, { once: true });
  }
  function watch(el) {
    if (seen.indexOf(el) >= 0) return;
    seen.push(el);
    EVENTS.forEach(function (name) { el.addEventListener(name, function () { post(el, name); }); });
    el.addEventListener("timeupdate", function () {
      var now = Date.now();
      if (now - lastSent >= THROTTLE_MS) { lastSent = now; post(el, "timeupdate"); }
    });
    if (pendingSeek !== null) applySeek(el);
  }
  var play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () { watch(this); return play.apply(this, arguments); };
  ["play", "loadedmetadata"].forEach(function (name) {
    document.addEventListener(name, function (e) { if (e.target instanceof HTMLMediaElement) watch(e.target); }, true);
  });
  window.addEventListener("message", function (e) {
    var m = e.data;
    if (e.source !== window.parent || !m || m.annals !== "media-cmd") return;
    if (typeof m.seek === "number" && isFinite(m.seek)) {
      pendingSeek = m.seek;
      var els = seen.length ? seen : Array.prototype.slice.call(document.querySelectorAll("audio,video"));
      if (els.length) { watch(els[0]); if (pendingSeek !== null) applySeek(els[0]); }
    }
  });
  window.annalsMedia = { watch: watch };
})();
