/* bot-chat.js — BotChat facade (H-B2b JS split, 397→~30)

Parts loaded before this one — see index.html:
  bot-chat-core.js, bot-chat-bridge.js, bot-chat-cards.js, bot-chat-send.js

Public API unchanged: window.BotChat
*/

'use strict';

const BotChat = {};

UIHelpers.mergeParts(BotChat, BotChatCore, BotChatBridge, BotChatCards, BotChatSend);

if (typeof window !== 'undefined') window.BotChat = BotChat;
if (typeof module === 'object' && module.exports) module.exports = BotChat;
