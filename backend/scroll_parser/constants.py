"""Immutable vocabulary of the virtual-scroll parse.

`_EXTRACT_JS` is the one DOM probe that reads both the rendered people and the
scroll geometry in a single ``evaluate()`` call, so "is more content loading?"
and "are we at the bottom?" are answered together. `STOPPED` is the sentinel
that distinguishes "the user halted the run" from "the page context was lost".
"""

#: One round trip returns both the rendered people AND the scroll geometry, so
#: "is more content loading?" and "are we at the bottom?" can be answered from
#: a single evaluate() call.
_EXTRACT_JS = """(function(){
    var vp = document.querySelector(%(vp)s);
    var items = document.querySelectorAll('user-item');
    var users = [];
    items.forEach(function(item){
        var wrapper = item.querySelector('.avatar-wrapper');
        var badge = item.querySelector('.badge');
        var nickEl = item.querySelector('.primary-text');
        if(!wrapper||!nickEl) return;
        var cl = wrapper.classList;
        users.push({
            nick: nickEl.textContent.trim(),
            female: cl.contains('female-avatar'),
            male: cl.contains('male-avatar'),
            guest: cl.contains('guest-avatar'),
            registered: badge ? badge.classList.contains('registered-badge') : false,
            anonymous: badge ? badge.classList.contains('anonymous-badge') : false
        });
    });
    var top = 0, height = 0, client = 0;
    if (vp) {
        top = vp.scrollTop || 0;
        height = vp.scrollHeight || 0;
        client = vp.clientHeight || 0;
    }
    return JSON.stringify({
        users: users, count: users.length, viewport: !!vp,
        scrollTop: top, scrollHeight: height, clientHeight: client,
        atBottom: !!vp && (top + client >= height - 4)
    });
})()""" 


#: Returned by :meth:`ScrollParser._settle` when the user stopped the run
#: before any snapshot could be taken — distinct from ``None``, which means
#: the page context was genuinely lost.
STOPPED = object()
