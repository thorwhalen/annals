/* annals media progress: tells the annals page what a framed document is playing.
   The server inlines this into published html pages (annals.media). A spoken overview is
   such a page, shown in a sandboxed frame, so only the frame can see its <audio>; this
   script relays what it plays to the page around it, which records what was heard
   (annals.listening). It does nothing in a page opened on its own (no parent).
   To the parent:  {annals: "media", why, t, d, playing, ended, played}   (seconds)
     played is the element's own record of what it played ([[start, end], ...]), right
     across seeking, playback speed and a locked screen that held the events back.
     on play, pause, seeking, seeked, ended, loadedmetadata, and timeupdate at most once
     per THROTTLE_MS.
   From the parent: {annals: "media-cmd", seek: s}: start the audio at s seconds (applied
     when the audio is ready, or on its first play: a player may build its element late).
   An element is found when it plays (HTMLMediaElement.play is wrapped, which also catches
   an Audio() never added to the page) or when a media event reaches the document.
   Replaying from a chosen point after the end: in WebKit (Safari, every iPhone and iPad
   browser) a seek made on an ended element and then play() starts from the end, which ends
   at once, or from 0, not from the chosen point (a transcript line tapped after the audio
   finished). So the wrapped play() of an ended element whose seek is still under way waits
   for that seek to land ("seeked"), then plays. The element has played before, so playing
   outside the tap is allowed. Players built before this was fixed at the source get it here. */
(function () {
  "use strict";
  if (window.annalsMedia || window.parent === window) return;
  var THROTTLE_MS = 1000;
  var EVENTS = ["play", "pause", "seeking", "seeked", "ended", "loadedmetadata"];
  var seen = [], pendingSeek = null, lastSent = 0;

  function ranges(tr) {
    var out = [];
    for (var i = 0; tr && i < tr.length; i++) out.push([tr.start(i), tr.end(i)]);
    return out;
  }
  function post(el, why) {
    try {
      window.parent.postMessage({
        annals: "media", why: why, t: el.currentTime || 0,
        d: isFinite(el.duration) ? el.duration : null,
        playing: !el.paused && !el.ended, ended: !!el.ended, played: ranges(el.played)
      }, "*");
    } catch (e) { /* a parent that went away */ }
  }
  function applySeek(el) {
    var at = pendingSeek;
    pendingSeek = null;
    function seek() { if (isFinite(el.duration) && at >= 0 && at < el.duration - 1) el.currentTime = at; }
    if (el.readyState >= 1) seek(); else el.addEventListener("loadedmetadata", seek, { once: true });
  }
  var ENDED_EPS_S = 0.25;   /* this close to the end counts as still at the end */
  var SEEK_WAIT_MS = 1500;  /* play anyway if a seek never reports it landed */
  var endedEls = typeof WeakSet === "function" ? new WeakSet() : null;
  function watch(el) {
    if (seen.indexOf(el) >= 0) return;
    seen.push(el);
    EVENTS.forEach(function (name) { el.addEventListener(name, function () { post(el, name); }); });
    if (endedEls) {
      el.addEventListener("ended", function () { endedEls.add(el); });
      el.addEventListener("playing", function () { endedEls.delete(el); });
    }
    el.addEventListener("timeupdate", function () {
      var now = Date.now();
      if (now - lastSent >= THROTTLE_MS) { lastSent = now; post(el, "timeupdate"); }
    });
    if (pendingSeek !== null) applySeek(el);
  }
  var play = HTMLMediaElement.prototype.play;
  /* true when the element has ended and was since sought to a point before its end */
  function soughtAfterEnd(el) {
    if (!endedEls || !(el.ended || endedEls.has(el))) return false;
    return isFinite(el.duration) && el.currentTime < el.duration - ENDED_EPS_S;
  }
  HTMLMediaElement.prototype.play = function () {
    watch(this);
    var el = this, args = arguments;
    if (!el.seeking || !soughtAfterEnd(el) || typeof Promise !== "function") return play.apply(el, args);
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(go, SEEK_WAIT_MS);
      function go() {
        clearTimeout(timer);
        el.removeEventListener("seeked", go);
        var started = play.apply(el, args);
        if (started && typeof started.then === "function") started.then(resolve, reject); else resolve();
      }
      el.addEventListener("seeked", go);
    });
  };
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
