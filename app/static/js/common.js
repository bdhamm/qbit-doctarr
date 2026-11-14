// Shared utility functions for qbit-doctarr pages.
// Loaded by every page that needs these helpers, before the page's own script.
// Keep this file small — only functions with more than one caller belong here.

/**
 * Escape a value for safe insertion into HTML.
 * Prevents user-controlled data (media titles, torrent names, task details)
 * from breaking the DOM or opening the door to XSS.
 */
function escapeHTML(str) {
    str = String(str);
    return str.replace(/[&<>'"]/g, tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    }[tag]));
}
