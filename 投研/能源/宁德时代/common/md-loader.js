/**
 * MdLoader — 通用 MD 文件加载与解析模块
 * 
 * 职责：fetch MD 文件 → 缓存 → 按需提取章节/字段 → 支持两种使用模式
 *   A. 自动模式：扫描 DOM 中 .md-content 元素，自动注入（用于研报 HTML）
 *   B. 手动模式：调用 MdLoader.get(key) / extractSection() 自行渲染（用于 model.html）
 * 
 * 使用方式：
 *   <script src="../../common/md-loader.js"></script>
 *   <script>
 *     MdLoader.init({
 *       files: [
 *         { key: 'main', path: '定性分析/换电业务相变与估值影响.md' },
 *         { key: 'ref',  path: '定性分析/换电业务探讨.md' }
 *       ],
 *       autoPopulate: true  // 可选，默认 false。true 时自动扫描 .md-content 元素
 *     }).then(function() {
 *       // 所有文件加载完成，可安全调用 MdLoader.get('main') 等
 *       yourInitFunction();
 *     });
 *   </script>
 * 
 * 依赖：无外部依赖，纯 vanilla JS
 * 协议限制：file:// 协议下 fetch 无法读取本地文件，需通过 HTTP 服务打开
 */

var MdLoader = (function() {
  'use strict';

  /* ============================================================
   * 内部状态
   * ============================================================ */
  var _cache = {};           // { key: mdText | null }
  var _hlCache = {};         // { key: hlData | null }  高亮标注数据
  var _readyPromise = null;  // 加载完成 Promise
  var _isFileProtocol = (location.protocol === 'file:');

  /* ============================================================
   * 公开 API
   * ============================================================ */

  /**
   * 初始化：加载所有配置的 MD 文件
   * @param {Object} config
   * @param {Array}  config.files        - [{key: '别名', path: '相对路径.md'}, ...]
   * @param {boolean} [config.autoPopulate] - 是否自动扫描 .md-content 并注入（默认 false）
   * @returns {Promise} 所有文件加载完成后 resolve
   */
  function init(config) {
    if (_readyPromise) return _readyPromise;

    if (_isFileProtocol) {
      console.warn('[MdLoader] file:// 协议下无法 fetch 本地文件，请通过 HTTP 服务打开');
      _readyPromise = Promise.resolve();
      if (config.autoPopulate) {
        _autoPopulateError();
      }
      return _readyPromise;
    }

    var files = config.files || [];
    if (!files.length) {
      _readyPromise = Promise.resolve();
      return _readyPromise;
    }

    var tasks = files.map(function(f) {
      var mdPath = f.path;
      var hlPath = f.path.replace(/\.md$/, '.hl.json');

      return Promise.all([
        /* MD 文件（必须） */
        fetch(mdPath)
          .then(function(resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.text();
          })
          .then(function(text) {
            _cache[f.key] = text;
          })
          .catch(function(err) {
            console.warn('[MdLoader] MD 加载失败: ' + mdPath, err.message);
            _cache[f.key] = null;
          }),
        /* 高亮标注文件（可选，不存在时静默跳过） */
        fetch(hlPath)
          .then(function(resp) {
            if (!resp.ok) return null;
            return resp.json();
          })
          .then(function(data) {
            _hlCache[f.key] = data || null;
          })
          .catch(function() {
            _hlCache[f.key] = null;
          })
      ]);
    });

    _readyPromise = Promise.all(tasks).then(function() {
      if (config.autoPopulate) {
        _autoPopulate();
      }
    });
    return _readyPromise;
  }

  /**
   * 同步获取已缓存的 MD 原文
   * @param {string} key - 文件别名
   * @returns {string|null} MD 文本，未加载或加载失败返回 null
   */
  function get(key) {
    return _cache.hasOwnProperty(key) ? _cache[key] : null;
  }

  /**
   * 判断当前是否 file:// 协议
   * @returns {boolean}
   */
  function isFileProtocol() {
    return _isFileProtocol;
  }

  /**
   * 从 MD 文本中按标题锚点提取章节
   * @param {string} mdText    - MD 全文
   * @param {string} anchor    - 章节标题关键词（匹配 # heading 行，如 "4.3"）
   * @param {string} [endAnchor] - 结束锚点（如 "4.4"），默认到下一个同级标题
   * @param {boolean} [excludeEnd] - true 时排除 endAnchor 章节
   * @returns {{summary:string, detail:string}} summary=第一段文本, detail=完整章节原文
   */
  function extractSection(mdText, anchor, endAnchor, excludeEnd) {
    if (!mdText) return { summary: '', detail: '' };

    var lines = mdText.split('\n');
    var startIdx = -1, endIdx = lines.length;

    // 找起始锚点
    for (var i = 0; i < lines.length; i++) {
      var heading = lines[i].trim();
      if (heading.match(/^#{1,4}\s/) && heading.indexOf(anchor) !== -1) {
        startIdx = i;
        break;
      }
    }
    if (startIdx === -1) return { summary: '', detail: '' };

    // 确定结束位置
    var headingLevel = (lines[startIdx].match(/^(#{1,4})/) || [''])[1].length;

    if (endAnchor) {
      // 找到 endAnchor 行
      var endAnchorIdx = -1;
      for (var m = startIdx + 1; m < lines.length; m++) {
        var h2 = lines[m].trim();
        if (h2.match(/^#{1,4}\s/) && h2.indexOf(endAnchor) !== -1) {
          endAnchorIdx = m;
          break;
        }
      }
      if (endAnchorIdx > 0) {
        if (excludeEnd) {
          endIdx = endAnchorIdx;
        } else {
          var endLevel = (lines[endAnchorIdx].match(/^(#{1,4})/) || [''])[1].length;
          for (var j = endAnchorIdx + 1; j < lines.length; j++) {
            var h = lines[j].trim();
            if (h.match(/^#{1,4}\s/)) {
              var level = (h.match(/^(#{1,4})/) || [''])[1].length;
              if (level <= endLevel) { endIdx = j; break; }
            }
          }
        }
      }
    } else {
      // 到下一个同级或更高级标题
      for (var k = startIdx + 1; k < lines.length; k++) {
        var h3 = lines[k].trim();
        if (h3.match(/^#{1,4}\s/)) {
          var lvl = (h3.match(/^(#{1,4})/) || [''])[1].length;
          if (lvl <= headingLevel) { endIdx = k; break; }
        }
      }
    }

    var sectionLines = lines.slice(startIdx, endIdx);
    var sectionText = sectionLines.join('\n');

    // 提取 summary：标题后第一段非空文本
    var summary = '';
    for (var s = 1; s < sectionLines.length; s++) {
      var line = sectionLines[s].trim();
      if (line && !line.match(/^#{1,4}\s/) && !line.match(/^```/) && !line.match(/^\|/)) {
        summary = line.replace(/^>\s*/, '');
        break;
      }
    }
    if (!summary) summary = sectionLines[0].replace(/^#{1,4}\s*/, '');

    return { summary: summary, detail: sectionText };
  }

  /**
   * 从 MD 浓缩版 chunk 中提取标题/摘要/内容三个字段
   * 浓缩版格式：#### 标题 / #### 摘要 / #### 内容
   * @param {string} chunk - 浓缩版模块的文本
   * @returns {{title:string, summary:string, content:string}|null}
   */
  function extractMdFields(chunk) {
    var titleMatch   = chunk.match(/####\s+标题\s*\n([\s\S]*?)(?=\n####\s|\n###\s|\n##\s|$)/);
    var summaryMatch = chunk.match(/####\s+摘要\s*\n([\s\S]*?)(?=\n####\s|\n###\s|\n##\s|$)/);
    var contentMatch = chunk.match(/####\s+内容\s*\n([\s\S]*?)(?=\n##\s|\n###\s浓缩版|$)/);

    if (!titleMatch && !summaryMatch && !contentMatch) return null;

    return {
      title:   titleMatch   ? titleMatch[1].trim()   : '',
      summary: summaryMatch ? summaryMatch[1].trim() : '',
      content: contentMatch ? contentMatch[1].trim() : ''
    };
  }

  /**
   * 简易 Markdown → HTML（段落 + 粗体 + 高亮）
   * @param {string} text - MD 文本
   * @param {Array}  [highlights] - 高亮标注数组 [{text, color}, ...]
   * @returns {string} HTML
   */
  function mdToHtml(text, highlights) {
    if (!text) return '';
    var paras = text.split(/\n\n+/);
    return paras.map(function(p) {
      p = p.trim();
      if (!p) return '';
      p = p.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
      if (highlights && highlights.length) {
        p = applyHighlights(p, highlights);
      }
      return '<p style="line-height:1.85;margin-bottom:8px">' + p + '</p>';
    }).join('\n');
  }

  /**
   * 对 HTML 文本应用语义高亮标注
   * 原理：将标注文本替换为 <span> 包裹的彩色文本
   *       使用占位符防止重复匹配，按长度降序避免短词覆盖长词
   * @param {string} html - 已转义为 HTML 的文本（含 <b> 等标签）
   * @param {Array}  annotations - [{text: "失血", color: "red"}, ...]
   * @returns {string} 带高亮 <span> 的 HTML
   */
  function applyHighlights(html, annotations) {
    if (!annotations || !annotations.length) return html;

    /* 按文本长度降序排列，避免短词覆盖长词 */
    var sorted = annotations.slice().sort(function(a, b) {
      return b.text.length - a.text.length;
    });

    /* 第一步：用唯一占位符替换标注文本（仅替换 HTML 标签外的文本） */
    var placeholders = [];
    sorted.forEach(function(ann, i) {
      var placeholder = '\x00HL' + i + '\x00';
      var colorVar = '--' + ann.color;
      var span = '<span style="color:var(' + colorVar + ');font-weight:600">' +
                 ann.text + '</span>';
      placeholders.push({ph: placeholder, span: span});

      /* 按 HTML 标签拆分，只对文本段做替换 */
      html = html.split(/(<[^>]+>)/).map(function(part) {
        if (part.charAt(0) === '<') return part;
        return part.split(ann.text).join(placeholder);
      }).join('');
    });

    /* 第二步：将占位符替换为实际的 <span> 标签 */
    placeholders.forEach(function(p) {
      html = html.split(p.ph).join(p.span);
    });

    return html;
  }

  /* ============================================================
   * 内部函数：自动扫描 .md-content 元素并注入（模式 A）
   * ============================================================ */

  /**
   * 从 MD 文本中定位指定 section-id 的浓缩版模块
   * @param {string} mdText - MD 全文
   * @param {string} sectionId - 如 "L2 - 2.0"
   * @returns {string|null} 浓缩版 chunk 文本
   */
  function _findCondensedSection(mdText, sectionId) {
    var escaped = sectionId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var secPattern = new RegExp('###\\s+浓缩版[：:]\\s*' + escaped + '\\s*\\n');
    var secMatch = mdText.match(secPattern);
    if (!secMatch) return null;
    return mdText.substring(secMatch.index + secMatch[0].length);
  }

  /** 自动扫描并注入所有 .md-content 元素 */
  function _autoPopulate() {
    var cards = document.querySelectorAll('.md-content[data-md-src-key][data-md-section]');
    if (!cards.length) return;

    cards.forEach(function(card) {
      var key = card.getAttribute('data-md-src-key');
      var sectionId = card.getAttribute('data-md-section');
      var mdText = _cache[key];
      var hlData = _hlCache[key] || {};

      if (!mdText) {
        _setCardError(card, 'MD 内容未加载');
        return;
      }

      var chunk = _findCondensedSection(mdText, sectionId);
      if (!chunk) {
        _setCardError(card, '未找到浓缩版: ' + sectionId);
        return;
      }

      var fields = extractMdFields(chunk);
      if (!fields) {
        _setCardError(card, '字段解析失败: ' + sectionId);
        return;
      }

      /* 取该 section 的高亮标注 */
      var sectionHl = hlData[sectionId] || {};
      var titleHl   = sectionHl.title   || [];
      var summaryHl = sectionHl.summary || [];
      var contentHl = sectionHl.content || [];

      var titleEl   = card.querySelector('.md-title');
      var summaryEl = card.querySelector('.md-summary');
      var bodyEl    = card.querySelector('.md-content-body');
      var srcEl     = card.querySelector('.md-src-ref');

      /* 标题：纯文本 + 高亮（无 ** 标记，直接应用） */
      if (titleEl) {
        titleEl.innerHTML = titleHl.length
          ? applyHighlights(fields.title, titleHl)
          : fields.title;
      }
      /* 摘要：纯文本 + 高亮 */
      if (summaryEl) {
        summaryEl.innerHTML = summaryHl.length
          ? applyHighlights(fields.summary, summaryHl)
          : fields.summary;
      }
      /* 内容：MD→HTML + 高亮 */
      if (bodyEl) {
        bodyEl.innerHTML = mdToHtml(fields.content, contentHl);
      }
      if (srcEl) srcEl.textContent = '来源：' + key;
    });
  }

  /** file:// 协议下统一显示错误提示 */
  function _autoPopulateError() {
    var cards = document.querySelectorAll('.md-content[data-md-src-key][data-md-section]');
    cards.forEach(function(card) {
      _setCardError(card, '需通过 HTTP 服务打开（file:// 协议不支持 fetch）');
    });
  }

  /** 设置子卡错误状态 */
  function _setCardError(card, msg) {
    var titleEl = card.querySelector('.md-title');
    if (titleEl) titleEl.textContent = '⚠ ' + msg;
  }

  /* ============================================================
   * 暴露公开接口
   * ============================================================ */
  return {
    init:             init,
    get:              get,
    isFileProtocol:   isFileProtocol,
    extractSection:   extractSection,
    extractMdFields:  extractMdFields,
    mdToHtml:         mdToHtml,
    applyHighlights:  applyHighlights
  };

})();