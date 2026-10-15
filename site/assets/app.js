/* 新闻联播 · 文字版 前端渲染（原生 JS，无依赖） */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var WEEK = ["日", "一", "二", "三", "四", "五", "六"];
  var dates = [];
  var current = null;

  /* ---------- 视频播放 ---------- */

  var activePlayerCleanup = null; // 当前已挂载播放器的清理函数
  var infoCache = new Map();      // guid -> Promise<接口返回>

  function loadVideoInfo(guid) {
    if (!infoCache.has(guid)) {
      infoCache.set(guid, fetch(
        "https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid=" + encodeURIComponent(guid),
        { cache: "no-store" }
      ).then(function (r) {
        if (!r.ok) throw new Error("接口返回 HTTP " + r.status);
        return r.json();
      }).then(function (info) {
        var chs = (((info || {}).video || {}).chapters) || [];
        chs = chs.filter(function (c) { return c && c.url; });
        if (!chs.length) throw new Error("接口未返回可播放的视频分段");
        return info;
      }).catch(function (e) {
        infoCache.delete(guid); // 失败不缓存，允许重试
        throw e;
      }));
    }
    return infoCache.get(guid);
  }

  function unmountPlayer() {
    if (activePlayerCleanup) {
      try { activePlayerCleanup(); } catch (e) { /* 忽略 */ }
      activePlayerCleanup = null;
    }
  }

  function mountPlayer(mount, opts) {
    unmountPlayer();
    activePlayerCleanup = buildPlayer(mount, opts);
  }

  function buildPlayer(mount, opts) {
    var cleaned = false;
    var video = null;
    var chapters = [];
    var chapterIdx = 0;

    var root = el("div", "player");
    var head = el("div", "player-head");
    head.appendChild(el("span", "player-title", opts.title || "视频播放"));
    var segLabel = el("span", "player-seg");
    head.appendChild(segLabel);
    var closeBtn = el("button", "player-close", "✕ 关闭");
    head.appendChild(closeBtn);
    root.appendChild(head);

    var body = el("div", "player-body", "正在解析视频地址…");
    root.appendChild(body);
    mount.innerHTML = "";
    mount.appendChild(root);

    function cleanup() {
      cleaned = true;
      try {
        if (video) {
          video.pause();
          video.removeAttribute("src");
          video.load();
        }
      } catch (e) { /* 忽略 */ }
      video = null;
      mount.innerHTML = "";
    }
    closeBtn.addEventListener("click", cleanup);

    function showFallback(msg) {
      body.innerHTML = "";
      var box = el("div", "notice", msg);
      if (opts.fallbackUrl) {
        var a = document.createElement("a");
        a.href = opts.fallbackUrl;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = "前往央视网观看 ↗";
        box.appendChild(document.createElement("br"));
        box.appendChild(a);
      }
      body.appendChild(box);
    }

    loadVideoInfo(opts.guid).then(function (info) {
      if (cleaned) return;
      chapters = (((info.video || {}).chapters) || []).filter(function (c) { return c && c.url; });

      body.innerHTML = "";
      video = document.createElement("video");
      video.controls = true;
      video.autoplay = true;
      video.playsInline = true;
      video.preload = "metadata";
      if (info.image) video.poster = info.image;
      body.appendChild(video);

      video.addEventListener("error", function () {
        showFallback("视频加载失败，地址可能已失效。");
      });

      if (chapters.length > 1) {
        segLabel.textContent = "分段 1/" + chapters.length;
        video.addEventListener("ended", function () {
          if (chapterIdx < chapters.length - 1) {
            chapterIdx += 1;
            video.src = chapters[chapterIdx].url;
            segLabel.textContent = "分段 " + (chapterIdx + 1) + "/" + chapters.length;
            var p = video.play();
            if (p) p.catch(function () { /* 需用户手动点击 */ });
          }
        });
      }

      video.src = chapters[0].url;
      var p = video.play();
      if (p) p.catch(function () { /* 自动播放被浏览器拦截时，用户点播放键即可 */ });
    }).catch(function (e) {
      if (!cleaned) showFallback("视频地址解析失败：" + e.message);
    });

    return cleanup;
  }

  /* ---------- 基础工具 ---------- */

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function fmtDate(iso) {
    var d = new Date(iso + "T00:00:00");
    return d.getFullYear() + " 年 " + (d.getMonth() + 1) + " 月 " + d.getDate() +
      " 日 · 星期" + WEEK[d.getDay()];
  }

  function durText(doc) {
    if (doc.duration_text) return doc.duration_text;
    if (typeof doc.duration_seconds === "number") {
      var s = Math.round(doc.duration_seconds);
      var m = Math.floor(s / 60);
      return (m >= 60 ? Math.floor(m / 60) + " 小时 " : "") + (m % 60) + " 分 " + (s % 60) + " 秒";
    }
    return "";
  }

  function setStatus(t) { $("status").textContent = t || ""; }

  /* ---------- 数据加载 ---------- */

  function loadIndex() {
    return fetch("data/index.json", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("无法读取 data/index.json（HTTP " + r.status + "）");
      return r.json();
    });
  }

  function loadDay(d) {
    return fetch("data/" + d + ".json", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("没有 " + d + " 的数据文件");
      return r.json();
    });
  }

  /* ---------- 渲染 ---------- */

  function renderIndex(idx) {
    dates = idx.dates || [];
    var sel = $("dateSelect");
    sel.innerHTML = "";
    dates.forEach(function (d) {
      var o = document.createElement("option");
      o.value = d;
      o.textContent = d;
      sel.appendChild(o);
    });
    $("updated").textContent = "数据更新于 " + (idx.updated_at || "—") +
      " · 已收录 " + dates.length + " 期";
  }

  function chip(text, href) {
    var li = el("li");
    if (href) {
      var a = document.createElement("a");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = text;
      li.appendChild(a);
    } else {
      li.textContent = text;
    }
    return li;
  }

  function chipBtn(text, onClick) {
    var li = el("li", "bare");
    var b = el("button", "chip-btn", text);
    b.addEventListener("click", onClick);
    li.appendChild(b);
    return li;
  }

  function makePara(text, isFirst) {
    var p = el("p");
    if (isFirst && text.indexOf("央视网消息") === 0) {
      var i = text.indexOf("：");
      if (i > 0 && i < 24) {
        p.className = "lead-strong";
        p.appendChild(document.createElement("strong")).textContent = text.slice(0, i + 1);
        p.appendChild(document.createTextNode(text.slice(i + 1)));
        return p;
      }
    }
    p.textContent = text;
    return p;
  }

  function renderDay(doc) {
    unmountPlayer();

    var meta = $("meta");
    meta.innerHTML = "";

    meta.appendChild(el("p", "date-line", fmtDate(doc.date)));
    var chips = el("ul", "chips");
    if (doc.air_time) chips.appendChild(chip("播出 " + doc.air_time.slice(11, 16)));
    var dt = durText(doc);
    if (dt) chips.appendChild(chip("时长 " + dt));
    chips.appendChild(chip("共 " + doc.segment_count + " 条"));
    if (doc.guid) {
      chips.appendChild(chipBtn("▶ 播放完整版", function () {
        var mount = $("player");
        mountPlayer(mount, { guid: doc.guid, title: doc.title, fallbackUrl: doc.episode_url });
        mount.scrollIntoView({ behavior: "smooth", block: "center" });
      }));
    }
    if (doc.episode_url) chips.appendChild(chip("官方页面 ↗", doc.episode_url));
    meta.appendChild(chips);

    var toc = $("toc");
    toc.innerHTML = "";
    doc.segments.forEach(function (s) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "#seg-" + s.no;
      a.textContent = s.title;
      li.appendChild(a);
      toc.appendChild(li);
    });
    $("tocBox").open = window.innerWidth > 900;

    var box = $("articles");
    box.innerHTML = "";
    doc.segments.forEach(function (s) {
      var art = el("article", "entry");
      art.id = "seg-" + s.no;

      var h2 = el("h2");
      h2.appendChild(el("span", "no", String(s.no)));
      h2.appendChild(document.createTextNode(s.title));
      art.appendChild(h2);

      var m = el("div", "entry-meta");
      if (s.duration_text) m.appendChild(document.createTextNode("时长 " + s.duration_text + "　"));
      if (s.guid) {
        m.appendChild(chipBtn("▶ 播放本条", function () {
          mountPlayer(art.querySelector(".player-mount"), {
            guid: s.guid, title: s.title, fallbackUrl: s.url
          });
        }));
        m.appendChild(document.createTextNode("　"));
      }
      if (s.url) {
        var a = document.createElement("a");
        a.href = s.url;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = "央视网 ↗";
        m.appendChild(a);
      }
      art.appendChild(m);

      var mount = el("div", "player-mount");
      art.appendChild(mount);

      var body = el("div", "entry-body");
      if (s.paragraphs && s.paragraphs.length) {
        s.paragraphs.forEach(function (t, i) {
          body.appendChild(makePara(t, i === 0));
        });
      } else {
        body.appendChild(el("p", "empty", "（本条为视频/片花，页面未提供文字稿）"));
      }
      art.appendChild(body);
      box.appendChild(art);
    });
  }

  function renderError(msg) {
    var box = $("articles");
    box.innerHTML = "";
    box.appendChild(el("div", "notice", msg));
  }

  /* ---------- 导航 ---------- */

  function updateNav() {
    var i = dates.indexOf(current);
    $("prev").disabled = !(i >= 0 && i < dates.length - 1); // dates 按新→旧排列
    $("next").disabled = !(i > 0);
    var sel = $("dateSelect");
    if (sel.value !== current) sel.value = current;
  }

  function goto(d) {
    if (!d) return;
    current = d;
    updateNav();
    setStatus("加载中…");
    window.scrollTo(0, 0);
    loadDay(d).then(function (doc) {
      renderDay(doc);
      setStatus("");
      if (location.hash.slice(1) !== d) history.replaceState(null, "", "#" + d);
      document.title = "新闻联播文字版 · " + d;
    }).catch(function (e) {
      renderError("加载失败：" + e.message);
      setStatus("");
    });
  }

  function step(delta) {
    var i = dates.indexOf(current);
    var j = i - delta; // dates 新→旧，"前一天"是更旧的一天
    if (j >= 0 && j < dates.length) goto(dates[j]);
  }

  /* ---------- 启动 ---------- */

  $("prev").addEventListener("click", function () { step(-1); });
  $("next").addEventListener("click", function () { step(1); });
  $("print").addEventListener("click", function () { window.print(); });
  $("dateSelect").addEventListener("change", function () { goto(this.value); });
  document.addEventListener("keydown", function (e) {
    var t = e.target.tagName;
    if (t === "SELECT" || t === "INPUT" || t === "TEXTAREA") return;
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
  });
  window.addEventListener("hashchange", function () {
    var h = decodeURIComponent(location.hash.slice(1));
    if (h && h !== current && dates.indexOf(h) >= 0) goto(h);
  });

  loadIndex().then(function (idx) {
    renderIndex(idx);
    if (!dates.length) {
      renderError("暂无数据：请先运行 python xwlb.py fetch 生成数据文件。");
      return;
    }
    var h = decodeURIComponent(location.hash.slice(1));
    goto(dates.indexOf(h) >= 0 ? h : dates[0]);
  }).catch(function (e) {
    renderError(
      "数据加载失败：" + e.message +
      "。请通过 HTTP 访问本页面（例如 http://localhost/xwlb/site/），直接双击 index.html 会因浏览器安全策略无法读取数据文件。"
    );
  });
})();
