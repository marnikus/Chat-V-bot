"""Message injection into Virt-Chat textarea via CDP."""

import logging
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")

# Verified selector from saved HTML
TEXTAREA_SELECTOR = "textarea[placeholder='Сообщение']"
TEXTAREA_FALLBACK = "textarea#mat-input-1"


async def type_message(cdp: CDPClient, text: str, typing_speed_ms: int = 30) -> bool:
    """Set textarea value and dispatch Angular-compatible input events."""
    esc = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    js = f"""(function(){{
        var ta = document.querySelector('{TEXTAREA_SELECTOR}')
            || document.querySelector('{TEXTAREA_FALLBACK}');
        if(!ta) return false;
        ta.focus();
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype,'value').set;
        setter.call(ta,'{esc}');
        ta.dispatchEvent(new Event('input',{{bubbles:true}}));
        ta.dispatchEvent(new Event('change',{{bubbles:true}}));
        return true;
    }})()"""
    result = await cdp.evaluate(js)
    if result:
        log.info("Message typed (%d chars)", len(text))
        return True
    log.error("Textarea not found for message injection")
    return False


async def click_send(cdp: CDPClient) -> bool:
    """Click the send button (submit type with 'send' icon)."""
    js = """(function(){
        var btn = document.querySelector("button[type='submit']");
        if(btn){btn.click(); return true;}
        var icons = document.querySelectorAll('mat-icon');
        for(var i=0;i<icons.length;i++){
            if(icons[i].textContent.trim()==='send'){
                icons[i].closest('button').click(); return true;
            }
        }
        return false;
    })()"""
    result = await cdp.evaluate(js)
    if result:
        log.info("Send button clicked")
        return True
    log.error("Send button not found")
    return False
